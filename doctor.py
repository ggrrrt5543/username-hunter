"""Local diagnostics. Does not print credentials, phone numbers or session names."""
import argparse
import importlib.util
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parent

def main(argv=None):
    argparse.ArgumentParser(description='Локальная диагностика без сетевых запросов').parse_args(argv)
    print('Username Hunter — диагностика (без интернета)')
    problems = 0
    def check(label, ok, hint=''):
        nonlocal problems
        print(f'{"OK" if ok else "WARN"}  {label}' + (f' — {hint}' if hint and not ok else ''))
        if not ok: problems += 1
    print(f'Python {platform.python_version()} / {platform.system()}')
    check('Python 3.10+', sys.version_info >= (3,10))
    for module in ['httpx','bs4','lxml','dotenv','rich','telethon','python_socks']:
        check(module, importlib.util.find_spec(module) is not None, 'запусти run.bat / run.sh для установки')
    for name in ['words_en.txt','words_ru.txt']:
        check(f'Словарь {name}', (ROOT/'data'/name).is_file())
    check('Файл .env', (ROOT/'.env').exists(), 'настрой Telegram через меню; значения не выводятся')
    print('API-ключи, содержимое .env и Telegram-сессии не выводились.')
    print('WARN может означать, что первоначальная настройка ещё не завершена.')
    return 0 if not problems else 1

if __name__ == '__main__':
    raise SystemExit(main())
