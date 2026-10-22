CREATE DATABASE IF NOT EXISTS taobao;
CREATE TABLE IF NOT EXISTS taobao.user_behavior (
`user_id` string comment '用户ID',
`item_id` string comment '商品ID',
`category_id` string comment '商品类目ID',
`behavior_type` string  comment '行为类型，枚举类型，包括(pv, buy, cart, fav)',
`timestamp` int comment '行为时间戳',
`datetime` string comment '行为时间')
row format delimited
fields terminated by','
lines terminated by '\n';

--加载
LOAD DATA LOCAL INPATH '/mnt/taobao/UserBehavior.csv'
OVERWRITE INTO TABLE taobao.user_behavior;

SELECT *
FROM taobao.user_behavior
LIMIT 10;