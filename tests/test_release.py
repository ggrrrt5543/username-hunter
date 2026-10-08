import io
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import updater
from scripts.build_release import build

class ReleaseTests(unittest.TestCase):
    def test_version_order(self):
        self.assertGreater(updater.version_tuple('v8.10.0'), updater.version_tuple('8.9.0'))
        for invalid in ['8.4','banana','8.4.0/evil','8.4.0-rc1']:
            with self.assertRaises(updater.UpdateError): updater.version_tuple(invalid)

    def test_new_public_version_series(self):
        self.assertTrue(updater.is_newer_release('1.0.0', '8.4.2'))
        self.assertTrue(updater.is_newer_release('v1.0.1', '8.4.0'))
        self.assertTrue(updater.is_newer_release('1.0.1', '1.0.0'))
        self.assertFalse(updater.is_newer_release('1.0.0', '1.0.1'))
        self.assertFalse(updater.is_newer_release('8.4.2', '1.0.0'))
        self.assertFalse(updater.is_newer_release('1.0.0', '1.0.0'))

    def test_private_files_excluded(self):
        for path in ['.env','data/hunter.db','data/settings.json','data/sessions/main.session',
                     'data/ready.txt','data/progress.json','data/market_cache.json','data/hunter.log',
                     'data/custom_words.txt','__pycache__/cli.pyc','../cli.py','/cli.py','data/../cli.py',
                     'docs/../../.env','docs/a\\b.py','C:/cli.py','.git/config','.venv/cli.py']:
            self.assertFalse(updater.is_shipped(path),path)
        self.assertTrue(updater.is_shipped('.env.example'))
        self.assertTrue(updater.is_shipped('data/words_en.txt'))

    def test_package_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact=build(output=tmp)
            entries=updater.validate_archive(artifact.read_bytes(),updater.current_version())
            self.assertIn('cli.py',entries)
            self.assertNotIn('.env',entries)
            self.assertNotIn('.gitattributes',entries)  # Git-only file; older updater rejects it
            self.assertNotIn('data/settings.json',entries)

    def test_zip_windows_launchers_are_ascii_crlf(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = build(output=tmp)
            with zipfile.ZipFile(artifact) as archive:
                for name in ['run.bat', 'update.bat']:
                    content = archive.read('username_hunter/' + name)
                    self.assertTrue(content.isascii(), name)
                    self.assertNotIn(b'\n', content.replace(b'\r\n', b''), name)
                    self.assertNotIn(b'\r', content.replace(b'\r\n', b''), name)
                    self.assertTrue(content.startswith(b'@echo off\r\n'))
                    self.assertNotIn(b') else (', content)

    @unittest.skipUnless(os.name == 'nt', 'Requires actual Windows CMD')
    def test_cmd_executes_both_launchers(self):
        with tempfile.TemporaryDirectory(prefix='hunter batch ') as tmp:
            root = Path(tmp)
            for name, entry in [('run.bat', 'bootstrap.py'), ('update.bat', 'updater.py')]:
                (root / name).write_bytes((ROOT / name).read_bytes())
                (root / entry).write_text("import sys; print('BATCH_LAUNCH_OK ' + ' '.join(sys.argv[1:]))\n")
                result = subprocess.run(['cmd.exe', '/d', '/c', name + ' --version'],
                    cwd=root, input='\n', capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('BATCH_LAUNCH_OK --version', result.stdout)
                self.assertNotIn('not recognized', result.stdout + result.stderr)

    def test_archive_rejects_traversal(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z: z.writestr('username_hunter/../.env','bad')
        with self.assertRaises(updater.UpdateError): updater.validate_archive(stream.getvalue(),'8.4.0')

    def test_archive_rejects_duplicate(self):
        stream=io.BytesIO()
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(stream,'w') as z:
                z.writestr('username_hunter/cli.py','one')
                z.writestr('username_hunter/cli.py','two')
        with self.assertRaises(updater.UpdateError): updater.validate_archive(stream.getvalue(),'8.4.0')

    def test_archive_rejects_symlink(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            i=zipfile.ZipInfo('username_hunter/cli.py'); i.external_attr=0o120777<<16
            z.writestr(i,'../../.env')
        with self.assertRaises(updater.UpdateError): updater.validate_archive(stream.getvalue(),'8.4.0')

    def test_data_preserved_and_code_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'data/sessions').mkdir(parents=True)
            fixtures={'.env':b'private', 'data/hunter.db':b'database', 'data/settings.json':b'{}',
                      'data/sessions/main.session':b'session', 'data/progress.json':b'progress',
                      'data/custom_words.txt':b'personal words'}
            for path,data in fixtures.items(): (root/path).write_bytes(data)
            (root/'cli.py').write_bytes(b'old code')
            backup=updater.install_entries({'cli.py':b'new code','VERSION':b'8.4.0\n'},root)
            self.assertEqual((root/'cli.py').read_bytes(),b'new code')
            self.assertEqual((backup/'cli.py').read_bytes(),b'old code')
            for path,data in fixtures.items(): self.assertEqual((root/path).read_bytes(),data)

    def test_rollback_on_replace_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'cli.py').write_bytes(b'old')
            original=updater.os.replace
            calls=[]
            def failing(src,dst):
                calls.append(dst)
                if len(calls)==2: raise OSError('simulated disk error')
                return original(src,dst)
            with patch.object(updater.os,'replace',side_effect=failing):
                with self.assertRaises(OSError): updater.install_entries({'cli.py':b'new','VERSION':b'8.4.0'},root)
            self.assertEqual((root/'cli.py').read_bytes(),b'old')
            self.assertFalse((root/'VERSION').exists())

    def test_checksum_mismatch_prevents_writes(self):
        release={'tag_name':'v9.0.0','assets':[
            {'name':'username_hunter-9.0.0.zip','browser_download_url':f'https://github.com/{updater.REPOSITORY}/releases/download/v9.0.0/username_hunter-9.0.0.zip'},
            {'name':'SHA256SUMS.txt','browser_download_url':f'https://github.com/{updater.REPOSITORY}/releases/download/v9.0.0/SHA256SUMS.txt'}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(updater,'fetch',side_effect=[b'0000  username_hunter-9.0.0.zip\n',b'bad zip']):
            with self.assertRaises(updater.UpdateError): updater.apply_release(release,Path(tmp))
            self.assertFalse((Path(tmp)/'cli.py').exists())

    def test_apply_real_package_preserves_private_data(self):
        with tempfile.TemporaryDirectory() as package, tempfile.TemporaryDirectory() as tmp:
            artifact=build(output=package)
            root=Path(tmp); (root/'data/sessions').mkdir(parents=True)
            (root/'VERSION').write_text('8.3.0')
            (root/'.env').write_bytes(b'private')
            (root/'data/sessions/main.session').write_bytes(b'private-session')
            version=updater.current_version()
            release={'tag_name':'v'+version,'assets':[
                {'name':artifact.name,'browser_download_url':f'https://github.com/{updater.REPOSITORY}/releases/download/v{version}/{artifact.name}'},
                {'name':'SHA256SUMS.txt','browser_download_url':f'https://github.com/{updater.REPOSITORY}/releases/download/v{version}/SHA256SUMS.txt'}]}
            with patch.object(updater,'fetch',side_effect=[(Path(package)/'SHA256SUMS.txt').read_bytes(),artifact.read_bytes()]):
                updater.apply_release(release,root)
            self.assertEqual(updater.current_version(root),version)
            self.assertEqual((root/'.env').read_bytes(),b'private')
            self.assertEqual((root/'data/sessions/main.session').read_bytes(),b'private-session')

    def test_backup_failure_does_not_replace_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'cli.py').write_bytes(b'old')
            with patch.object(updater.shutil,'copy2',side_effect=OSError('no space for backup')):
                with self.assertRaises(OSError): updater.install_entries({'cli.py':b'new'},root)
            self.assertEqual((root/'cli.py').read_bytes(),b'old')

    def test_private_path_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'.env').write_bytes(b'private')
            with self.assertRaises(updater.UpdateError): updater.install_entries({'cli.py':b'new','.env':b'bad'},root)
            self.assertEqual((root/'.env').read_bytes(),b'private')
            self.assertFalse((root/'cli.py').exists())

    def test_untrusted_url_rejected(self):
        for url in ['http://github.com/file','https://evil.example/file','https://github.com.evil.example/file']:
            with self.assertRaises(updater.UpdateError): updater.fetch(url)

    def test_reject_existing_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root=Path(tmp)
            try: (root/'docs').symlink_to(outside,target_is_directory=True)
            except (OSError, NotImplementedError): self.skipTest('symlinks not available')
            with self.assertRaises(updater.UpdateError): updater.install_entries({'docs/setup.md':b'bad'},root)

if __name__=='__main__': unittest.main()
