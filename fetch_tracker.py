#!/usr/bin/env python3
"""Выгрузка трекера вывода SKUWITHDRAW в data/withdraw.csv через CLI ya-tracker.

Запуск:  python3 fetch_tracker.py            # все задачи очереди → data/withdraw.csv (+ сырой JSON)
         python3 fetch_tracker.py --from-json data/skuwithdraw_raw.json   # без обращения к API

Следом выгружается трекер новинок NEWPRODUCT, доска 4306 «Путь Напитки» → data/new.csv (доступ выдан 23.10.2026).
"""
import csv, json, os, re, subprocess, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
RAW = os.path.join(DATA, 'skuwithdraw_raw.json')
OUT = os.path.join(DATA, 'withdraw.csv')
P = '6a68974352d91521d25f3d47--'   # префикс локальных полей очереди SKUWITHDRAW

# статус в API → статус в интерфейсе доски «Вывод товаров из ассортимента; Путь Напитки»
STATUS_UI = {
    'backlog': 'Беклог',
    'open': 'На вывод',
    'vRaboteUTehnologa': 'В работе у технолога',
    'naSoglasovanii': 'На согласовании',
    'notagreed': 'Не согласовано технологом',
    'received': 'Получен ответ от поставщика',
    'onpause': 'Планируется возвращение в сезон',
    'closed': 'Закрыт',
}

COLS = ['key', 'status_key', 'status', 'board', 'sku_id', 'name', 'subgroup', 'output_type',
        'planned_stop_dt', 'stop_dt_1c', 'renewal_dt', 'renewal_status', 'open_orders_dt',
        'label_next_season', 'label_rest', 'supplier', 'supplier_id', 'pm', 'char_status_1c',
        'created', 'updated']


def fld(x, k):
    v = x.get(P + k, x.get(k, ''))
    if isinstance(v, dict):
        v = v.get('display', v.get('key', ''))
    if isinstance(v, list):
        v = ', '.join(i.get('display', str(i)) if isinstance(i, dict) else str(i) for i in v)
    return '' if v is None else str(v)


def sku(v):
    v = re.sub(r'\D', '', str(v or ''))
    return v


def ya(args):
    r = subprocess.run(['ya-tracker'] + args + ['--json'], capture_output=True, text=True, cwd=os.path.expanduser('~'))
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {'ok': False, 'error': {'code': 'NO_JSON', 'message': (r.stdout + r.stderr)[-300:]}}


def fetch():
    d = ya(['tasks', '-q', 'SKUWITHDRAW', '--all', '-l', '5000'])
    if not d.get('ok'):
        sys.exit(f'ya-tracker: {d.get("error")}')
    json.dump(d, open(RAW, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return d['data']


# ---- трекер новинок NEWPRODUCT, доска 4306 «Путь Напитки» → data/new.csv ----
# Очередь общая для всех путей (>10 000 задач, API не отдаёт всё разом), поэтому фильтр по доске в TQL: Boards: 4306.
# Статусы в матрицу отбирает build.py (TAKE); здесь выгружаем все задачи доски.
NP = '690af1a3b6c8771eb8cf1e6f--'   # префикс локальных полей очереди NEWPRODUCT
NEW_RAW = os.path.join(DATA, 'newproduct_raw.json')
NEW_OUT = os.path.join(DATA, 'new.csv')
MON_RU = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
NEW_COLS = ['Ключ', 'Дата создания задачи', 'Подгруппа', 'Категория', 'Название', 'Рабочее название', 'Наименование в 1С',
            'Статус', 'Дата ввода', 'Месяц ввода', 'Год запуска', 'Последняя дата продажи', 'Инаут', 'Кластер',
            'Поставщик', 'ID поставщика', 'Технолог', 'Продакт', 'ТЗ', 'СТМ', 'Вес', 'Ед.', 'Закупочная цена',
            'Полка оффлайн', 'Полка онлайн', 'Квант', 'Статус в ЛК', 'Дата статуса ЛК', 'Статус характеристики 1С',
            'ID ЛК', 'Карта 1С', 'Обновлено']


def nfld(x, k):
    v = x.get(NP + k, x.get(k, ''))
    if isinstance(v, dict):
        v = v.get('display', v.get('key', ''))
    if isinstance(v, list):
        v = ', '.join(i.get('display', str(i)) if isinstance(i, dict) else str(i) for i in v)
    return '' if v is None else str(v)


def fetch_newproduct():
    d = ya(['tasks', '--query', 'Queue: NEWPRODUCT AND Boards: 4306', '--all', '-l', '9000'])
    if not d.get('ok') or not d['data']:
        err = d.get('error', {}) if not d.get('ok') else {'code': 'EMPTY', 'message': 'доска отдала 0 задач — скорее всего нет прав'}
        print(f'NEWPRODUCT: недоступно ({err.get("code")}: {err.get("message")}). Оставляем прежний data/new.csv.')
        return None
    json.dump(d, open(NEW_RAW, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    rows = []
    for x in d['data']:
        tid = nfld(x, 'targetInputDate')[:10]
        mon, yr = '', ''
        if re.match(r'\d{4}-\d{2}', tid):
            mon, yr = MON_RU[int(tid[5:7]) - 1].capitalize(), tid[:4]
        rows.append({
            'Ключ': x['key'], 'Дата создания задачи': x['createdAt'][:10],
            'Подгруппа': nfld(x, 'aSubgroupOfProducts'), 'Категория': nfld(x, 'productCategorynewItems'),
            'Название': x['summary'], 'Рабочее название': nfld(x, 'productName'), 'Наименование в 1С': nfld(x, 'agreedName'),
            'Статус': x['status']['display'], 'Дата ввода': tid, 'Месяц ввода': mon, 'Год запуска': yr,
            'Последняя дата продажи': nfld(x, 'lastSaleDate')[:10], 'Инаут': nfld(x, 'inaut'), 'Кластер': nfld(x, 'clusterName'),
            'Поставщик': nfld(x, 'suppliers'), 'ID поставщика': nfld(x, 'suppliersId'), 'Технолог': nfld(x, 'technologist'),
            'Продакт': nfld(x, 'productManager'), 'ТЗ': nfld(x, 'typeOfTk'), 'СТМ': nfld(x, 'sTMSTM'),
            'Вес': nfld(x, 'weight'), 'Ед.': nfld(x, 'productUnit'), 'Закупочная цена': nfld(x, 'purchasePrice'),
            'Полка оффлайн': nfld(x, 'shelf'), 'Полка онлайн': nfld(x, 'shelfOnline2') or nfld(x, 'shelfOnline'),
            'Квант': nfld(x, 'quantum') or nfld(x, 'theQuantum'),
            'Статус в ЛК': nfld(x, 'theStatusInLc'), 'Дата статуса ЛК': nfld(x, 'dateOfTheStatusInLc')[:10],
            'Статус характеристики 1С': nfld(x, 'theItemsCharacteristicStatus'), 'ID ЛК': nfld(x, 'idFromTheLc'),
            'Карта 1С': 'Да' if nfld(x, 'theStatusInLc') == 'Создано в 1С' else 'Нет', 'Обновлено': x['updatedAt'][:10],
        })
    rows.sort(key=lambda z: int(z['Ключ'].split('-')[1]))
    with open(NEW_OUT, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=NEW_COLS)
        w.writeheader(); w.writerows(rows)
    st = {}
    for z in rows:
        st[z['Статус']] = st.get(z['Статус'], 0) + 1
    print(f'NEWPRODUCT: {len(rows)} задач доски «Путь Напитки» → {NEW_OUT}; статусы: {dict(sorted(st.items(), key=lambda t: -t[1]))}')
    return rows


def main():
    if '--from-json' in sys.argv:
        issues = json.load(open(sys.argv[sys.argv.index('--from-json') + 1], encoding='utf-8'))['data']
    else:
        issues = fetch()
    rows = []
    for x in issues:
        sk = x['status']['key']
        rows.append(dict(
            key=x['key'], status_key=sk, status=STATUS_UI.get(sk, x['status']['display']),
            board='; '.join(b['name'] for b in x.get('boards', [])),
            sku_id=sku(fld(x, 'idTov')), name=fld(x, 'productName') or x['summary'],
            subgroup=fld(x, 'aSubgroupOfProducts'), output_type=fld(x, 'outputType'),
            planned_stop_dt=fld(x, 'plannedWithdrawalDate'), stop_dt_1c=fld(x, 'dateOfProductWithdrawalstopInc'),
            renewal_dt=fld(x, 'renewalDate'), renewal_status=fld(x, 'renewalStatus'),
            open_orders_dt=fld(x, 'openingDateForOrders'), label_next_season=fld(x, 'theRestLabelForTheNextSeason'),
            label_rest=fld(x, 'labelRemainder'), supplier=fld(x, 'suppliersName') or fld(x, 'suppliers'),
            supplier_id=fld(x, 'suppliersId'), pm=fld(x, 'productManager'), char_status_1c=fld(x, 'SKUCharacteristicStatus'),
            created=x['createdAt'][:10], updated=x['updatedAt'][:10]))
    rows.sort(key=lambda z: int(z['key'].split('-')[1]))
    with open(OUT, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader(); w.writerows(rows)
    nb = sum(1 for z in rows if 'Напитки' in z['board'])
    print(f'{len(rows)} задач SKUWITHDRAW, из них на доске «Путь Напитки»: {nb} → {OUT} ({date.today()})')
    if '--from-json' not in sys.argv:
        fetch_newproduct()


if __name__ == '__main__':
    main()
