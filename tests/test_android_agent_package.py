"""Validate the generated phone runtime, including native Pillow dependencies."""
import hashlib
from pathlib import Path
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'android/agent-runtime'


@unittest.skipUnless(RUNTIME.is_dir(), 'Android runtime has not been generated')
class AndroidAgentPackageTest(unittest.TestCase):
    def test_native_pillow_and_its_shared_libraries_are_present(self):
        site = RUNTIME / 'arm64-v8a/bundle/site-packages'
        self.assertTrue(list((site / 'PIL').glob('_imaging*.so')))
        self.assertTrue((site / 'chaquopy/lib/libjpeg_chaquopy.so').is_file())
        with zipfile.ZipFile(site / 'pure.zip') as archive:
            self.assertIn('openpyxl/__init__.py', archive.namelist())
            self.assertIn('maa/__init__.py', archive.namelist())
        profile = (ROOT / 'android/pi-profile.yaml').read_text(encoding='utf-8')
        self.assertIn('{bundle}/site-packages/chaquopy/lib', profile)

    def test_cached_runtime_matches_project_requirements(self):
        digest = hashlib.sha256((ROOT / 'android/agent-requirements.txt').read_bytes()).hexdigest()
        self.assertEqual((RUNTIME / 'project-requirements.sha256').read_text().strip().lower(), digest)


if __name__ == '__main__':
    unittest.main()
