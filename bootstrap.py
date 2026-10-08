"""Cross-platform launcher. Installs into .venv, not system Python."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent

def main():
    os.chdir(ROOT)
    if sys.version_info < (3, 10):
        print('Нужен Python 3.10 или новее: https://www.python.org/downloads/')
        return 1
    args = sys.argv[1:]
    # Standard-library tools also work before dependencies are installed.
    if args and args[0] in {'update','doctor'}:
        local_python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        interpreter = str(local_python) if args[0] == 'doctor' and local_python.exists() else sys.executable
        return subprocess.call([interpreter, str(ROOT / ('updater.py' if args[0] == 'update' else 'doctor.py')), *args[1:]])
    env = ROOT / '.venv'
    python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    try:
        if not python.exists():
            print('Первый запуск: создаю отдельное окружение .venv…', flush=True)
            venv.EnvBuilder(with_pip=True).create(env)
        req = ROOT / 'requirements.txt'
        digest = hashlib.sha256(req.read_bytes()).hexdigest()
        stamp = env / '.hunter-requirements'
        if not stamp.exists() or stamp.read_text() != digest:
            print('Устанавливаю зависимости…', flush=True)
            subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(req)], check=True)
            stamp.write_text(digest)
        return subprocess.call([str(python), str(ROOT / 'cli.py'), *args])
    except (OSError, subprocess.CalledProcessError) as e:
        print(f'Не удалось подготовить запуск: {e}')
        print('Проверь интернет и установку Python. Linux: может понадобиться python3-venv.')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
