-- MovieLens 100K: observed rating activity, never viewing or sales activity.
-- name: monthly
WITH bounds AS (
    SELECT MIN(rating_month) AS first_month, MAX(rating_month) AS last_month FROM ratings
), monthly AS (
    SELECT rating_month, COUNT(*) AS rating_count,
           COUNT(DISTINCT user_id) AS scoring_users,
           COUNT(DISTINCT movie_id) AS rated_movies,
           AVG(rating) AS rating_mean,
           COUNT(DISTINCT substr(rated_at_utc, 1, 10)) AS observed_day_count
    FROM ratings GROUP BY rating_month
), calendar AS (
    SELECT monthly.*,
           CAST(julianday(date(rating_month || '-01', '+1 month'))
                - julianday(rating_month || '-01') AS INTEGER) AS calendar_days,
           CASE WHEN rating_month IN (first_month, last_month) THEN 1 ELSE 0 END AS is_partial_month
    FROM monthly CROSS JOIN bounds
)
SELECT rating_month, rating_count, scoring_users, rated_movies, rating_mean,
       calendar_days, observed_day_count, is_partial_month,
       CASE WHEN is_partial_month = 0 THEN 1.0 * rating_count / calendar_days END AS day_normalized_ratings,
       1.0 * rating_count / scoring_users AS ratings_per_scoring_user
FROM calendar ORDER BY rating_month;

-- name: concentration
WITH counts AS (
    SELECT m.movie_id, COUNT(r.movie_id) AS n
    FROM movies m LEFT JOIN ratings r ON r.movie_id = m.movie_id GROUP BY m.movie_id
), ranked AS (
    SELECT movie_id, n, ROW_NUMBER() OVER (ORDER BY n DESC, movie_id) AS count_rank FROM counts
), totals AS (
    SELECT COUNT(*) AS movie_count, SUM(n) AS rating_count,
           CAST((COUNT(*) + 9) / 10 AS INTEGER) AS top10_movie_count,
           CAST((COUNT(*) + 4) / 5 AS INTEGER) AS top20_movie_count FROM counts
)
SELECT movie_count, rating_count, top10_movie_count,
       SUM(CASE WHEN count_rank <= top10_movie_count THEN n ELSE 0 END) AS top10_rating_count,
       1.0 * SUM(CASE WHEN count_rank <= top10_movie_count THEN n ELSE 0 END) / rating_count AS top10_rating_share,
       top20_movie_count,
       SUM(CASE WHEN count_rank <= top20_movie_count THEN n ELSE 0 END) AS top20_rating_count,
       1.0 * SUM(CASE WHEN count_rank <= top20_movie_count THEN n ELSE 0 END) / rating_count AS top20_rating_share,
       SUM(CASE WHEN n <= 20 THEN 1 ELSE 0 END) AS longtail_movie_count,
       1.0 * SUM(CASE WHEN n <= 20 THEN 1 ELSE 0 END) / movie_count AS longtail_movie_share,
       SUM(CASE WHEN n <= 20 THEN n ELSE 0 END) AS longtail_rating_count,
       1.0 * SUM(CASE WHEN n <= 20 THEN n ELSE 0 END) / rating_count AS longtail_rating_share
FROM ranked CROSS JOIN totals GROUP BY movie_count, rating_count, top10_movie_count, top20_movie_count;

-- name: movie_candidates
WITH movie_stats AS (
    SELECT movie_id, COUNT(*) AS rating_count, AVG(rating) AS raw_mean,
           AVG(CASE WHEN rating >= 4 THEN 1.0 ELSE 0.0 END) AS high_rating_ratio
    FROM ratings GROUP BY movie_id HAVING COUNT(*) >= 30
), scored AS (
    SELECT movie_stats.*, movies.title, (SELECT AVG(rating) FROM ratings) AS global_mean,
           50.0 AS prior_strength,
           (rating_count * raw_mean + 50.0 * (SELECT AVG(rating) FROM ratings)) / (rating_count + 50.0) AS shrunk_mean
    FROM movie_stats JOIN movies USING (movie_id)
)
SELECT movie_id, title, rating_count, raw_mean, high_rating_ratio, global_mean,
       prior_strength, shrunk_mean,
       ROW_NUMBER() OVER (ORDER BY rating_count DESC, movie_id) AS rating_count_rank,
       ROW_NUMBER() OVER (ORDER BY raw_mean DESC, rating_count DESC, movie_id) AS raw_mean_rank,
       ROW_NUMBER() OVER (ORDER BY shrunk_mean DESC, rating_count DESC, movie_id) AS shrunk_rank
FROM scored ORDER BY shrunk_rank;

-- name: genre
WITH multiplicity AS (
    SELECT movie_id, COUNT(*) AS n_genres FROM movie_genres GROUP BY movie_id
), movie_stats AS (
    SELECT movie_id, AVG(rating) AS movie_mean FROM ratings GROUP BY movie_id
), equal_movie AS (
    SELECT mg.genre_id, AVG(ms.movie_mean) AS equal_movie_weight_mean
    FROM movie_genres mg JOIN movie_stats ms USING (movie_id) GROUP BY mg.genre_id
), by_genre AS (
    SELECT mg.genre_id, mg.genre, COUNT(DISTINCT mg.movie_id) AS movie_count,
           COUNT(DISTINCT r.user_id) AS scoring_users, COUNT(*) AS rating_count,
           AVG(r.rating) AS rating_mean,
           AVG(CASE WHEN r.rating >= 4 THEN 1.0 ELSE 0.0 END) AS high_rating_ratio,
           SUM(1.0 / multiplicity.n_genres) AS weighted_count,
           SUM(1.0 * r.rating / multiplicity.n_genres) / SUM(1.0 / multiplicity.n_genres) AS weighted_rating_mean,
           SUM(1.0 / multiplicity.n_genres) / (SELECT COUNT(*) FROM ratings) AS weighted_share
    FROM ratings r JOIN movie_genres mg USING (movie_id) JOIN multiplicity USING (movie_id)
    GROUP BY mg.genre_id, mg.genre
)
SELECT by_genre.*, equal_movie.equal_movie_weight_mean
FROM by_genre JOIN equal_movie USING (genre_id) ORDER BY weighted_count DESC, genre_id;

-- name: sensitivity
WITH movie_stats AS (
    SELECT movie_id, COUNT(*) AS rating_count, AVG(rating) AS raw_mean
    FROM ratings GROUP BY movie_id HAVING COUNT(*) >= 30
), strengths(prior_strength) AS (VALUES (20.0), (50.0), (100.0)), scored AS (
    SELECT movie_stats.*, movies.title, prior_strength,
           (rating_count * raw_mean + prior_strength * (SELECT AVG(rating) FROM ratings))
           / (rating_count + prior_strength) AS shrunk_mean
    FROM movie_stats JOIN movies USING (movie_id) CROSS JOIN strengths
), ranked AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY prior_strength ORDER BY shrunk_mean DESC, rating_count DESC, movie_id
    ) AS shrunk_rank FROM scored
)
SELECT prior_strength, movie_id, title, rating_count, raw_mean, shrunk_mean, shrunk_rank
FROM ranked WHERE shrunk_rank <= 20 ORDER BY prior_strength, shrunk_rank;
