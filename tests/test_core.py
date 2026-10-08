from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scorer import rate, level, EN, RU
from db import DB
import tempfile

class CoreTests(unittest.TestCase):
    def test_scores_are_bounded(self):
        for name in ['hello','@telegram','abcde','crypto','zzzzz','ton777','goldfox','a'*32]:
            result=rate(name)
            self.assertGreaterEqual(result.score,0)
            self.assertLessEqual(result.score,100)
    def test_normalization(self):
        self.assertEqual(rate('@HeLLo').username,'hello')
    def test_dictionaries_present(self):
        self.assertGreater(len(EN),10000); self.assertGreater(len(RU),10000)
    def test_tiers(self):
        self.assertEqual(level(95)[0],'S+')
        self.assertEqual(level(85)[0],'S')
        self.assertEqual(level(75)[0],'A')
    def test_database_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=DB(str(Path(tmp)/'hunter.db'))
            try:
                db.put('example','maybe',75,10,verified=0)
                self.assertEqual(db.counts()['maybe'],1)
                self.assertTrue(db.recent('example'))
                self.assertEqual(db.best('maybe')[0][0],'example')
            finally: db.c.close()

if __name__=='__main__': unittest.main()
