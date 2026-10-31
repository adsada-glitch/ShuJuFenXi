"""A SQL-first analyst case: source audit, explicit metrics and aggregate reports."""

import argparse
from contextlib import closing
import io
import itertools
import json
from pathlib import Path
import re
import sqlite3
import zipfile

import numpy as np
import pandas as pd

from .data import PROJECT_ROOT, SOURCE_SHA256, SOURCE_URL, load_ratings


def load_queries():
    """Return the five independently executable named SQL queries."""
    source = (PROJECT_ROOT / "sql" / "analysis.sql").read_text(encoding="utf-8")
    sections = re.split(r"^-- name:\s*(\w+)\s*$", source, flags=re.M)
    return {sections[index]: sections[index + 1].strip() for index in range(1, len(sections), 2)}


def shrink_mean(raw_mean, rating_count, global_mean, prior_strength=50):
    """Deterministic descriptive shrinkage; not a causal or recommendation model."""
    if prior_strength < 0:
        raise ValueError("prior_strength must be nonnegative")
    count = np.asarray(rating_count)
    if (count <= 0).any():
        raise ValueError("rating_count must be positive")
    return (count * np.asarray(raw_mean) + prior_strength * global_mean) / (count + prior_strength)


def _read_metadata(archive):
    with zipfile.ZipFile(archive) as source:
        genre_pairs = [line.rsplit("|", 1) for line in source.read("ml-100k/u.genre").decode("latin-1").splitlines() if line]
        genres = pd.DataFrame([{"genre_id": int(value), "genre": name} for name, value in genre_pairs]).sort_values("genre_id")
        flag_names = [f"genre_{value}" for value in genres.genre_id]
        item_text = source.read("ml-100k/u.item").decode("latin-1")
        expected_columns = 5 + len(flag_names)
        invalid_width = sum(len(line.split("|")) != expected_columns for line in item_text.splitlines())
        if invalid_width:
            raise ValueError(f"u.item has {invalid_width} rows with unexpected column counts")
        raw_movies = pd.read_csv(io.StringIO(item_text), sep="|", keep_default_na=False,
                                 names=["movie_id", "title", "release_date_raw", "video_release_date_raw", "imdb_url"] + flag_names)
        user_ids = [int(line.split("|", 1)[0]) for line in source.read("ml-100k/u.user").decode("latin-1").splitlines() if line]
    return raw_movies, genres, pd.DataFrame({"user_id": user_ids}), flag_names


def normalize_movies(raw_movies, genres, flag_names):
    """Keep distinct movie IDs even when titles repeat; preserve actual genre flags."""
    dates = pd.to_datetime(raw_movies.release_date_raw, format="%d-%b-%Y", errors="coerce")
    movies = raw_movies[["movie_id", "title"]].copy()
    movies["release_date"] = dates.dt.strftime("%Y-%m-%d").where(dates.notna(), None)
    movies["release_year"] = dates.dt.year.astype("Int64")
    membership = raw_movies[["movie_id"] + flag_names].melt(id_vars="movie_id", var_name="flag", value_name="present")
    membership = membership[membership.present == 1].copy()
    membership["genre_id"] = membership.flag.str.removeprefix("genre_").astype(int)
    membership = membership.merge(genres, on="genre_id", validate="many_to_one")
    return movies, membership[["movie_id", "genre_id", "genre"]], dates


def _create_schema(connection):
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript("""
        CREATE TABLE users (user_id INTEGER PRIMARY KEY);
        CREATE TABLE genres (genre_id INTEGER PRIMARY KEY, genre TEXT NOT NULL UNIQUE);
        CREATE TABLE movies (movie_id INTEGER PRIMARY KEY, title TEXT NOT NULL,
                             release_date TEXT, release_year INTEGER);
        CREATE TABLE ratings (
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            movie_id INTEGER NOT NULL REFERENCES movies(movie_id),
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            timestamp INTEGER NOT NULL,
            rated_at_utc TEXT NOT NULL, rating_month TEXT NOT NULL,
            PRIMARY KEY(user_id, movie_id)
        );
        CREATE TABLE movie_genres (
            movie_id INTEGER NOT NULL REFERENCES movies(movie_id),
            genre_id INTEGER NOT NULL REFERENCES genres(genre_id), genre TEXT NOT NULL,
            PRIMARY KEY(movie_id, genre_id)
        );
        CREATE VIEW rating_clean AS SELECT * FROM ratings;
        CREATE INDEX ratings_by_movie ON ratings(movie_id);
        CREATE INDEX ratings_by_month ON ratings(rating_month);
    """)


def prepare_database(data_dir=None):
    """Verify the source archive, audit it and atomically create a local database."""
    data_dir = Path(data_dir or PROJECT_ROOT / "data")
    ratings = load_ratings(data_dir)
    raw_movies, genres, users, flag_names = _read_metadata(data_dir / "ml-100k.zip")
    movies, membership, dates = normalize_movies(raw_movies, genres, flag_names)
    movie_genre_counts = membership.groupby("movie_id").size()
    title_counts = raw_movies.title.value_counts()
    release_present = raw_movies.release_date_raw.ne("")
    rating_time = pd.to_datetime(ratings.timestamp, unit="s", utc=True)
    audit = {
        "source_url": SOURCE_URL, "source_sha256": SOURCE_SHA256,
        "ratings": {"rows": int(len(ratings)), "missing_cells": int(ratings.isna().sum().sum()),
                    "duplicate_user_movie_pairs": int(ratings.duplicated(["user_id", "movie_id"]).sum()),
                    "out_of_range_ratings": int((~ratings.rating.between(1, 5)).sum()),
                    "unique_users": int(ratings.user_id.nunique()), "unique_movies": int(ratings.movie_id.nunique()),
                    "global_mean": float(ratings.rating.mean()),
                    "first_utc": rating_time.min().isoformat(), "last_utc": rating_time.max().isoformat()},
        "movies": {"rows": int(len(raw_movies)), "duplicate_movie_ids": int(raw_movies.movie_id.duplicated().sum()),
                   "missing_titles": int(raw_movies.title.eq("").sum()),
                   "duplicate_title_groups": int((title_counts > 1).sum()),
                   "rows_with_duplicate_titles": int(title_counts[title_counts > 1].sum()),
                   "duplicate_title_extra_rows": int(raw_movies.title.duplicated().sum()),
                   "missing_release_dates": int((~release_present).sum()),
                   "unparseable_nonempty_release_dates": int((release_present & dates.isna()).sum()),
                   "missing_video_release_dates": int(raw_movies.video_release_date_raw.eq("").sum()),
                   "missing_imdb_urls": int(raw_movies.imdb_url.eq("").sum()),
                   "invalid_genre_flag_cells": int((~raw_movies[flag_names].isin([0, 1])).sum().sum()),
                   "movies_with_multiple_genres": int((movie_genre_counts > 1).sum()),
                   "movies_without_genre_flags": int((~movies.movie_id.isin(membership.movie_id)).sum()),
                   "unknown_genre_movies": int(membership.loc[membership.genre.eq("unknown"), "movie_id"].nunique())},
        "integrity": {"orphan_rating_movie_ids": int((~ratings.movie_id.isin(movies.movie_id)).sum()),
                      "orphan_rating_user_ids": int((~ratings.user_id.isin(users.user_id)).sum()),
                      "duplicate_genre_ids": int(genres.genre_id.duplicated().sum()),
                      "duplicate_user_ids": int(users.user_id.duplicated().sum()),
                      "duplicate_movie_genre_pairs": int(membership.duplicated(["movie_id", "genre_id"]).sum())},
        "cleaning_decisions": [
            "保留全部有效评分，1星和5星不是脏数据；不按评分高低删除记录。",
            "电影主键是movie_id，同名不同ID不盲目合并或删除。",
            "发行日期缺失保留NULL；空的视频发行日期不用于业务指标，不补造日期。",
            "genre按源文件真实多标签保留，unknown不替换成其他类型。",
            "数据库和行级中间表仅留在被Git忽略的data目录；对外只保存聚合结果。",
        ],
    }
    if any(audit["integrity"].values()) or audit["movies"]["duplicate_movie_ids"] or audit["movies"]["invalid_genre_flag_cells"]:
        raise ValueError("Source integrity checks failed; inspect the verified source before transforming")
    if audit["movies"]["movies_without_genre_flags"]:
        raise ValueError("Missing genre memberships prevent allocation-weight conservation")
    clean_ratings = ratings.copy()
    clean_ratings["rated_at_utc"] = rating_time.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    clean_ratings["rating_month"] = rating_time.dt.strftime("%Y-%m")
    database = data_dir / "movielens_analyst.sqlite3"
    temporary = data_dir / "movielens_analyst.building.sqlite3"
    temporary.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            _create_schema(connection)
            # Raw snapshots remain local for traceability, separate from normalized tables.
            ratings.to_sql("raw_ratings", connection, index=False)
            raw_movies.to_sql("raw_movies", connection, index=False)
            genres.to_sql("raw_genres", connection, index=False)
            users.to_sql("users", connection, index=False, if_exists="append")
            genres.to_sql("genres", connection, index=False, if_exists="append")
            movies.to_sql("movies", connection, index=False, if_exists="append")
            clean_ratings.to_sql("ratings", connection, index=False, if_exists="append")
            membership.to_sql("movie_genres", connection, index=False, if_exists="append")
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise ValueError("SQLite foreign-key checks failed")
            audit["integrity"]["sqlite_foreign_key_violations"] = len(violations)
            audit["integrity"]["sqlite_foreign_keys_enabled_during_load"] = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
            audit["preservation"] = {
                "clean_rating_rows": int(connection.execute("SELECT COUNT(*) FROM rating_clean").fetchone()[0]),
                "clean_movie_rows": int(connection.execute("SELECT COUNT(*) FROM movies").fetchone()[0]),
                "movie_genre_rows": int(len(membership)),
                "rating_genre_join_rows": int(connection.execute("SELECT COUNT(*) FROM ratings JOIN movie_genres USING(movie_id)").fetchone()[0]),
                "genre_weighted_rating_total": float(connection.execute("""
                    SELECT SUM(1.0 / n_genres) FROM ratings
                    JOIN movie_genres USING(movie_id)
                    JOIN (SELECT movie_id, COUNT(*) AS n_genres FROM movie_genres GROUP BY movie_id) USING(movie_id)
                """).fetchone()[0]),
            }
        assert audit["preservation"]["clean_rating_rows"] == len(ratings)
        assert audit["preservation"]["clean_movie_rows"] == len(movies)
        assert np.isclose(audit["preservation"]["genre_weighted_rating_total"], len(ratings))
        temporary.replace(database)
    finally:
        temporary.unlink(missing_ok=True)
    return database, audit


def _records(frame):
    """Convert NaN to JSON null and numpy scalars to ordinary JSON values."""
    return json.loads(frame.to_json(orient="records"))


def _figures(connection, tables, output):
    # Set a headless backend here; importing analyst does not alter Notebook plotting.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                         "svg.hashsalt": "analyst-case-v1", "font.size": 10})
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        fig.tight_layout()
        destination = figures / f"{name}.svg"
        with matplotlib.rc_context({"svg.fonttype": "none"}):
            fig.savefig(destination, metadata={"Date": None})
        destination.write_text(
            "\n".join(line.rstrip() for line in destination.read_text(encoding="utf-8").splitlines()) + "\n",
            encoding="utf-8", newline="\n",
        )
        plt.close(fig)

    monthly = tables["monthly"]
    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    colors = ["#B8C0C8" if value else "#247BA0" for value in monthly.is_partial_month]
    axes[0].bar(monthly.rating_month, monthly.rating_count, color=colors)
    axes[0].set(ylabel="Observed ratings", title="Monthly activity: grey = partial boundary month")
    axes[1].plot(monthly.rating_month, monthly.scoring_users, color="#D7833F", marker="o")
    axes[1].set(ylabel="Distinct scoring users", xlabel="UTC rating month")
    axes[1].tick_params(axis="x", rotation=30)
    save(fig, "monthly_activity")

    histogram = pd.read_sql_query("""
        SELECT n, COUNT(*) AS movies FROM (
            SELECT m.movie_id, COUNT(r.movie_id) AS n FROM movies m LEFT JOIN ratings r USING(movie_id)
            GROUP BY m.movie_id
        ) GROUP BY n ORDER BY n
    """, connection)
    counts = np.repeat(histogram.n.to_numpy(), histogram.movies.to_numpy())
    x = np.arange(len(counts) + 1) / len(counts)
    y = np.r_[0, np.cumsum(counts) / counts.sum()]
    fig, ax = plt.subplots(figsize=(6.8, 5))
    ax.plot(x, y, label="Observed rating concentration", color="#247BA0", linewidth=2)
    ax.plot([0, 1], [0, 1], linestyle="--", color="#9CA3AF", label="Equal rating counts")
    ax.set(xlabel="Cumulative movie share (least rated first)", ylabel="Cumulative rating share",
           title="Lorenz curve of observed ratings", xlim=(0, 1), ylim=(0, 1))
    ax.legend()
    save(fig, "rating_concentration")

    candidates = tables["movie_candidates"].head(30)
    fig, ax = plt.subplots(figsize=(7.2, 5))
    points = ax.scatter(candidates.raw_mean, candidates.shrunk_mean, c=candidates.rating_count,
                        cmap="viridis", s=65, edgecolor="white", linewidth=.5)
    lower = min(candidates.raw_mean.min(), candidates.shrunk_mean.min()) - .03
    upper = max(candidates.raw_mean.max(), candidates.shrunk_mean.max()) + .03
    ax.plot([lower, upper], [lower, upper], "--", color="#9CA3AF")
    ax.set(xlabel="Raw mean stars", ylabel="Shrunk mean stars (m=50)",
           title="Top 30 shrunk-score candidates; at least 30 ratings")
    fig.colorbar(points, ax=ax, label="Observed rating count")
    save(fig, "candidate_shrinkage")


def _report(result, output):
    concentration = result["concentration"]
    summary = result["audit_summary"]
    complete_months = [row for row in result["monthly"] if not row["is_partial_month"]]
    peak = max(complete_months, key=lambda row: row["rating_count"])
    first = complete_months[0]
    genres = result["genre"][:5]
    lines = ["# 电影评分活动与候选片单分析", "",
             "## 结论与使用范围", "",
             f"本案例分析{summary['rating_count']:,}条已记录评分、{summary['scoring_users']}位评分用户和{summary['movie_count']:,}部电影；全样本均分为{summary['global_mean']:.5f}星。",
             f"完整月中{peak['rating_month']}的评分记录最多；评分最多的约前10%电影占{concentration['top10_rating_share']:.2%}，"
             f"≤20条评分的电影占目录{concentration['longtail_movie_share']:.2%}，却只贡献评分{concentration['longtail_rating_share']:.2%}。",
             "这些结果支持进一步核查评分活动的组成，以及建立分层的人工评审片单；不能据此预测播放量、收入、市场需求或上线推荐收益。", "",
             "## 数据与分析口径", "",
             "固定MovieLens 100K，分析范围为全部历史已记录评分；按UTC评分提交时间统计，不使用模型训练/验证/测试切分。"
             "首尾月份保守标为不完整月，月间比较使用1997-10至1998-03六个完整日历月。",
             "电影主键为movie_id，同名不同ID不合并；发行日期缺失保留NULL，unknown类型按真实标记保留，1星和5星都不作为脏数据删除。"
             "具体缺失、重复、孤儿外键与行数守恒检查见[audit.json](audit.json)。",
             "原始档案、行级表和SQLite仅留在data目录；本报告和[metrics.json](metrics.json)发布聚合结果。", "",
             "## 问题一：完整月份的评分活动怎样变化？", "",
             "“评分用户”是当月至少提交一条评分的去重用户，不是平台注册用户、平台MAU或新增用户。"
             "日均以完整月的日历天数为分母，人均以当月去重评分用户为分母。", "",
             "| 月份 | 评分记录 | 去重评分用户 | 每评分用户记录数 | 日均记录 | 有记录日/日历日 | 均分 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for row in complete_months:
        lines.append(f"| {row['rating_month']} | {row['rating_count']:,} | {row['scoring_users']} | "
                     f"{row['ratings_per_scoring_user']:.2f} | {row['day_normalized_ratings']:.2f} | "
                     f"{row['observed_day_count']}/{row['calendar_days']} | {row['rating_mean']:.3f} |")
    lines += ["",
              f"{peak['rating_month']}记录{peak['rating_count']:,}条评分、{peak['scoring_users']}位评分用户，人均{peak['ratings_per_scoring_user']:.2f}条；"
              f"作为对照，{first['rating_month']}为{first['rating_count']:,}条、{first['scoring_users']}人、人均{first['ratings_per_scoring_user']:.2f}条。"
              "评分量变化同时涉及参与评分的人数与每人的记录量，不能将人数或均分变化直接归因于内容质量、营销或用户留存。",
              "1997-12的31个日历日里只有29日出现评分记录；另2日没有被记录的评分，不能证明那两天无人观看、无人使用平台或没有其他行为。"
              "因此日均仍除以31，而不是除以29；进一步解释需要核查采集完整性及行为日志。", "",
              "![月度活动：灰色为边界不完整月](figures/monthly_activity.svg)", "",
              "## 问题二：评分活动集中在多少部电影上？", "",
              "在全部目录电影中，按评分数降序、movie_id升序处理并列；Top比例对应的电影数向上取整。"
              "这里的集中度描述评分记录，不能当作观看集中度或市场份额。", "",
              "| 分组 | 电影数 | 评分记录 | 评分占比 |", "|---|---:|---:|---:|",
              f"| 约前10%电影 | {concentration['top10_movie_count']} | {concentration['top10_rating_count']:,} | {concentration['top10_rating_share']:.2%} |",
              f"| 约前20%电影 | {concentration['top20_movie_count']} | {concentration['top20_rating_count']:,} | {concentration['top20_rating_share']:.2%} |",
              f"| ≤20条评分电影 | {concentration['longtail_movie_count']} | {concentration['longtail_rating_count']:,} | {concentration['longtail_rating_share']:.2%} |", "",
              f"长尾组占目录电影{concentration['longtail_movie_share']:.2%}。头部两行是嵌套分组，不能相加。"
              "长尾评分少可能涉及曝光、片库可用性、用户选择和采集机制，不能直接解释为没有需求。", "",
              "![评分记录的Lorenz集中度曲线](figures/rating_concentration.svg)", "",
              "## 问题三：电影类型怎样比较，才能避免多标签重复计数？", "",
              f"按真实类型标记关联后，{summary['rating_count']:,}条评分展开为{summary['rating_genre_join_rows']:,}条类型评分关联。"
              "一部电影有k个类型时，将每条评分按1/k分摊，分摊评分数可加总回100,000、分摊占比可加总为100%。"
              "这是分析归属约定，不是被观测到的观看份额。下表按分摊占比列前五类型。", "",
              "| 类型 | 涉及电影 | 普通评分数 | 分摊评分数 | 分摊占比 | 普通均分 | 分摊均分 | 等电影均分 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in genres:
        lines.append(f"| {row['genre']} | {row['movie_count']} | {row['rating_count']:,} | {row['weighted_count']:,.2f} | "
                     f"{row['weighted_share']:.2%} | {row['rating_mean']:.3f} | {row['weighted_rating_mean']:.3f} | "
                     f"{row['equal_movie_weight_mean']:.3f} |")
    lines += ["",
              "普通均分按评分记录计权，分摊均分按1/k计权；等电影均分先算每部电影的均分，再让每部电影权重相同。"
              "三种均值回答不同问题，类型间均分差异也可能来自电影和评分者组成，不能视作类型造成的偏好差异。"
              "普通类型评分数、类型涉及电影数以及去重评分用户数均会跨标签重叠，不能直接相加。", "",
              "## 问题四：怎样建立样本量较稳妥的候选片单？", "",
              f"先要求n≥30条评分，再用全局均分C={summary['global_mean']:.5f}，计算收缩分(n×原始均分+m×C)/(n+m)，主方案m=50。"
              "同样的原始均分下，评分较少的电影向C收缩更多。n≥30门槛和m=50都是透明的分析约定，不能称为已证实的最优参数。", "",
              "| 收缩排名 | 电影 | 评分数 | 原始均分 | 收缩均分 | ≥4星比例 |", "|---:|---|---:|---:|---:|---:|"]
    for row in result["movie_candidates"][:10]:
        title = row["title"].replace("|", "\\|")
        lines.append(f"| {row['shrunk_rank']} | {title} | {row['rating_count']} | {row['raw_mean']:.3f} | {row['shrunk_mean']:.3f} | {row['high_rating_ratio']:.1%} |")
    lines += ["", "![前30候选的原始均分与收缩分，颜色表示评分数](figures/candidate_shrinkage.svg)", "",
              "将m改为20、50、100，分别保留前20名，检验成员对先验强度的敏感性：", "",
              "| 两个m方案 | Top20共同电影 | 交集/并集（Jaccard） |", "|---|---:|---:|"]
    for row in result["sensitivity"]["pairwise_top20_overlap"]:
        lines.append(f"| {row['left_m']} 与 {row['right_m']} | {row['shared_movies']}/20 | {row['jaccard']:.2%} |")
    lines += ["",
              "Top20成员的重合不代表内部名次顺序相同，也不是统计显著性或排名可靠性的证明；完整名次保存在metrics.json。"
              "该片单仅作为历史样本上的人工评审候选，未证明这些电影适合某个用户，也未验证投放或推荐收益。", "",
              "## 从证据到有限建议", "",
              "| 现有证据 | 当前可以提出的有限建议 | 进一步决策需要的新数据 |", "|---|---|---|"]
    lines += [
        f"| 完整月中{peak['rating_month']}有{peak['rating_count']:,}条评分、{peak['scoring_users']}位评分用户，参与人数和人均记录量均与其他月份不同。 "
        "| 先将月度监测拆成评分人数、人均评分和日均评分，核查波动来源；不直接归因内容或营销效果。 "
        "| 采集运行与缺失日志、曝光/观看事件、用户进入评分样本的方式和活动日历；若评估活动效果，还需要对照或随机实验。 |",
        f"| 约前10%电影占评分{concentration['top10_rating_share']:.2%}；长尾占电影{concentration['longtail_movie_share']:.2%}、评分仅{concentration['longtail_rating_share']:.2%}。 "
        "| 人工评审与探索性片单保留头部/长尾分层，先设样本量和观测窗口；不按评分份额直接分配商业预算。 "
        "| 片库可用性、展示位置与曝光量、观看转化及留存、成本与权利信息；上线探索需合适的实验设计。 |",
        f"| {genres[0]['genre']}分摊占比{genres[0]['weighted_share']:.2%}；候选Top20会随m变化，且所有候选均满足n≥30。 "
        "| 将类型分摊结果作为样本描述，将收缩片单作为人工复核起点，并保留敏感性结果；不把m=50当最优，也不将片单当个体推荐。 "
        "| 更新时期的评分与评分质量审查、实际可用片库、曝光和观看数据、目标用户需求，以及预先固定指标的试验结果。 |",
        "", "## 限制与复现", "",
        "用户和评分记录都存在选择偏差；1997–1998年的历史样本不能代表今天所有观众。没有曝光、观看或随机分配数据，描述性差异不能证明因果。"
        "先验强度敏感性也不涵盖抽样误差、异常评分机制或时期变化。",
        "从项目目录运行`python -m rating_lab.analyst`可重建本报告；SQL位于[analysis.sql](../../sql/analysis.sql)。"
        "完整聚合表见[metrics.json](metrics.json)，源数据审计见[audit.json](audit.json)。",
        f"固定原包SHA-256：`{result['source_sha256']}`。代码许可不覆盖MovieLens源数据，发布内容保持为聚合结果。",
        "后续按[学习指南](../../docs/LEARNING_GUIDE.md)复核口径、执行SQL并写出自己的结论。", "",
    ]
    (output / "ANALYSIS_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run_analysis(data_dir=None, output_dir=None):
    """Run the SQL case and write aggregate-only JSON, figures and a short report."""
    database, audit = prepare_database(data_dir)
    output = Path(output_dir or PROJECT_ROOT / "reports" / "analyst")
    output.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        tables = {name: pd.read_sql_query(query, connection) for name, query in load_queries().items()}
        assert set(tables) == {"monthly", "concentration", "movie_candidates", "genre", "sensitivity"}
        assert np.isclose(tables["genre"].weighted_count.sum(), connection.execute("SELECT COUNT(*) FROM ratings").fetchone()[0])
        assert np.isclose(tables["genre"].weighted_share.sum(), 1.0)
        sensitive = tables["sensitivity"]
        sets = {int(value): set(rows.movie_id) for value, rows in sensitive.groupby("prior_strength")}
        pairwise = [{"left_m": left, "right_m": right, "shared_movies": len(sets[left] & sets[right]),
                     "jaccard": len(sets[left] & sets[right]) / len(sets[left] | sets[right])}
                    for left, right in itertools.combinations(sorted(sets), 2)]
        result = {
            "dataset": "MovieLens 100K", "source_sha256": SOURCE_SHA256,
            "audit_summary": {"rating_count": audit["ratings"]["rows"], "movie_count": audit["movies"]["rows"],
                              "scoring_users": audit["ratings"]["unique_users"], "global_mean": audit["ratings"]["global_mean"],
                              "candidate_movies_n_ge_30": len(tables["movie_candidates"]),
                              "rating_genre_join_rows": audit["preservation"]["rating_genre_join_rows"]},
            "monthly": _records(tables["monthly"]),
            "concentration": _records(tables["concentration"])[0],
            "movie_candidates": _records(tables["movie_candidates"].head(30)),
            "genre": _records(tables["genre"]),
            "sensitivity": {"top20_rankings": _records(sensitive), "pairwise_top20_overlap": pairwise},
            "definitions": {
                "scope": "全部100000条历史已记录评分；不使用建模的train/validation/test分区。",
                "monthly": "UTC评分提交月；首尾月保守标partial；日均只用于完整月；人均分母是月去重评分用户。",
                "concentration": "全1682部目录电影按评分数降序、movie_id升序，Top10/20%部数向上取整；长尾为≤20条评分。",
                "candidates": "n≥30，C=全样本评分均值，收缩分=(n*raw_mean+m*C)/(n+m)；主表m=50，敏感性20/50/100；不声称最优。",
                "genre": "普通计数跨标签重复；weighted_count为每条评分按真实类型数k分摊1/k；等电影均分先算电影均分再按电影等权；独立用户不可跨类型加总。",
            },
            "limitations": ["评分为选择性提交而非曝光/观看样本；不能将评分活动当作播放量或市场份额。",
                            "1997–1998历史样本，用户筛选和记录方式限制外推。",
                            "月均分、类型均分、电影片单都是描述性结果，不能证明因果或线上提升。"],
        }
        _figures(connection, tables, output)
    (output / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _report(result, output)
    print(f"Report: {output / 'ANALYSIS_REPORT.md'}")
    print(f"Database (local only): {database}")
    return result


def main():
    parser = argparse.ArgumentParser(description="SQL-first MovieLens analyst case")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    run_analysis(args.data_dir, args.output_dir)


if __name__ == "__main__":
    main()
