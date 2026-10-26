#!/usr/bin/env python3
"""Полный цикл: выгрузить данные → собрать HTML → зашифровать кодом доступа → выложить на GitHub Pages (ветка gh-pages).

  python3 publish.py              # всё: Superset + Трекер + сборка + публикация
  python3 publish.py --no-fetch   # только сборка и публикация из текущих data/
  python3 publish.py --no-push    # собрать site/, но не пушить

Страница публикуется в site/index.html: сам HTML матрицы лежит внутри зашифрованным (AES-GCM, ключ из кода доступа
через PBKDF2-SHA256), расшифровка — в браузере. Код доступа: переменная PAGES_CODE или файл .pages-code (создаётся
при первой публикации, в репозиторий не попадает).
"""
import base64, json, os, secrets, subprocess, sys, time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'out'; SITE = HERE / 'site'; DATA = HERE / 'data'
PY = sys.executable
env = HERE / '.env'
if env.exists():
    for line in env.read_text().splitlines():
        if '=' in line and not line.strip().startswith('#'):
            k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip())


def run(cmd, **kw):
    print('+', ' '.join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=HERE, **kw)


def pages_code():
    code = os.environ.get('PAGES_CODE', '').strip()
    f = HERE / '.pages-code'
    if not code and f.exists():
        code = f.read_text().strip()
    if not code:
        code = '-'.join(secrets.token_hex(2) for _ in range(3))   # вида a1b2-c3d4-e5f6
        f.write_text(code + '\n'); os.chmod(f, 0o600)
        print(f'код доступа создан и сохранён в {f}')
    return code


def encrypt(html: str, code: str):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt, 250_000).derive(code.encode())
    ct = AESGCM(key).encrypt(iv, html.encode('utf-8'), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return dict(salt=b64(salt), iv=b64(iv), ct=b64(ct), iter=250_000)


def main():
    args = set(sys.argv[1:])
    today = date.today().isoformat()
    if '--no-fetch' not in args:
        run([PY, 'fetch_superset.py'])
        run([PY, 'fetch_tracker.py'])
        # дата данных 1С — в build.py
        b = (HERE / 'build.py').read_text(encoding='utf-8')
        import re
        b = re.sub(r"DATA_DT = pd\.Timestamp\('\d{4}-\d{2}-\d{2}'\)", f"DATA_DT = pd.Timestamp('{today}')", b)
        b = re.sub(r"week = '\d{4}-\d{2}-\d{2}'", f"week = '{today}'", b)
        b = re.sub(r"(database_id \d+', dt=)'\d{4}-\d{2}-\d{2}'", rf"\g<1>'{today}'", b)
        (HERE / 'build.py').write_text(b, encoding='utf-8')
    OUT.mkdir(exist_ok=True)
    out_html = OUT / f'Матрица_Напитки_Алкоголь_1С_{today}.html'
    run([PY, 'build.py', str(out_html)])
    html = out_html.read_text(encoding='utf-8')
    code = pages_code()
    enc = encrypt(html, code)
    SITE.mkdir(exist_ok=True)
    repo = os.environ.get('GITHUB_REPO') or subprocess.run(['git', 'config', '--get', 'remote.origin.url'], capture_output=True, text=True, cwd=HERE).stdout.strip()
    repo = repo.replace('git@github.com:', 'https://github.com/').removesuffix('.git')
    loader = (HERE / 'site_loader.html').read_text(encoding='utf-8')
    meta = dict(built=today, repo=repo, size_kb=len(html) // 1024)
    page = loader.replace('/*__ENC__*/null', json.dumps(enc)).replace('/*__META__*/null', json.dumps(meta, ensure_ascii=False))
    (SITE / 'index.html').write_text(page, encoding='utf-8')
    (SITE / '.nojekyll').write_text('')
    print(f'site/index.html собран: матрица {meta["size_kb"]} КБ, собрано {today}')
    if '--no-push' in args:
        return
    # публикация: содержимое site/ → ветка gh-pages (одним коммитом, без истории)
    tmp = HERE / '.gh-pages-tmp'
    subprocess.run(['rm', '-rf', str(tmp)]); tmp.mkdir()
    for f in SITE.iterdir():
        subprocess.run(['cp', '-R', str(f), str(tmp / f.name)], check=True)
    subprocess.run(['git', 'init', '-q', '-b', 'gh-pages'], check=True, cwd=tmp)
    subprocess.run(['git', 'add', '-A'], check=True, cwd=tmp)
    subprocess.run(['git', '-c', 'user.name=matrix-bot', '-c', 'user.email=matrix-bot@users.noreply.github.com', 'commit', '-q', '-m', f'matrix {today} {time.strftime("%H:%M")}'], check=True, cwd=tmp)
    origin = subprocess.run(['git', 'config', '--get', 'remote.origin.url'], capture_output=True, text=True, cwd=HERE).stdout.strip()
    tok = os.environ.get('GITHUB_TOKEN')   # в GitHub Actions: push токеном задания, у сервиса раннера нет git-кредов
    if tok and origin.startswith('https://github.com/'):
        origin = origin.replace('https://github.com/', f'https://x-access-token:{tok}@github.com/', 1)
    subprocess.run(['git', 'push', '-q', '--force', origin, 'HEAD:gh-pages'], check=True, cwd=tmp)
    subprocess.run(['rm', '-rf', str(tmp)])
    owner, name = repo.removeprefix('https://github.com/').split('/')[:2]
    print(f'опубликовано в gh-pages: https://{owner}.github.io/{name}/')


if __name__ == '__main__':
    main()
