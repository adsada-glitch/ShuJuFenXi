-- 1. 去掉完全重复的数据
INSERT OVERWRITE TABLE taobao.user_behavior
SELECT user_id, item_id, category_id, behavior_type,
       `timestamp`, `datetime`
FROM taobao.user_behavior
GROUP BY user_id, item_id, category_id, behavior_type,
         `timestamp`, `datetime`;
--数据清洗，时间戳格式化成 datetime
INSERT OVERWRITE TABLE taobao.user_behavior
select user_id, item_id, category_id, behavior_type,
       `timestamp`,from_unixtime(`timestamp`,'yyyy-MM-dd HH:mm:ss')
       from taobao.user_behavior;
select date(datetime) as day from taobao.user_behavior group by date(datetime)order by day;

--数据清洗，去掉时间异常的数据
insert overwrite table taobao.user_behavior
select user_id, item_id, category_id, behavior_type, `timestamp`, datetime
from taobao.user_behavior
where cast(datetime as date) between '2017-11-25' and '2017-12-03';

--查看 behavior_type 是否有异常值
select behavior_type from taobao.user_behavior group by behavior_type;

SELECT
    from_unixtime(`timestamp`, 'yyyy-MM-dd') AS actual_day,
    COUNT(*) AS total_rows
FROM taobao.user_behavior
GROUP BY from_unixtime(`timestamp`, 'yyyy-MM-dd')
ORDER BY actual_day;