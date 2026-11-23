"""Repeatable local end-to-end verification without Docker.

Starts the actual three service processes with isolated temporary SQLite databases,
places one order, verifies idempotency, waits for Notification consumption and broker
acknowledgement, and checks correlated JSON logs. The resulting evidence is genuine
LOCAL evidence, never represented as a Docker/hosted GitHub run.
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def available_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def json_request(url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode('utf-8')
    req = Request(url, data=data, headers=headers or {}, method='POST' if body is not None else 'GET')
    with urlopen(req, timeout=3) as res:
        return res.status, json.loads(res.read())


def wait_for(f, seconds=15):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        try:
            result = f()
            if result:
                return result
        except Exception:
            pass
        time.sleep(0.15)
    raise TimeoutError('Verification condition not met in time')


def count(db_path, query):
    with sqlite3.connect(db_path) as db:
        return db.execute(query).fetchone()[0]


def main():
    ports = {name: available_port() for name in ('broker', 'order', 'notification')}
    correlation = 'verifiable-local-' + str(uuid4())[:8]
    procs, files = [], []
    with tempfile.TemporaryDirectory(prefix='maltashop-e2e-') as tempdir:
        temp = Path(tempdir)
        try:
            for name in ('broker', 'order', 'notification'):
                env = dict(os.environ)
                env['DB_PATH'] = str(temp / f'{name}.db')
                if name != 'broker':
                    env['BROKER_URL'] = f'http://127.0.0.1:{ports["broker"]}'
                log = open(temp / f'{name}.log', 'w+', encoding='utf-8')
                files.append(log)
                proc = subprocess.Popen([
                    sys.executable, '-m', 'uvicorn', f'{name}.app:app',
                    '--host', '127.0.0.1', '--port', str(ports[name])
                ], cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
                procs.append(proc)
                wait_for(lambda: json_request(f'http://127.0.0.1:{ports[name]}/healthz')[0] == 200)

            body = {'customer_ref': 'synthetic-test-only', 'items': [{'sku': 'TV-02', 'quantity': 1}]}
            headers = {'Content-Type':'application/json', 'Idempotency-Key': 'local-test-' + str(uuid4()), 'X-Correlation-ID':correlation}
            endpoint = f'http://127.0.0.1:{ports["order"]}/orders'
            status, first = json_request(endpoint, body, headers)
            replay_status, replay = json_request(endpoint, body, headers)
            assert status == replay_status == 202
            assert first['status'] == 'ACCEPTED' and not first['replayed']
            assert replay['replayed'] and replay['order_id'] == first['order_id']

            wait_for(lambda: count(temp/'notification.db', 'SELECT COUNT(*) FROM inbox') == 1 and
                     count(temp/'broker.db', "SELECT COUNT(*) FROM messages WHERE state='acked'") == 1)
            wait_for(lambda: 'event_consumed' in (temp/'notification.log').read_text())
            order_log = (temp/'order.log').read_text()
            notification_log = (temp/'notification.log').read_text()
            assert 'order_accepted' in order_log and correlation in order_log
            assert 'event_consumed' in notification_log and correlation in notification_log

            payload = {
                'result': 'PASS', 'environment': 'local Python processes (not Docker; not hosted GitHub)',
                'order_response_status': status, 'order_response': first,
                'idempotent_replay_confirmed': replay['replayed'],
                'broker_messages_acked': count(temp/'broker.db', "SELECT COUNT(*) FROM messages WHERE state='acked'"),
                'notification_inbox_events': count(temp/'notification.db','SELECT COUNT(*) FROM inbox'),
                'same_correlation_id_in_order_and_notification_logs': True,
                'correlation_id': correlation
            }
            out = ROOT / 'evidence' / 'reverified-local-e2e.json'
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
            for name in ('order', 'notification', 'broker'):
                (ROOT/'evidence'/f'reverified-{name}.log').write_text(
                    (temp/f'{name}.log').read_text(), encoding='utf-8'
                )
            print(json.dumps(payload, indent=2))
        finally:
            for proc in procs:
                proc.terminate()
            for proc in procs:
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
            for log in files:
                log.close()


if __name__ == '__main__':
    main()
