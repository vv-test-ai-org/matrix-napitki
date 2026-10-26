#!/usr/bin/env python3
"""Выгрузка четырёх источников Superset (1С, канал, хвост, карточки) в data/*.csv через REST API SQL Lab.

Креды — только из окружения или файла .env рядом со скриптом (см. .env.example):
  SUPERSET_URL, SUPERSET_USER, SUPERSET_PASSWORD, SUPERSET_PROVIDER (db | ldap)
Запуск: python3 fetch_superset.py            # все четыре
        python3 fetch_superset.py har_kontr  # один
SQL-тексты лежат в sql/*.sql (в репозиторий не попадают — там внутренние имена таблиц).
"""
import csv, json, os, sys, time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
DATA = HERE / 'data'
SQL = HERE / 'sql'
env = HERE / '.env'
if env.exists():
    for line in env.read_text().splitlines():
        if '=' in line and not line.strip().startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

# имя файла → (database_id в Superset, sql-файл, порядок колонок в CSV)
SOURCES = {
    'har_kontr':  (11, 'har_kontr.sql',  ['sku_id', 'sku_name', 'subgroup', 'is_alc', 'supplier', 'status_1c', 'activity_status', 'stop_dt', 'reason_code', 'comment_1c']),
    'channel_ch': (92, 'channel_ch.sql', ['sku_id', 'nm', 'grp', 'ds_asrt', 'ws_asrt', 'ds_qty', 'ws_qty', 'channel']),
    'sales_tail': (92, 'sales_tail.sql', ['sku_id', 'avg_qty_3m', 'avg_qty_12m', 'stock_last']),
    'sku_cards':  (76, 'sku_cards.sql',  ['sku_id', 'sku_name', 'sku_category_name', 'sku_group_name', 'card_created_dt', 'first_supply_min_dt', 'first_sale_dttm']),
}


class Superset:
    def __init__(self):
        for k in ('SUPERSET_URL', 'SUPERSET_USER', 'SUPERSET_PASSWORD'):
            if not os.environ.get(k):
                sys.exit(f'нет {k}: заполните .env (см. .env.example)')
        self.base = os.environ['SUPERSET_URL'].rstrip('/') + '/api/v1'
        self.s = requests.Session()
        r = self.s.post(f'{self.base}/security/login', json={
            'username': os.environ['SUPERSET_USER'], 'password': os.environ['SUPERSET_PASSWORD'],
            'provider': os.environ.get('SUPERSET_PROVIDER', 'db'), 'refresh': True}, timeout=60)
        r.raise_for_status()
        self.s.headers['Authorization'] = 'Bearer ' + r.json()['access_token']
        csrf = self.s.get(f'{self.base}/security/csrf_token/', timeout=60)
        if csrf.ok:
            self.s.headers['X-CSRFToken'] = csrf.json()['result']
            self.s.headers['Referer'] = os.environ['SUPERSET_URL']

    def sql(self, database_id, sql, limit=20000, tries=60, pause=5):
        body = {'database_id': database_id, 'sql': sql, 'runAsync': False, 'queryLimit': limit,
                'client_id': f'matrix{int(time.time()*1000) % 10**8:08d}'}
        r = self.s.post(f'{self.base}/sqllab/execute/', json=body, timeout=600)
        if r.status_code not in (200, 202):
            raise RuntimeError(f'SQL Lab {r.status_code}: {r.text[:300]}')
        j = r.json()
        if j.get('status') == 'success' and 'data' in j:
            return [c['name'] for c in j['columns']], j['data']
        qid = j.get('query_id') or j.get('query', {}).get('id')
        for _ in range(tries):   # асинхронный режим: ждём и забираем результат
            time.sleep(pause)
            q = self.s.get(f'{self.base}/query/{qid}', timeout=60).json()['result']
            if q['status'] == 'success':
                res = self.s.get(f'{self.base}/sqllab/results/', params={'key': q['results_key']}, timeout=600).json()
                return [c['name'] for c in res['columns']], res['data']
            if q['status'] in ('failed', 'stopped'):
                raise RuntimeError(f'запрос {qid}: {q.get("error_message") or q["status"]}')
        raise TimeoutError(f'запрос {qid} не завершился')


def main():
    names = [a for a in sys.argv[1:] if a in SOURCES] or list(SOURCES)
    ss = Superset()
    for nm in names:
        dbid, sqlfile, cols = SOURCES[nm]
        sql = (SQL / sqlfile).read_text(encoding='utf-8')
        t0 = time.time()
        columns, data = ss.sql(dbid, sql)
        out = DATA / f'{nm}.csv'
        with open(out, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f); w.writerow(cols)
            for row in data:
                w.writerow(['' if row.get(c) is None else row.get(c, '') for c in cols])
        print(f'{nm}: {len(data)} строк → {out.name} ({time.time()-t0:.0f} с)')
    (DATA / 'superset_fetched.json').write_text(json.dumps({'date': time.strftime('%Y-%m-%d'), 'sources': names}, ensure_ascii=False))


if __name__ == '__main__':
    main()
