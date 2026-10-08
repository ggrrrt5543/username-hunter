"""Explicit, checksum-verified updates. Never replaces user data or .env."""
import argparse
from bootstrap import configure_stdio
configure_stdio()
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import time
import urllib.request
import urllib.parse
import zipfile

ROOT = Path(__file__).resolve().parent
REPOSITORY = 'ggrrrt5543/username-hunter'
MAX_DOWNLOAD = 25 * 1024 * 1024
RUNTIME_FILES = {'cli.py','checker.py','db.py','fragment.py','generator.py','limiter.py',
                 'market.py','scorer.py','settings.py','sources.py','updater.py','doctor.py',
                 'bootstrap.py','requirements.txt','run.bat','run.sh','update.bat','update.sh',
                 '.env.example','.gitignore','VERSION','README.md','CHANGELOG.md','SECURITY.md','CONTRIBUTING.md'}

class UpdateError(Exception):
    pass

def version_tuple(value):
    if not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise UpdateError('Неверный номер версии')
    return tuple(map(int, value.lstrip('v').split('.')))

def current_version(root=ROOT):
    try:
        return (Path(root) / 'VERSION').read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        return '8.3.0'

def fetch(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'api.github.com','github.com'}:
        raise UpdateError('Недоверенный адрес загрузки')
    req = urllib.request.Request(url, headers={'User-Agent':'Username-Hunter-Updater', 'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise UpdateError('Файл слишком большой')
    return data

def latest_release():
    import urllib.error
    try:
        release = json.loads(fetch(f'https://api.github.com/repos/{REPOSITORY}/releases/latest'))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError('Публичного релиза пока нет') from e
        if e.code == 403:
            raise UpdateError('GitHub ограничил запросы. Попробуй позже или скачай релиз вручную') from e
        raise
    version_tuple(release['tag_name'])
    if release.get('draft') or release.get('prerelease'):
        raise UpdateError('Ожидался стабильный релиз')
    return release

def is_shipped(path):
    p = PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts or '\\' in path or ':' in path:
        return False
    if path in RUNTIME_FILES or path in {'data/words_en.txt','data/words_ru.txt'}:
        return True
    # Only documentation, first-party artwork and offline tests/scripts.
    return len(p.parts) > 1 and p.parts[0] in {'docs','assets','tests','scripts','.github'} and p.suffix in {'.md','.svg','.py','.yml','.yaml'}

def validate_archive(raw, expected_version):
    entries = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > 500 or sum(i.file_size for i in infos) > MAX_DOWNLOAD:
                raise UpdateError('Архив превышает лимит распаковки')
            for info in infos:
                if info.is_dir():
                    continue
                path = info.filename
                if not path.startswith('username_hunter/'):
                    raise UpdateError('Неверная структура архива')
                rel = path[len('username_hunter/'):]
                if not is_shipped(rel) or rel in entries or stat.S_ISLNK(info.external_attr >> 16):
                    raise UpdateError(f'Недопустимый файл в архиве: {rel}')
                entries[rel] = archive.read(info)
    except (zipfile.BadZipFile, RuntimeError) as e:
        raise UpdateError('Повреждённый архив') from e
    required = {'VERSION','cli.py','bootstrap.py','requirements.txt','updater.py','run.bat','run.sh',
                'data/words_en.txt','data/words_ru.txt'}
    if not required <= entries.keys():
        raise UpdateError('В архиве не хватает обязательных файлов')
    if entries['VERSION'].decode().strip() != expected_version.lstrip('v'):
        raise UpdateError('Версия архива не совпадает с релизом')
    return entries

def install_entries(entries, root=ROOT):
    root = Path(root).resolve()
    # Validate every path before writing, including existing symlinked parents.
    for rel in entries:
        if not is_shipped(rel):
            raise UpdateError(f'Недопустимый путь: {rel}')
        target = root / rel
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise UpdateError('Символическая ссылка ведёт вне папки проекта')
    backup = root / 'data' / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns()))
    if not backup.resolve().is_relative_to(root):
        raise UpdateError('Папка резервных копий ведёт вне проекта')
    backup.mkdir(parents=True, exist_ok=False)
    old = {}
    changed = []
    try:
        for rel in entries:
            target = root / rel
            old[rel] = target.exists()
            if target.exists():
                dest = backup / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, dest)
        (backup / 'restore.json').write_text(json.dumps(old), encoding='utf-8')
        for rel, content in entries.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(dir=target.parent, prefix='.hunter-update-')
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(content)
                mode = target.stat().st_mode if target.exists() else (0o755 if rel.endswith('.sh') else 0o644)
                os.chmod(temp, mode)
                os.replace(temp, target)
                changed.append(rel)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
    except Exception:
        for rel in reversed(changed):
            target = root / rel
            if old[rel]:
                shutil.copy2(backup / rel, target)
            elif target.exists():
                target.unlink()
        raise
    return backup

def apply_release(release, root=ROOT):
    version = release['tag_name'].lstrip('v')
    if version_tuple(version) <= version_tuple(current_version(root)):
        raise UpdateError('Обновление не новее установленной версии')
    assets = {a['name']: a for a in release.get('assets', [])}
    name = f'username_hunter-{version}.zip'
    if name not in assets or 'SHA256SUMS.txt' not in assets:
        raise UpdateError('В релизе нет ZIP или контрольных сумм')
    for asset in (assets[name], assets['SHA256SUMS.txt']):
        if not asset['browser_download_url'].startswith(f'https://github.com/{REPOSITORY}/releases/download/{release["tag_name"]}/'):
            raise UpdateError('Файл не принадлежит ожидаемому релизу')
    sums = fetch(assets['SHA256SUMS.txt']['browser_download_url']).decode()
    expected = None
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip('*') == name:
            expected = parts[0]
    raw = fetch(assets[name]['browser_download_url'])
    if not expected or hashlib.sha256(raw).hexdigest() != expected:
        raise UpdateError('SHA-256 не совпадает. Установка отменена')
    return install_entries(validate_archive(raw, version), root)

def main(argv=None):
    p = argparse.ArgumentParser(description='Обновление Username Hunter без замены личных данных')
    p.add_argument('--check', action='store_true', help='только проверить версию')
    p.add_argument('--yes', action='store_true', help='подтвердить обновление (закрой другие копии программы)')
    args = p.parse_args(argv)
    print(f'Username Hunter {current_version()}')
    try:
        release = latest_release()
        target = release['tag_name']
        if version_tuple(target) <= version_tuple(current_version()):
            print('Установлена актуальная версия.'); return 0
        print(f'Доступна версия {target}: https://github.com/{REPOSITORY}/releases/latest')
        if args.check: return 0
        print('Закрой другие копии программы. .env, база, настройки и сессии сохранятся.')
        if not args.yes and input('Скачать и установить? [y/да/N]: ').strip().lower() not in {'y','yes','да','д'}:
            print('Обновление отменено.'); return 0
        backup = apply_release(release)
        print(f'Обновлено до {target}. Резервная копия кода: {backup}')
        print('Запусти run.bat / run.sh заново — зависимости обновятся автоматически.')
        return 0
    except Exception as e:
        print(f'Обновление не выполнено: {e}')
        print(f'Ручное скачивание: https://github.com/{REPOSITORY}/releases/latest')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
