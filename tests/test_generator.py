"""Cooperative generators must preserve names and yield control on expensive work."""
import itertools
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import generator as g

class GeneratorTests(unittest.TestCase):
    def test_aliases_preserve_custom_templates(self):
        for alias,canonical in [('p5','5p'),('p6','6p'),('p7','7p'),('d5','5d'),('d6','6d')]:
            self.assertEqual(g.canonical_preset(alias),canonical)
        self.assertEqual(g.canonical_preset('CVCVC'),'CVCVC')

    def test_template_names_are_unchanged_by_cooperative_mode(self):
        legacy=list(g.candidates('abcDD',0))
        cooperative=list(g.candidates('abcDD',0,cooperative=True))
        self.assertEqual(legacy,[name for name in cooperative if name is not None])
        self.assertEqual(len(legacy),100)
        self.assertTrue(all(isinstance(name,str) for name in legacy))

    def test_dictionary_scoring_has_checkpoints_and_same_names(self):
        words={f'a{i:04d}':i+1 for i in range(600)}
        with patch.object(g,'EN',words),patch.object(g,'RU',{}),patch.object(g,'rate',return_value=SimpleNamespace(score=99)):
            legacy=list(g.candidates('dict',95))
            cooperative=list(g.candidates('dict',95,cooperative=True))
        self.assertIn(None,cooperative)
        self.assertEqual(legacy,[name for name in cooperative if name is not None])

    def test_full_enumeration_yields_control_even_when_no_name_matches(self):
        groups=[[['a'],['b'],['c'],['d'],['e','f']]]
        save=Mock()
        with patch.object(g,'_prog',return_value={}),patch.object(g,'_save_prog',save), \
             patch.object(g,'PROGRESS',{}),patch.object(g,'CURRENT',[None]), \
             patch.object(g,'rate',return_value=SimpleNamespace(score=0)):
            values=list(g._full(groups,'test',95,chunk=1,cooperative=True))
            self.assertEqual(values,[None,None])
            self.assertEqual(g.PROGRESS['test'],[2,2])
            self.assertEqual(save.call_args.args,('test',2))

    def test_brand_yields_before_expensive_generation(self):
        with patch.object(g,'markov') as markov:
            stream=g.candidates('brand',95,cooperative=True)
            self.assertIsNone(next(stream))
            markov.assert_not_called()
            stream.close()

    def test_mix_does_not_starve_dictionary_behind_brand(self):
        stream=g.candidates('mix',95,cooperative=True)
        def child(spec,*args,**kwargs):
            if spec=='brand': return itertools.repeat(None)
            if spec=='dict': return iter(['hello'])
            return iter(())
        with patch.object(g,'candidates',side_effect=child):
            self.assertIsNone(next(stream))
            self.assertEqual(next(stream),'hello')
        stream.close()

    def test_brand_impossible_length_stops_cleanly(self):
        self.assertEqual(list(g.candidates('brand',95,lengths=(12,12),cooperative=True)),[])

    def test_score_filter_metrics_explain_zero_candidates(self):
        metrics={}
        words={'hello':1,'world':2}
        with patch.object(g,'EN',words),patch.object(g,'RU',{}),patch.object(g,'rate',return_value=SimpleNamespace(score=80)):
            self.assertEqual(list(g.candidates('dict',95,cooperative=True,metrics=metrics)),[])
        self.assertEqual(metrics,{'total':2,'low_score':2})

    def test_visual_progress_advances_before_disk_checkpoint(self):
        groups=[[['abcde'],[str(i) for i in range(1024)]]]
        save=Mock()
        with patch.object(g,'_prog',return_value={}),patch.object(g,'_save_prog',save), \
             patch.object(g,'PROGRESS',{}),patch.object(g,'CURRENT',[None]):
            stream=g._full(groups,'live',95,chunk=1024,cooperative=True)
            self.assertIsNone(next(stream))
            self.assertIsNone(next(stream))
            self.assertEqual(g.PROGRESS['live'],[512,1024])
            save.assert_not_called()  # Interrupting here must not skip unscored names.
            stream.close()

if __name__=='__main__': unittest.main()
