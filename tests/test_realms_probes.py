"""Spatial and quest probes only use geometry visible within a single realm."""
import unittest

from benchmark.probes import build_probes


class RealmsProbeTests(unittest.TestCase):
    def test_stairs_are_recallable_but_break_spatial_paths(self):
        trace = [
            {'observation': {'room': 'Степь', 'zone': 'overworld', 'exits': ['east']},
             'action': {'type': 'move', 'direction': 'east'}},
            {'observation': {'room': 'Подножие', 'zone': 'overworld', 'exits': ['up']},
             'action': {'type': 'move', 'direction': 'up'}},
            {'observation': {'room': 'Вход склепа', 'zone': 'dungeon', 'exits': ['east']},
             'action': {'type': 'move', 'direction': 'east'}},
            {'observation': {'room': 'Склеп масок', 'zone': 'dungeon', 'exits': ['east']},
             'action': {'type': 'move', 'direction': 'east'}},
        ]
        final = {'room': 'Зал дракона', 'zone': 'dungeon', 'exits': ['west']}
        probes = build_probes(trace, final, scenario='realms', max_per_capability=10)
        recall = [p for p in probes if p['capability'] == 'navigation_recall']
        vertical = [p for p in recall if 'направлении up' in p['question']]
        self.assertEqual([p['answer'] for p in vertical], ['Вход склепа'])
        spatial = [p for p in probes if p['capability'] == 'spatial_reasoning']
        self.assertEqual(len(spatial), 1)
        self.assertIn('Вход склепа', spatial[0]['question'])
        self.assertIn('Зал дракона', spatial[0]['question'])
        self.assertEqual(spatial[0]['answer'], 'east')

    def test_zone_change_breaks_path_even_on_cardinal_direction(self):
        trace = [
            {'observation': {'room': 'A', 'zone': 'overworld', 'exits': ['east']},
             'action': {'type': 'move', 'direction': 'east'}},
            {'observation': {'room': 'B', 'zone': 'mountain', 'exits': ['east']},
             'action': {'type': 'move', 'direction': 'east'}},
        ]
        final = {'room': 'C', 'zone': 'mountain', 'exits': ['west']}
        probes = build_probes(trace, final, scenario='realms')
        self.assertFalse(any(p['capability'] == 'spatial_reasoning' for p in probes))

    def test_quest_instructions_with_extra_information_are_detected(self):
        trace = [{'observation': {'room': 'Поселение', 'zone': 'overworld',
                                  'message': 'Старейшина: найдите сердце звезды в месте «Алтарь дракона» '
                                             'и принесите мне сюда, в «Поселение». Дракон дышит огнём.'},
                  'action': {'type': 'search'}}]
        probes = build_probes(trace, {'room': 'Степь', 'zone': 'overworld'}, scenario='realms')
        questions = [p for p in probes if p['capability'] == 'quest_memory']
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]['answer'], 'Алтарь дракона')
        self.assertNotIn('Алтарь дракона', questions[0]['question'])

    def test_missing_zone_disables_spatial_inference(self):
        trace = [
            {'observation': {'room': 'A', 'exits': ['east']},
             'action': {'type': 'move', 'direction': 'east'}},
            {'observation': {'room': 'B', 'exits': ['east']},
             'action': {'type': 'move', 'direction': 'east'}},
        ]
        probes = build_probes(trace, {'room': 'C'}, scenario='realms')
        self.assertFalse(any(p['capability'] == 'spatial_reasoning' for p in probes))


if __name__ == '__main__':
    unittest.main()
