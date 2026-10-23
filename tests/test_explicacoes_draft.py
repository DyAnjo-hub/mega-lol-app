"""Synthetic exact arithmetic fixtures for explanations, no predictive claims."""
from copy import deepcopy
import unittest
from modelo_draft_sqlite import WEIGHTS, explain_comparison


def result(blue=(80,60,55),red=(20,40,45),games=20):
    teams={}
    for side,scores in [('blue',blue),('red',red)]:
        components={}
        for category,score in zip(WEIGHTS,scores):
            components[category]={'score':score,'relation_games_sum':games,
                'missing_pairs':24,'found_pairs':1,'queried_pairs':25,
                'details':[{'first':'A','second':'B','games':games,'winrate':score/100 if score is not None else None,
                            'patch_sources':[{'patch':'16.10'}]}]}
        total=sum(WEIGHTS[c]*v['score'] for c,v in components.items()) if all(v['score'] is not None for v in components.values()) else None
        teams[side]={'score':total,'components':components}
    a,b=teams['blue']['score'],teams['red']['score']
    relative={'blue':a/(a+b)*100,'red':b/(a+b)*100} if a is not None and b is not None and a+b else None
    return {'teams':teams,'relative_indicator':relative,'weights':dict(WEIGHTS)}


class ExplanationTests(unittest.TestCase):
    def test_components_and_relations_reconstruct_observed_gap(self):
        for r in (result(),result((60,60,60),(50,50,50)),result((20,40,45),(80,60,55))):
            before=deepcopy(r);e=explain_comparison(r)
            actual=r['relative_indicator']['blue']-r['relative_indicator']['red']
            self.assertAlmostEqual(sum(c['indicator_gap_contribution'] for c in e['components']),actual)
            self.assertAlmostEqual(sum(c['indicator_gap_contribution'] for c in e['relations']),actual)
            self.assertEqual(r,before)
        e=explain_comparison(result())
        self.assertAlmostEqual(e['indicator_gap'],33)
        self.assertAlmostEqual(e['components'][0]['indicator_gap_contribution'],24)
        self.assertTrue(e['large_gap'])
        self.assertEqual(e['leader'],'blue')

    def test_leader_support_and_opposition_have_correct_signs(self):
        e=explain_comparison(result((80,40,45),(20,60,55)))
        self.assertEqual(e['leader'],'blue')
        self.assertTrue(all(r['score_gap_contribution']>0 for r in e['supporting_relations']))
        self.assertTrue(all(r['score_gap_contribution']<0 for r in e['opposing_relations']))
        e=explain_comparison(result((20,60,55),(80,40,45)))
        self.assertEqual(e['leader'],'red')
        self.assertTrue(all(r['score_gap_contribution']<0 for r in e['supporting_relations']))

    def test_missing_components_do_not_invent_comparison(self):
        e=explain_comparison(result((None,60,60),(50,50,50)))
        self.assertIsNone(e['leader']);self.assertIsNone(e['indicator_gap'])
        self.assertIsNone(e['large_gap'])
        self.assertEqual(e['supporting_relations'],[])
        self.assertTrue(all(c['indicator_gap_contribution'] is None for c in e['components']))
        self.assertIn('unavailable_component',{a['type'] for a in e['alerts']})

    def test_ties_small_samples_and_display_threshold(self):
        e=explain_comparison(result((60,60,60),(60,60,60)))
        self.assertEqual(e['leader'],'tie');self.assertFalse(e['large_gap'])
        e=explain_comparison(result(games=1),large_gap=40)
        self.assertFalse(e['large_gap'])
        self.assertIn('small_sample_influential_relation',{a['type'] for a in e['alerts']})
        self.assertIn('concentrated_component',{a['type'] for a in e['alerts']})
