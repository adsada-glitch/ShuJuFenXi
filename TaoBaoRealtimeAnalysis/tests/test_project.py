import argparse
import json
import tempfile
import unittest
from pathlib import Path
import project


class PipelineTests(unittest.TestCase):
    def test_china_midnight_and_window_boundary(self):
        events = [project.parse_row(['1','2','3','pv','1511539199']),
                  project.parse_row(['1','2','3','buy','1511539200'])]
        result = project.reference(events)
        self.assertIn('2017-11-24 23:55:00', result['windows'])
        self.assertIn('2017-11-25 00:00:00', result['windows'])
        self.assertEqual(result['overall']['active_users'],1)
        self.assertEqual(result['overall']['buyers'],1)

    def test_repeated_events_kept_but_users_distinct(self):
        e=project.parse_row(['1','2','3','buy','1511544070'])
        result=project.aggregate([e,e])
        self.assertEqual(result['buy_events'],2)
        self.assertEqual(result['buyers'],1)

    def test_invalid_rows(self):
        for row in (['1'],['1','2','3','bad','1'],['1','2','3','pv','-1']):
            with self.assertRaises(ValueError): project.parse_row(row)

    def test_prepare_counts_bad_dates_and_sorts(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'input.csv'
            src.write_text('1,2,3,buy,1511544070\n1,2,3,pv,1511539200\n1,2,3,pv,1\nbad\n',encoding='utf-8')
            project.prepare(argparse.Namespace(csv=str(src),limit=4,out=d))
            m=json.loads((Path(d)/'manifest.json').read_text())
            self.assertEqual((m['accepted_rows'],m['invalid_rows'],m['out_of_range_rows']),(2,1,1))
            e=[json.loads(x) for x in (Path(d)/'events.jsonl').read_text().splitlines()]
            self.assertLess(e[0]['ts'],e[1]['ts'])

    def test_cumulative_resets_daily_and_excludes_end_boundary(self):
        events = [dict(user_id=u,item_id=1,category_id=1,behavior='pv',ts=t)
                  for u,t in [(1,1511539200),(2,1511539800),(3,1511625600)]]
        c = project.reference(events)['cumulative']
        self.assertEqual(c['2017-11-25 00:10:00'],1)
        self.assertEqual(c['2017-11-25 00:20:00'],2)
        self.assertEqual(c['2017-11-26 00:00:00'],2)
        self.assertEqual(c['2017-11-26 00:10:00'],1)

    def test_run_rejects_sql_injection(self):
        with self.assertRaises(ValueError): project.names("x'; DROP TABLE events;")


if __name__=='__main__': unittest.main()
