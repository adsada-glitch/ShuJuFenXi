--总访问量PV，总用户量UV
select sum(case when behavior_type = 'pv' then 1 else 0 end) as pv,
       count(distinct user_id) as uv
from taobao.user_behavior;

SELECT cast(datetime as date)as day,
       sum(case when behavior_type ='pv' then 1 else 0 end)as pv,
       count(distinct user_id)as uv
from taobao.user_behavior
group by cast(datetime as date)
order by day;

--每个用户的购物情况，加工到 user_behavior_count
create table taobao.user_behavior_count as
select user_id,
       sum(case when behavior_type = 'pv' then 1 else 0 end) as pv,   --点击数
       sum(case when behavior_type = 'fav' then 1 else 0 end) as fav,  --收藏数
       sum(case when behavior_type = 'cart' then 1 else 0 end) as cart,  --加购物车数
       sum(case when behavior_type = 'buy' then 1 else 0 end) as buy  --购买数
from taobao.user_behavior
group by user_id;

--复购率：产生两次或两次以上购买的用户占购买用户的比例
select sum(case when buy>1 then 1 else 0 end) / sum(case when buy > 0 then 1 else 0 end)
from taobao.user_behavior_count;