"""Spatial questions must be derived from multiple observed movements."""
import unittest

from benchmark.probes import build_probes, check_answer, public_probe


def trace_for(directions):
    rooms = ['a', 'b', 'c', 'd', 'e']
    trace = [
        {'observation': {'room': rooms[i], 'exits': [direction], 'message': ''},
         'action': {'type': 'move', 'direction': direction}}
        for i, direction in enumerate(directions)
    ]
    return trace, {'room': rooms[len(directions)], 'message': '', 'exits': []}


def spatial(trace, final):
    return [p for p in build_probes(trace, final) if p['capability'] == 'spatial_reasoning']


class SpatialProbeTests(unittest.TestCase):
    def test_two_steps_same_axis(self):
        trace, final = trace_for(['east', 'east'])
        probes = spatial(trace, final)
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0]['answer'], 'east')
        self.assertIn('«a»', probes[0]['question'])
        self.assertIn('«c»', probes[0]['question'])
        self.assertTrue(check_answer(probes[0], ' EAST '))
        self.assertNotIn('answer', public_probe(probes[0]))

    def test_final_exits_do_not_reveal_relative_position(self):
        trace, final = trace_for(['east', 'east'])
        final['exits'] = ['east']
        probes = spatial(trace, final)
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0]['answer'], 'east')

    def test_cancellation_requires_combining_directions(self):
        trace, final = trace_for(['east', 'north', 'west'])
        probes = spatial(trace, final)
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0]['answer'], 'north')
        self.assertIn('«a»', probes[0]['question'])
        self.assertIn('«d»', probes[0]['question'])

    def test_no_probe_without_aligned_multi_step_path(self):
        for directions in ([], ['east'], ['east', 'north'], ['east', 'west']):
            trace, final = trace_for(directions)
            self.assertEqual(spatial(trace, final), [])

    def test_invalid_move_does_not_advance_path(self):
        trace, final = trace_for(['east', 'east'])
        trace[1]['action']['direction'] = 'north'
        self.assertEqual(spatial(trace, final), [])

    def test_limit_zero(self):
        trace, final = trace_for(['east', 'east'])
        self.assertEqual(build_probes(trace, final, max_per_capability=0), [])


if __name__ == '__main__':
    unittest.main()
