-- 一天的活跃时段分布
select hour(datetime) as hour,
       sum(case when behavior_type = 'pv' then 1 else 0 end) as pv,   --点击数
       sum(case when behavior_type = 'fav' then 1 else 0 end) as fav,  --收藏数
       sum(case when behavior_type = 'cart' then 1 else 0 end) as cart,  --加购物车数
       sum(case when behavior_type = 'buy' then 1 else 0 end) as buy  --购买数
from taobao.user_behavior
group by hour(datetime)
order by hour;

--一周用户的活跃分布
select pmod(datediff(datetime, '1920-01-01') - 3, 7) as weekday,
       sum(case when behavior_type = 'pv' then 1 else 0 end) as pv,   --点击数
       sum(case when behavior_type = 'fav' then 1 else 0 end) as fav,  --收藏数
       sum(case when behavior_type = 'cart' then 1 else 0 end) as cart,  --加购物车数
       sum(case when behavior_type = 'buy' then 1 else 0 end) as buy  --购买数
from taobao.user_behavior
where date(datetime) between '2017-11-27' and '2017-12-03'
group by pmod(datediff(datetime, '1920-01-01') - 3, 7)
order by weekday;

--销量最高的商品
select item_id ,
       sum(case when behavior_type = 'pv' then 1 else 0 end) as pv,   --点击数
       sum(case when behavior_type = 'fav' then 1 else 0 end) as fav,  --收藏数
       sum(case when behavior_type = 'cart' then 1 else 0 end) as cart,  --加购物车数
       sum(case when behavior_type = 'buy' then 1 else 0 end) as buy  --购买数
from taobao.user_behavior
group by item_id
order by buy desc
limit 10;

--销量最高的商品大类
select category_id ,
       sum(case when behavior_type = 'pv' then 1 else 0 end) as pv,   --点击数
       sum(case when behavior_type = 'fav' then 1 else 0 end) as fav,  --收藏数
       sum(case when behavior_type = 'cart' then 1 else 0 end) as cart,  --加购物车数
       sum(case when behavior_type = 'buy' then 1 else 0 end) as buy  --购买数
from taobao.user_behavior
group by category_id
order by buy desc
limit 10;

select user_id,
       datediff('2017-12-04',max(datetime))as R,
       dense_rank()over(order by datediff('2017-12-04',max(datetime)))as R_rank
from taobao.user_behavior
where behavior_type='buy'
group by user_id 
LIMIT 10;

select user_id,
       count(1) as F,
       dense_rank() over(order by count(1) desc) as F_rank
from taobao.user_behavior
where behavior_type = 'buy'
group by user_id
limit 10;

with cte as(
select user_id,
       datediff('2017-12-04', max(datetime)) as R,
       dense_rank() over(order by datediff('2017-12-04', max(datetime))) as R_rank,
       count(1) as F,
       dense_rank() over(order by count(1) desc) as F_rank
from taobao.user_behavior
where behavior_type = 'buy'
group by user_id)

select user_id, R, R_rank, R_score, F, F_rank, F_score,  R_score + F_score AS score
from(
select *,
       case ntile(5) over(order by R_rank) when 1 then 5
                                           when 2 then 4
                                           when 3 then 3
                                           when 4 then 2
                                           when 5 then 1
       end as R_score,
       case ntile(5) over(order by F_rank) when 1 then 5
                                           when 2 then 4
                                           when 3 then 3
                                           when 4 then 2
                                           when 5 then 1
       end as F_score
from cte
) as a
order by score desc
limit 20;