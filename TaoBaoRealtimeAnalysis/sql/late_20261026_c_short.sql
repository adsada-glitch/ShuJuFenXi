SET 'parallelism.default' = '1';
SET 'table.local-time-zone' = 'Asia/Shanghai';
CREATE TABLE events (user_id BIGINT,item_id BIGINT,category_id BIGINT,behavior STRING,ts BIGINT, event_time AS TO_TIMESTAMP_LTZ(ts,0), WATERMARK FOR event_time AS event_time - INTERVAL '00:00:05' HOUR TO SECOND) WITH ('connector'='kafka','topic'='late_20261026_c_short_events','properties.bootstrap.servers'='192.168.121.134:9092','properties.group.id'='late_20261026_c_short_flink','scan.startup.mode'='earliest-offset','scan.bounded.mode'='specific-offsets','scan.bounded.specific-offsets'='partition:0,offset:4','format'='json');
CREATE TABLE overall (metric_key STRING,total_events BIGINT, active_users BIGINT, pv BIGINT, fav BIGINT, cart BIGINT, buy_events BIGINT, buyers BIGINT, PRIMARY KEY (metric_key) NOT ENFORCED) WITH (
'connector'='upsert-kafka','topic'='late_20261026_c_short_overall','properties.bootstrap.servers'='192.168.121.134:9092','key.format'='json','value.format'='json');
CREATE TABLE windows (window_start STRING,total_events BIGINT, active_users BIGINT, pv BIGINT, fav BIGINT, cart BIGINT, buy_events BIGINT, buyers BIGINT, PRIMARY KEY (window_start) NOT ENFORCED) WITH (
'connector'='upsert-kafka','topic'='late_20261026_c_short_windows','properties.bootstrap.servers'='192.168.121.134:9092','key.format'='json','value.format'='json');
CREATE TABLE hours (hour_start STRING, buy_events BIGINT, PRIMARY KEY (hour_start) NOT ENFORCED) WITH (
'connector'='upsert-kafka','topic'='late_20261026_c_short_hours','properties.bootstrap.servers'='192.168.121.134:9092','key.format'='json','value.format'='json');
CREATE TABLE categories (category_id BIGINT, buy_events BIGINT, PRIMARY KEY (category_id) NOT ENFORCED) WITH (
'connector'='upsert-kafka','topic'='late_20261026_c_short_categories','properties.bootstrap.servers'='192.168.121.134:9092','key.format'='json','value.format'='json');
CREATE TABLE cumulative (window_end STRING, uv BIGINT, PRIMARY KEY (window_end) NOT ENFORCED) WITH (
'connector'='upsert-kafka','topic'='late_20261026_c_short_cumulative','properties.bootstrap.servers'='192.168.121.134:9092','key.format'='json','value.format'='json');
EXECUTE STATEMENT SET BEGIN
INSERT INTO overall SELECT 'all',COUNT(*), COUNT(DISTINCT user_id), SUM(CASE WHEN behavior='pv' THEN 1 ELSE 0 END), SUM(CASE WHEN behavior='fav' THEN 1 ELSE 0 END), SUM(CASE WHEN behavior='cart' THEN 1 ELSE 0 END), SUM(CASE WHEN behavior='buy' THEN 1 ELSE 0 END), COUNT(DISTINCT CASE WHEN behavior='buy' THEN user_id END) FROM events;
INSERT INTO windows SELECT DATE_FORMAT(window_start,'yyyy-MM-dd HH:mm:ss'),COUNT(*), COUNT(DISTINCT user_id), SUM(CASE WHEN behavior='pv' THEN 1 ELSE 0 END), SUM(CASE WHEN behavior='fav' THEN 1 ELSE 0 END), SUM(CASE WHEN behavior='cart' THEN 1 ELSE 0 END), SUM(CASE WHEN behavior='buy' THEN 1 ELSE 0 END), COUNT(DISTINCT CASE WHEN behavior='buy' THEN user_id END) FROM TABLE(TUMBLE(TABLE events,DESCRIPTOR(event_time),INTERVAL '5' MINUTE)) GROUP BY window_start,window_end;
INSERT INTO hours SELECT DATE_FORMAT(window_start,'yyyy-MM-dd HH:mm:ss'),COUNT(*) FROM TABLE(TUMBLE(TABLE events,DESCRIPTOR(event_time),INTERVAL '1' HOUR)) WHERE behavior='buy' GROUP BY window_start,window_end;
INSERT INTO categories SELECT category_id,COUNT(*) FROM events WHERE behavior='buy' GROUP BY category_id;
INSERT INTO cumulative SELECT DATE_FORMAT(window_end,'yyyy-MM-dd HH:mm:ss'),COUNT(DISTINCT user_id) FROM TABLE(CUMULATE(TABLE events,DESCRIPTOR(event_time),INTERVAL '10' MINUTE,INTERVAL '1' DAY)) GROUP BY window_start,window_end;
END;
