"""Read-only dashboard: snapshot HTML export or live Kafka result display."""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from project import names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', default='reports/result.json')
    parser.add_argument('--export', help='Export standalone HTML instead of starting a server')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--run')
    parser.add_argument('--bootstrap', default='192.168.121.134:9092')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    template = Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8')
    report = json.loads(Path(args.report).read_text(encoding='utf-8')) if Path(args.report).exists() else {}
    if args.export:
        content = template.replace('/*REPORT*/null', json.dumps(report, ensure_ascii=False).replace('<', '\\u003c'))
        Path(args.export).parent.mkdir(parents=True, exist_ok=True)
        Path(args.export).write_text(content, encoding='utf-8')
        return
    state = dict(report)
    lock = threading.Lock()
    if args.live:
        if not args.run:
            parser.error('--live requires --run')
        state = dict(run=args.run, source='Kafka result topics (live, not reconciled)',
                     actual=dict(overall={},windows={},hours={},categories={},cumulative={}), passed=None)

        def watch():
            from kafka import KafkaConsumer
            topics = names(args.run)
            mapping = {topics[k]: k for k in ('overall','windows','hours','categories','cumulative')}
            fields = dict(overall='metric_key',windows='window_start',hours='hour_start',categories='category_id',cumulative='window_end')
            try:
                consumer = KafkaConsumer(*mapping, bootstrap_servers=args.bootstrap,
                                         auto_offset_reset='earliest', enable_auto_commit=False,
                                         value_deserializer=lambda b: json.loads(b) if b else None,
                                         key_deserializer=lambda b: json.loads(b) if b else None)
                try:
                    for msg in consumer:
                        kind = mapping[msg.topic]
                        key = str(msg.key[fields[kind]])
                        with lock:
                            target = state['actual']
                            if kind == 'overall':
                                target['overall'] = msg.value or {}
                            elif msg.value is None:
                                target[kind].pop(key, None)
                            else:
                                target[kind][key] = msg.value if kind == 'windows' else msg.value['uv' if kind == 'cumulative' else 'buy_events']
                            state['last_update'] = time.strftime('%Y-%m-%d %H:%M:%S')
                finally:
                    consumer.close()
            except Exception as exc:
                with lock:
                    state['error'] = str(exc)
        threading.Thread(target=watch, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/api':
                with lock:
                    content = json.dumps(state, ensure_ascii=False).encode('utf-8')
                kind='application/json; charset=utf-8'
            elif self.path in ('/', '/index.html'):
                content=template.encode('utf-8'); kind='text/html; charset=utf-8'
            else:
                self.send_error(404); return
            self.send_response(200)
            self.send_header('Content-Type',kind)
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(content)))
            self.end_headers(); self.wfile.write(content)
        def log_message(self, *args):
            pass
    print(f'http://{args.host}:{args.port}',flush=True)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()


if __name__ == '__main__':
    main()
