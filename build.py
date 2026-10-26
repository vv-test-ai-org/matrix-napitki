import re, json, sys
import pandas as pd
from datetime import date

import os
X = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data') + '/'
OUT = sys.argv[1]
M0 = (2026, 10)
H = 12
TAIL = 1
RU = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек']
MON_FULL = {m: i+1 for i, m in enumerate(['январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь'])}

def midx(y, m):  # month index relative to M0
    return (y - M0[0]) * 12 + (m - M0[1])
months = []
for i in range(H):
    y, m = M0[0] + (M0[1] - 1 + i) // 12, (M0[1] - 1 + i) % 12 + 1
    months.append(f'{RU[m-1]} {y}')

def norm(s):
    s = str(s).lower().replace('ё', 'е')
    s = re.sub(r'[«»"“”„\'`]', '', s)
    s = re.sub(r'[^0-9a-zа-я,\. ]+', ' ', s)
    s = re.sub(r'\s*,\s*', ', ', s)
    return re.sub(r'\s+', ' ', s).strip(' ,.')

ALC = {'Пиво', 'Пиво импорт', 'Сидр. Пуаре', 'Пиво, сидр, б/а тестовые', 'Вино б/а', 'Пиво б/а', 'Медовуха'}
OFF_ONLY = {'Пиво', 'Пиво импорт', 'Сидр. Пуаре', 'Пиво, сидр, б/а тестовые'}

def category_for(sub, name):
    if sub == 'Медовуха':
        return 'Напитки' if 'безалкогол' in str(name).lower() else 'Алкоголь'
    return 'Алкоголь' if sub in ALC else 'Напитки'

def channel_by_cluster(cl):
    """канал новинки из «География поставки» (clusterName трекера): есть дарксторы → офф+онл, только дарксторы → онлайн,
    только магазины → оффлайн; пусто — None (дальше правило по полкам/подгруппе)"""
    s = str(cl or '').lower()
    if not s or s == 'nan':
        return None
    dark = 'дарк' in s or 'дмд' in s or 'сеть' in s
    white = 'вайт' in s or 'шмел' in s or 'вш' in s or 'сеть' in s or 'вместимость' in s
    if dark and white:
        return 'офф+онл'
    if dark:
        return 'онлайн'
    return 'оффлайн'

def channel_for(cat, sub, name, off=None, onl=None):
    if off is not None or onl is not None:
        o1 = pd.notna(off) and off != 0
        o2 = pd.notna(onl) and onl != 0
        if o1 and not o2:
            return 'оффлайн'
        if o2 and not o1:
            return 'онлайн'
    if sub in OFF_ONLY:
        return 'оффлайн'
    if sub == 'Медовуха' and cat == 'Алкоголь' and 'безалкогол' not in str(name).lower():
        return 'оффлайн'
    return 'офф+онл'

rows, problems = [], []
def prob(kind, src, name, detail=''):
    problems.append({'kind': kind, 'src': src, 'name': str(name), 'detail': str(detail)})

# ---------- 1С (vv06.Har_kontr + tovari) via Superset — replaces weekly 909
import math
hk = pd.read_csv(X + 'har_kontr.csv')
hk['status_1c'] = hk['status_1c'].fillna('').replace('', 'Рабочая')
hk['stop_dt'] = pd.to_datetime(hk['stop_dt'])
DATA_DT = pd.Timestamp('2026-10-23')
def decide(g):
    act = g[g.activity_status == 'Активная']
    if ((act.status_1c == 'Рабочая')).any():
        return pd.Series(dict(st='Рабочая', act='Активна', D=pd.NaT, reason='', supp=', '.join(sorted(set(act[act.status_1c=='Рабочая'].supplier)))))
    fut = act[act.stop_dt.notna() & (act.stop_dt > DATA_DT)]
    if len(fut):
        x = fut.sort_values('stop_dt').iloc[-1]
        return pd.Series(dict(st=x.status_1c, act='Активна', D=x.stop_dt, reason=x.reason_code if pd.notna(x.reason_code) else '', supp=x.supplier))
    new = g[g.activity_status == 'Новая']
    if len(new) == len(g):
        return pd.Series(dict(st='Новая', act='Новая', D=pd.NaT, reason='', supp=', '.join(sorted(set(new.supplier)))))
    out = g[g.activity_status == 'Выведена']
    if len(out):
        x = out.sort_values('stop_dt').iloc[-1]
        return pd.Series(dict(st=x.status_1c if x.status_1c else 'На вывод', act='Выведена', D=x.stop_dt, reason=x.reason_code if pd.notna(x.reason_code) else '', supp=x.supplier))
    x = g.iloc[0]
    return pd.Series(dict(st=x.status_1c, act=x.activity_status, D=x.stop_dt, reason=x.reason_code if pd.notna(x.reason_code) else '', supp=x.supplier))
agg = hk.groupby('sku_id').apply(decide).reset_index()
base = hk.groupby('sku_id').agg(name=('sku_name','first'), sub=('subgroup','first'), is_alc=('is_alc','max')).reset_index()
r = base.merge(agg, on='sku_id')
r['ID'] = r.sku_id.astype(int).astype(str)
r['Товар'] = r['name']; r['Подгруппа'] = r['sub']
r['grp'] = [('Алкоголь' if (ia == 1 or (sb in ALC and sb != 'Медовуха')) else 'Напитки') for ia, sb in zip(r.is_alc, r['sub'])]
r['Статус'] = r['st']; r['Статус Акт Хар'] = r['act']
n909_all = len(hk); week = '2026-10-23'

# channel by fact of store matrix (ClickHouse, last 4 weeks)
chn = pd.read_csv(X + 'channel_ch.csv'); chn['ID'] = chn.sku_id.astype(int).astype(str)
CH_FACT = dict(zip(chn.ID, chn.channel))
# sales tail (ClickHouse): stock on stores / avg monthly sales over last 3 full months, clamped 1..3
st = pd.read_csv(X + 'sales_tail.csv'); st['ID'] = st.sku_id.astype(int).astype(str); N_TAIL = len(st)
TAILS = {}
for _, x in st.iterrows():
    if pd.notna(x.stock_last) and pd.notna(x.avg_qty_3m) and x.avg_qty_3m > 0 and x.stock_last > 0:
        TAILS[x.ID] = int(min(3, max(1, math.ceil(x.stock_last / x.avg_qty_3m))))

# ---------- база матрицы = SKU с продажами / присутствием в матрице ТТ за период (решение заказчика 26.10)
# период: последние 3 полных месяца продаж (sales_tail) + последние 4 недели матрицы ТТ (channel_ch).
# Характеристика 1С без продаж за период в матрицу не попадает, кроме позиций с датой остановки
# (вывод / сезонная пауза — их ведёт трекер вывода). Карточка «Новая» с продажами — уже текущий ассортимент.
IN_PERIOD = set(chn.ID) | set(st[st.avg_qty_3m.fillna(0) > 0].ID)
r['in_period'] = r.ID.isin(IN_PERIOD)
keep = r.in_period | (r.D.notna() & (r.act != 'Новая'))
r_nosales = r[~keep].copy()
r = r[keep].copy()
n909 = len(r)
N_NOSALES = len(r_nosales); N_NOSALES_NEW = int((r_nosales.act == 'Новая').sum())
# 1С cards for novelties matching (Greenplum v_sku_actual)
cards = pd.read_csv(X + 'sku_cards.csv'); cards['ID'] = cards.sku_id.astype(int).astype(str)
CARD_BY_NAME = {norm(n): (i, pd.notna(fs)) for n, i, fs in zip(cards.sku_name, cards.ID, cards.first_supply_min_dt)}

# ---------- трекер вывода SKUWITHDRAW (доска «Путь Напитки»): возобновления + плановые выводы
# data/withdraw.csv формирует fetch_tracker.py; раньше здесь был файл vozob.xlsx («Остатки сезонного возобновления»)
wd = pd.read_csv(X + 'withdraw.csv', dtype=str).fillna('')
wd = wd[wd.board.str.contains('Напитки') & ~wd.status.isin(['Закрыт', 'Беклог'])].copy()
WD_DT = max(wd.updated) if len(wd) else ''
for c_ in ('planned_stop_dt', 'stop_dt_1c', 'renewal_dt', 'open_orders_dt'):
    wd[c_] = pd.to_datetime(wd[c_], errors='coerce')
# у сезонного вывода дата возврата может быть задана как «Дата открытия к заказам»
wd['renewal_from_orders'] = wd.renewal_dt.isna() & wd.open_orders_dt.notna() & (wd.output_type == 'Сезонный')
wd.loc[wd.renewal_from_orders, 'renewal_dt'] = wd.loc[wd.renewal_from_orders, 'open_orders_dt']
wd['n'] = wd.key.str.split('-').str[1].astype(int)
wd = wd.sort_values('n')  # у SKU может быть несколько задач — побеждает более поздняя
RESUME_ST = 'Планируется возвращение в сезон'
wd['is_resume'] = wd.renewal_dt.notna() | (wd.status == RESUME_ST)
v = wd[wd.is_resume]  # возобновления: есть дата возврата или статус «Планируется возвращение в сезон»
name2id909 = {norm(t): i for t, i in zip(r['Товар'], r['ID'])}
ids909 = set(r['ID'])
def wd_row(x):  # задача трекера в терминах прежнего файла возобновлений
    return pd.Series({'ID тов': x.sku_id, 'IDc': x.sku_id, 'Наименование': x['name'], 'Подгруппа': x.subgroup,
                      'Статус возобновления': (x.renewal_status or None), 'Поставщик': x.supplier,
                      'Дата возобновления': x.renewal_dt, 'Ключ': x.key, 'Статус трекера': x.status, 'Этикетка': x.label_next_season,
                      'Плановый вывод': x.planned_stop_dt, 'Возврат по открытию заказов': bool(x.renewal_from_orders)})
voz, voz_unmatched, planned = {}, [], {}
for _, x in wd.iterrows():
    iid = x.sku_id if x.sku_id in ids909 else None
    if not iid:
        iid2 = name2id909.get(norm(x['name']))
        if iid2:
            prob('Трекер вывода: ID не найден в 1С — сопоставлено по названию' if x.sku_id else 'Трекер вывода: нет ID — сопоставлено по названию',
                 'Трекер вывода', x['name'], f'{x.key}: ID в 1С {iid2}')
            iid = iid2
    if x.is_resume:
        if iid:
            voz[iid] = wd_row(x)
        else:
            voz_unmatched.append(wd_row(x))
        continue
    if iid:
        planned[iid] = x
    elif pd.notna(x.planned_stop_dt):
        prob('Трекер вывода: плановый вывод, позиции нет в 1С', 'Трекер вывода', x['name'], f'{x.key}, {x.planned_stop_dt:%d.%m.%Y}')

excluded_prev = 0
stat = {'909_in': n909, '909_all': n909_all, 'week': week}

def blank():
    return [''] * H

for _, x in r.iterrows():
    cat, sub, name = x['grp'], x['Подгруппа'], x['Товар']
    ch = CH_FACT.get(x['ID']) or channel_for(cat, sub, name)
    tail = TAIL; tail_sales = TAILS.get(x['ID'], '')   # хвост выработки: по договорённости 23.10 — 1 мес.; оценка по продажам показывается рядом, если отличается
    if tail_sales == TAIL: tail_sales = ''
    cells = blank(); conf = [1] * H
    flags = []
    st = x['Статус'] if pd.notna(x['Статус']) else ''
    D = x['D']
    vz = voz.get(x['ID'])
    pl = planned.get(x['ID'])
    key = ''; stnew_tr = ''; stop_plan = False
    if x['act'] == 'Новая':
        flags.append('характеристика 1С ещё «Новая», но есть продажи за период — считается текущим ассортиментом')
    elif not x['in_period']:
        flags.append('нет продаж за период — в матрице только из-за даты остановки')
    if pl is not None:
        key = pl.key; stnew_tr = pl.status
        if pd.isna(D) and pd.notna(pl.planned_stop_dt):
            D = pl.planned_stop_dt; stop_plan = True
            flags.append('дата вывода из трекера, в 1С её ещё нет')
        elif pd.notna(D) and pd.notna(pl.planned_stop_dt) and D.normalize() != pl.planned_stop_dt.normalize():
            flags.append(f'дата вывода в трекере {pl.planned_stop_dt:%d.%m.%Y} ≠ 1С {D:%d.%m.%Y}')
    elif vz is not None:
        key = vz['Ключ']
        if vz['Этикетка'] not in ('', '0'):
            flags.append(f'остаток этикетки на след. сезон: {vz["Этикетка"]}')
        if vz['Возврат по открытию заказов']:
            flags.append('дата возобновления взята из «Дата открытия к заказам»')
        plD = vz['Плановый вывод']
        if pd.isna(D) and pd.notna(plD):
            D = plD; stop_plan = True
            flags.append('дата вывода из трекера, в 1С её ещё нет')
        elif pd.notna(D) and pd.notna(plD) and D.normalize() != plD.normalize():
            flags.append(f'дата вывода в трекере {plD:%d.%m.%Y} ≠ 1С {D:%d.%m.%Y}')
    end = None
    if pd.isna(D):
        cells = [ch] * H
    else:
        sm = midx(D.year, D.month)      # месяц остановки — товар ещё в продаже
        end = sm + tail                  # дальше — хвост выработки остатка
        for i in range(0, min(sm, H - 1) + 1):
            cells[i] = ch
        for i in range(max(sm + 1, 0), min(end, H - 1) + 1):
            cells[i] = 'хвост'
            if stop_plan: conf[i] = 0
        if st == 'Рабочая' and not stop_plan:
            flags.append('«Рабочая» с датой остановки')
            prob('Статус «Рабочая», но стоит дата остановки', '1С', name, f'ID {x["ID"]}, дата {D:%d.%m.%Y}')
    typ = 'Текущий'
    vz_status = ''
    if vz is not None:
        R = vz['Дата возобновления']
        vz_status = vz['Статус возобновления'] if pd.notna(vz['Статус возобновления']) else 'нет статуса'
        typ = 'Возобновление'
        if pd.notna(R):
            rm = midx(R.year, R.month)
            last = end if end is not None else -1
            start = max(rm, 0, last + 1)
            if rm < 0 and (end is None or end >= 0):
                flags.append(f'дата возобновления в трекере уже прошла ({R:%d.%m.%Y}) — проверьте')
            if start < H and (end is not None):
                c_ok = 1 if vz_status == 'готово' else 0
                for i in range(start, H):
                    cells[i] = 'возобновление' if (i == start and rm >= 0) else ch
                    conf[i] = c_ok
                flags.append('нет даты окончания сезона')
                if c_ok == 0:
                    flags.append('возобновление не подтверждено')
        else:
            flags.append('нет даты возобновления в трекере — задайте дату')
            prob('Возобновление без даты', 'Трекер вывода', name, vz['Ключ'])
    elif st == 'Приостановлена' and x['reason'].startswith('5.') and end is not None:
        flags.append('сезонная пауза без даты возврата')
        prob('Сезонная приостановка, но нет в файле возобновлений', '1С', name, f'ID {x["ID"]}, остановка {D:%d.%m.%Y}')
    if all(c == '' for c in cells):
        excluded_prev += 1
        continue
    rows.append(dict(cat=cat, sub=sub, id=x['ID'], key=key, name=name, w='',
                     typ=typ, st1c=st, stop=(D.strftime('%d.%m.%Y') if pd.notna(D) else ''), reason=x['reason'],
                     stnew=(vz_status or stnew_tr), target=(vz['Дата возобновления'].strftime('%d.%m.%Y') if vz is not None and pd.notna(vz['Дата возобновления']) else ''),
                     inout='', ch=ch, cells=cells, conf=conf, ready='', flags=flags, backlog=0, supp=x['supp'], tail=tail, tail_sales=tail_sales, chsrc=('факт матрицы ТТ' if x['ID'] in CH_FACT else 'правило'), src=('1С + трекер вывода' if (vz is not None or pl is not None) else '1С')))
stat['909_prev'] = excluded_prev
# SKU с продажами за период, которых нет среди характеристик 1С (vv06) вообще — свежие вводы / расхождение справочников
ids_in_rows = set(x['id'] for x in rows if x['id'])
N_CH_ONLY = 0
for _, x in chn.iterrows():
    if x.ID in ids_in_rows or x.ID in set(hk.sku_id.astype(int).astype(str)):
        continue
    sub = str(x.grp); name = str(x.nm); cat = category_for(sub, name); ch = x.channel or channel_for(cat, sub, name)
    N_CH_ONLY += 1
    rows.append(dict(cat=cat, sub=sub, id=x.ID, key='', name=name, w='', typ='Текущий', st1c='—', stop='', reason='', stnew='', target='', inout='',
                     ch=ch, cells=[ch] * H, conf=[1] * H, ready='', flags=['есть продажи за период, но нет характеристики в 1С (vv06) — проверьте справочник'],
                     backlog=0, supp='', tail=TAIL, tail_sales='', chsrc='факт матрицы ТТ', src='Продажи (ClickHouse)'))
stat['nosales'] = N_NOSALES; stat['nosales_new'] = N_NOSALES_NEW; stat['ch_only'] = N_CH_ONLY

for x in voz_unmatched:
    name = x['Наименование']; sub = x['Подгруппа']; cat = category_for(sub, name)
    ch = channel_for(cat, sub, name)
    R = x['Дата возобновления']; cells = blank(); conf = [0] * H
    vz_status = x['Статус возобновления'] if pd.notna(x['Статус возобновления']) else 'нет статуса'
    c_ok = 1 if vz_status == 'готово' else 0
    flags = ['нет в 1С', 'нет даты окончания сезона']
    if pd.notna(R):
        rm = midx(R.year, R.month)
        if rm < 0:
            flags.append(f'дата возобновления в трекере уже прошла ({R:%d.%m.%Y}) — проверьте')
        for i in range(max(rm, 0), H):
            cells[i] = 'возобновление' if (i == rm) else ch
            conf[i] = c_ok
    else:
        flags.append('нет даты возобновления в трекере — задайте дату')
    prob('Возобновление: позиции нет среди активных характеристик 1С, взята из трекера вывода', 'Трекер вывода', name, f'{x["Ключ"]}, ID {x["IDc"] or "—"}')
    rows.append(dict(cat=cat, sub=sub, id=x['IDc'] or '', key=x['Ключ'], name=name, w='', typ='Возобновление', st1c='—', stop='', reason='',
                     stnew=vz_status, target=(R.strftime('%d.%m.%Y') if pd.notna(R) else ''), inout='', ch=ch, cells=cells, conf=conf,
                     ready='', flags=flags, backlog=0, supp=x['Поставщик'] if pd.notna(x['Поставщик']) else '', tail='', chsrc='правило', src='Трекер вывода'))
stat['voz_in'] = len(v); stat['voz_unmatched'] = len(voz_unmatched)

ROW_BY_ID = {x['id']: x for x in rows if x['id']}
ROW_BY_NAME = {norm(x['name']): x for x in rows if x['typ'] != 'Новинка'}
VOL = re.compile(r',?\s*(ж/б|ж б)?\s*\d+([\.,]\d+)?\s*(мл|л|гр|г|кг)\.?$')
def strip_vol(z): return VOL.sub('', z).strip(' ,.')
ROW_BY_SV = {}
for x in rows:
    if x['typ'] != 'Новинка': ROW_BY_SV.setdefault(strip_vol(norm(x['name'])), x)
ROW_NAMES = [(norm(x['name']), x) for x in rows if x['typ'] != 'Новинка']
def find_row(*cands):
    for cnd in cands:
        if not cnd or str(cnd) == 'nan': continue
        k = norm(cnd); ks = strip_vol(k)
        if k in ROW_BY_NAME: return ROW_BY_NAME[k]
        if ks in ROW_BY_SV: return ROW_BY_SV[ks]
        if len(ks) >= 14:
            for nm, x in ROW_NAMES:
                if nm.startswith(ks): return x
    return None
# ---------- novelties (трекер NEWPRODUCT, пока выгрузка CSV)
n = pd.read_csv(X + 'new.csv')
stat['new_all'] = len(n)
# решение заказчика 23.10: в матрицу попадают только рабочие статусы — от «Согласование наименования» до «Открыть SKU».
# Беклог, Отложено, Торг, Согласование КП, дегустация, В продаже, Постоянный ассортимент, Выведена, Отказ, Закрыт — не берём:
# позиции «в продаже» уже сидят в матрице через 1С.
TAKE = ['Согласование наименования', 'Приложить макет ДС', 'Согласование ДС', 'Заведение в ЛК', 'Статус из ЛК',
        'Согласование КДП', 'Согласование этикетки', 'Готов к старту', 'Планирование первого заказа', 'Планирование объёма', 'Открыть SKU']
IN_1C_ST = set(TAKE[3:])   # с «Заведение в ЛК» карточка уже есть в 1С — берём ID оттуда
READY = {st_: ('высокая' if st_ in IN_1C_ST else 'средняя') for st_ in TAKE}
names909 = set(norm(t) for t in r['Товар'])
n909_sv = set(strip_vol(x) for x in names909)
c = dict(taken=0, skipped=0, insale_ok=0, nodate=0, far=0, inplan=0, dup909=0, card_missing=0)
skipped_by = {}
nodate_list = []
ID_PREFIX = re.compile(r'^\s*(\d[\d\s ]{3,})\s+(?=\S)')   # «94 374 Сок яблочный…» — ID 1С, приписанный к наименованию
def new_name(x):
    """присвоенное наименование из 1С (без ID-префикса), иначе рабочее название из трекера (без скобок); + ID 1С из префикса"""
    nm1c = x['Наименование в 1С'] if pd.notna(x['Наименование в 1С']) and str(x['Наименование в 1С']).strip() not in ('-', '') else None
    id_pref = ''
    if nm1c:
        m_ = ID_PREFIX.match(str(nm1c))
        if m_:
            id_pref = re.sub(r'\D', '', m_.group(1)); nm1c = str(nm1c)[m_.end():].strip()
    title = str(x['Название']).strip()
    m_ = ID_PREFIX.match(title)
    if m_:
        id_pref = id_pref or re.sub(r'\D', '', m_.group(1)); title = title[m_.end():].strip()
    return nm1c, (nm1c or re.sub(r'\s*\(.*$', '', title).strip() or title), title, id_pref
for _, x in n.iterrows():
    st = x['Статус']; sub = x['Подгруппа'] if pd.notna(x['Подгруппа']) else ''
    if st not in TAKE or 'МБ' in sub or not sub:
        c['skipped'] += 1; skipped_by[st] = skipped_by.get(st, 0) + 1; continue
    c['taken'] += 1
    nm1c, name, title, id_pref = new_name(x)
    card = CARD_BY_NAME.get(norm(nm1c)) if nm1c else None
    if card is None: card = CARD_BY_NAME.get(norm(re.sub(r'\s*\(.*$', '', title)))
    if card is None and id_pref and (id_pref in ROW_BY_ID or id_pref in set(cards.ID)):
        card = (id_pref, id_pref in ROW_BY_ID)   # ID взят из префикса «Наименования в 1С»
    cat = category_for(sub, name)
    ch_cl = channel_by_cluster(x.get('Кластер')) if 'Кластер' in n.columns else None
    ch = ch_cl or channel_for(cat, sub, name, x['Полка оффлайн'], x['Полка онлайн'])
    io = x['Инаут'] if pd.notna(x['Инаут']) else ''
    supp = x['Поставщик'] if pd.notna(x['Поставщик']) else ''
    end_dt = pd.to_datetime(x.get('Последняя дата продажи'), errors='coerce') if 'Последняя дата продажи' in n.columns else pd.NaT
    flags = []
    if card:
        hit = ROW_BY_ID.get(card[0])
        if hit is not None:   # уже активная характеристика в 1С — считаем через 1С, трекер только привязываем
            c['insale_ok'] += 1
            if not hit['key']: hit['key'] = x['Ключ']; hit['src'] = '1С + трекер'; hit['stnew'] = st
            hit['flags'].append('в трекере ещё «' + st + '», а в 1С уже есть поставки')
            continue
        flags.append('карточка в 1С: ID ' + card[0])
    elif st in IN_1C_ST:
        c['card_missing'] += 1
        flags.append('статус «' + st + '» — карточка должна быть в 1С, но по наименованию не найдена')
    if norm(name) in names909 or strip_vol(norm(name)) in n909_sv:
        c['dup909'] += 1; flags.append('наименование уже есть в 1С')
    tid = pd.to_datetime(x.get('Дата ввода'), errors='coerce') if 'Дата ввода' in n.columns else pd.NaT
    if pd.notna(tid):
        y, m_ = tid.year, tid.month
    else:
        mon = str(x['Месяц ввода']).strip().lower()
        y = int(x['Год запуска']) if pd.notna(x['Год запуска']) else None
        m_ = MON_FULL.get(mon)
    work = x['Рабочее название'] if 'Рабочее название' in n.columns and pd.notna(x['Рабочее название']) else (title if nm1c else '')
    base_row = dict(cat=cat, sub=sub, id=(card[0] if card else ''), key=x['Ключ'], name=name, w=x['Вес'] if pd.notna(x['Вес']) else '',
                    typ='Новинка', st1c='', stop=(end_dt.strftime('%d.%m.%Y') if pd.notna(end_dt) else ''), reason='', stnew=st, inout=io, ch=ch,
                    ready=READY[st], backlog=0, supp=supp, tail='', chsrc=('география поставки' if ch_cl else 'правило'),
                    src='Трекер' + (' + 1С' if card else ''), name_work=(work if work != name else ''))
    if not m_ or not y:
        c['nodate'] += 1
        nodate_list.append(dict(key=x['Ключ'], sub=sub, name=name, st=st))
        rows.append(dict(base_row, target='', cells=blank(), conf=[0] * H, flags=flags + ['нет даты ввода в трекере — задайте дату, чтобы учесть']))
        continue
    mi = midx(y, m_)
    if mi >= H:
        c['far'] += 1; continue
    if mi < 0:
        flags.append(f'ввод просрочен (план {RU[m_-1]} {y})'); mi = 0
    last = min(midx(end_dt.year, end_dt.month), H - 1) if pd.notna(end_dt) else H - 1   # in-out: последний месяц продаж
    if pd.notna(end_dt) and last < mi:
        flags.append(f'последняя дата продажи ({end_dt:%d.%m.%Y}) раньше даты ввода — проверьте в трекере'); last = H - 1
    cells = blank()
    for i in range(mi, last + 1):
        cells[i] = 'старт' if i == mi else ch
    if io == 'Да' and pd.isna(end_dt):
        flags.append('in-out без «Последней даты продажи» в трекере — задайте «Дата остановки / окончания»')
    c['inplan'] += 1
    rows.append(dict(base_row, target=f'01.{m_:02d}.{y}', cells=cells, conf=[0] * H, flags=flags))
stat['new_skipped_by'] = skipped_by
# новинки — только из трекера NEWPRODUCT (решение заказчика 26.10): карточки 1С «Новая» без задачи трекера в матрицу не попадают
matched_ids = set(x['id'] for x in rows if x['typ'] == 'Новинка' and x['id'])
stat['cards_new'] = int((cards.first_supply_min_dt.isna()).sum()); stat['cards_matched'] = len(matched_ids)
stat['ch_fact'] = sum(1 for x in rows if x.get('chsrc') == 'факт матрицы ТТ'); stat['tail_fact'] = sum(1 for x in rows if x.get('tail_sales') not in ('', None))
stat.update({'new_' + k: v_ for k, v_ in c.items()})

for i, x in enumerate(rows):
    x['i'] = i
    x['w'] = str(x['w']).replace('.0', '') if x['w'] != '' else ''
    x.setdefault('src', '1С')
    if x['typ'] == 'Новинка': x['seg'] = 'Новинка'
    elif x['typ'] == 'Возобновление': x['seg'] = 'Возобновление'
    elif x['stop'] or x['st1c'] in ('На вывод', 'Приостановлена'): x['seg'] = 'На вывод'
    else: x['seg'] = 'Текущий ассортимент'
wx = json.load(open(X + 'weather.json'))
sources = [
  dict(what='Текущий ассортимент: статусы характеристик, даты остановки, причины, поставщики', src='1С (vv06): dbo.Har_kontr + dbo.tovari', how='Superset SQL Lab, database_id 11', dt='2026-10-23', rows=f"{n909_all} характеристик → {n909} SKU с продажами за период (ещё {N_NOSALES} без продаж исключены)"),
  dict(what='Канал (офлайн / онлайн / сеть) по факту матрицы ТТ за 4 недели', src='ClickHouse mart_mixed.dtt + report.v_org_unit_actual.is_dark_store', how='Superset SQL Lab, database_id 92', dt='2026-10-23', rows=f"{len(chn)} SKU"),
  dict(what='Хвост распродажи: остаток на ТТ и средние продажи за 3 мес.', src='ClickHouse mart_mixed.dtt', how='Superset SQL Lab, database_id 92', dt='2026-10-23', rows=f"{N_TAIL} SKU"),
  dict(what='Карточки новинок в 1С (для сопоставления с трекером по наименованию)', src='Greenplum report.v_sku_actual', how='Superset SQL Lab, database_id 76', dt='2026-10-23', rows=f"{len(cards)} карточек"),
  dict(what='План новинок: статус, дата ввода, присвоенное наименование, in-out и последняя дата продажи, география поставки', src='Яндекс.Трекер, очередь NEWPRODUCT, доска 4306 «Путь Напитки»',
       how=('API Трекера через ya-tracker (fetch_tracker.py)' if 'Дата ввода' in n.columns else 'выгрузка CSV (файл)'),
       dt=date.fromtimestamp(os.path.getmtime(X + 'new.csv')).isoformat(), rows=f"{stat['new_all']} задач, в матрице {stat['new_taken']}"),
  dict(what='Трекер вывода: сезонные возобновления (дата возврата, статус, этикетка) и плановые даты вывода до их появления в 1С', src='Яндекс.Трекер, очередь SKUWITHDRAW, доска «Вывод товаров из ассортимента; Путь Напитки»', how='API Трекера через ya-tracker (fetch_tracker.py)', dt=WD_DT, rows=f"{len(wd)} задач, из них возобновлений {len(v)}"),
]
# строка температуры убрана по решению заказчика 23.10 («не влияет на решения, не перегружать»); weather.json и weather_raw.py оставлены
problems = []; nodate_list = []

def clean(o):
    if isinstance(o, dict): return {k: clean(v_) for k, v_ in o.items()}
    if isinstance(o, list): return [clean(v_) for v_ in o]
    if isinstance(o, float) and o != o: return ''
    if o is None or o is pd.NaT: return ''
    return o
rows = clean(rows); problems = clean(problems); nodate_list = clean(nodate_list)
weather = []
for i in range(H):
    y, m = M0[0] + (M0[1] - 1 + i) // 12, (M0[1] - 1 + i) % 12 + 1
    weather.append(wx['months'].get(f'{y-1}-{m:02d}'))
import subprocess as _sp
REPO = _sp.run(['git','config','--get','remote.origin.url'], capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip().replace('git@github.com:','https://github.com/').removesuffix('.git') or None
data = dict(sources=sources, weather=None, months=months, rows=rows, problems=problems, nodate=nodate_list, stat=stat,
            built=date.today().strftime('%d.%m.%Y'), tail=TAIL, m0=list(M0), src='superset', repo=REPO)
tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'template.html'), encoding='utf-8').read()
html = tpl.replace('/*__DATA__*/null', json.dumps(data, ensure_ascii=False, default=str, allow_nan=False).replace('</', '<\\/'))
open(OUT, 'w', encoding='utf-8').write(html)
print(json.dumps(stat, ensure_ascii=False), len(rows), len(problems))
