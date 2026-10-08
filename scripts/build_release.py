"""Build only allowlisted distribution files; local data is never packaged."""
import hashlib
import shutil
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from updater import is_shipped, version_tuple

def build(root=ROOT, output=None):
    root = Path(root)
    out = Path(output) if output else root / 'dist'
    out.mkdir(parents=True, exist_ok=True)
    version = (root / 'VERSION').read_text().strip()
    version_tuple(version)
    name = f'username_hunter-{version}.zip'
    files = sorted(p for p in root.rglob('*') if p.is_file() and is_shipped(p.relative_to(root).as_posix()))
    if any(p.is_symlink() for p in files):
        raise ValueError('Distribution must not contain symlinks')
    with zipfile.ZipFile(out / name, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            rel = p.relative_to(root).as_posix()
            info = zipfile.ZipInfo('username_hunter/' + rel, (2026,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if rel.endswith('.sh') else 0o100644) << 16
            content = p.read_bytes()
            if rel.endswith('.bat'):
                # CMD requires Windows line endings; keep launchers ASCII-only.
                text = content.decode('ascii').replace('\r\n', '\n').replace('\r', '\n')
                content = text.replace('\n', '\r\n').encode('ascii')
            z.writestr(info, content)
    digest = hashlib.sha256((out / name).read_bytes()).hexdigest()
    shutil.copy2(out / name, out / 'username_hunter.zip')
    (out / 'SHA256SUMS.txt').write_text(f'{digest}  {name}\n{digest}  username_hunter.zip\n', encoding='ascii')
    print(f'Built {name}: {len(files)} files, {(out/name).stat().st_size} bytes')
    return out / name

if __name__ == '__main__':
    build()
