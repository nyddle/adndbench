"""Expedition probes may only use facts from player-visible observations."""
import json
import unittest
from collections import deque

from benchmark.expedition import Game
from benchmark.probes import build_probes, public_probe


class ExpeditionProbeTests(unittest.TestCase):
    def test_easy_quest_briefing_is_scored_from_visible_message(self):
        game = Game(3, quest_difficulty='easy', npc_difficulty='easy')
        initial = game.observe()
        accepted = game.step({'type': 'talk'})
        self.assertIn('Найдите', accepted['message'])
        direction = accepted['exits'][0]
        final = game.step({'type': 'move', 'direction': direction})
        trace = [{'observation': initial, 'action': {'type': 'talk'}},
                 {'observation': accepted, 'action': {'type': 'move', 'direction': direction}}]
        probes = [p for p in build_probes(trace, final, scenario='expedition')
                  if p['capability'] == 'quest_memory']
        self.assertEqual(len(probes), 1)
        expected = game.rooms[game.objectives['main_relic']['room_id']]['name']
        self.assertEqual(probes[0]['answer'], expected)
        self.assertIn(f"«{probes[0]['answer']}»", accepted['message'])
        self.assertNotIn(probes[0]['answer'], probes[0]['question'])
        self.assertNotIn(probes[0]['answer'], json.dumps(final, ensure_ascii=False))
        self.assertNotIn('answer', public_probe(probes[0]))

    def test_actual_informant_hint_becomes_memory_question(self):
        game = Game(3, quest_difficulty='hard', npc_difficulty='hard', enemy_count=0)
        topic_id = 'quest:main:main_relic'
        # Evaluator locates an informant and routes there on its private map;
        # every mutation/observation below goes through the public game API.
        from benchmark.difficulty.npcs import get_topics
        holder = next(n for n in game.plan['npcs']
                      if topic_id in {topic['id'] for topic in get_topics(game.npc_knowledge, n['id'])})
        trace = []

        def step(action):
            trace.append({'observation': game.observe(), 'action': action})
            return game.step(action)

        initial = game.observe()
        self.assertEqual(initial['npc'], 'Старейшина')
        accepted = step({'type': 'talk'})
        self.assertIn('Получено поручение', accepted['message'])
        self.assertFalse(any(p['capability'] == 'quest_memory'
                             for p in build_probes(trace, accepted, scenario='expedition')))

        dragon_room = game.world['sites']['dragon']
        queue = deque([(game.position, [])])
        seen = {game.position}
        while queue:
            current, path = queue.popleft()
            if current == holder['room_id']:
                break
            for direction, nxt in game.rooms[current]['exits'].items():
                if nxt not in seen and nxt != dragon_room:
                    seen.add(nxt)
                    queue.append((nxt, path + [direction]))
        else:
            self.fail('test informant not reachable without entering the dragon room')
        for direction in path:
            self.assertIsNone(game.observe()['enemy'])
            step({'type': 'move', 'direction': direction})
        before = game.observe()
        self.assertIn(topic_id, {t['id'] for t in before['topics']})
        clue = step({'type': 'ask', 'topic': topic_id})
        self.assertIn('найти предмет', clue['message'])
        final = step({'type': 'search'})
        questions = [p for p in build_probes(trace, final, scenario='expedition')
                     if p['capability'] == 'quest_memory']
        self.assertEqual(len(questions), 1)
        expected = game.rooms[game.objectives['main_relic']['room_id']]['name']
        self.assertEqual(questions[0]['answer'], expected)
        self.assertIn(f"«{questions[0]['answer']}»", clue['message'])
        self.assertNotIn(questions[0]['answer'], questions[0]['question'])
        self.assertNotIn(questions[0]['answer'], json.dumps(final, ensure_ascii=False))
        self.assertIn('по поручению', questions[0]['question'])

    def test_no_probe_for_current_answer_or_unshown_fact(self):
        clue = {'room': 'Поселение', 'zone': 'overworld', 'exits': ['east'],
                'message': 'Поручение «Трава», шаг 2: найти предмет «трава» в месте «Тайное болото».'}
        trace = [{'observation': clue, 'action': {'type': 'move', 'direction': 'east'}}]
        # Answer appearing anywhere in final observation must not be asked.
        final = {'room': 'Поле', 'zone': 'overworld', 'inventory': ['Тайное болото']}
        self.assertFalse(any(p['capability'] == 'quest_memory'
                             for p in build_probes(trace, final, scenario='expedition')))
        # No quest clues means no fabricated memory task.
        empty_trace = [{'observation': {'room': 'А', 'zone': 'overworld', 'message': 'Тихо'},
                        'action': {'type': 'search'}}]
        self.assertEqual(build_probes(empty_trace, {'room': 'Б'}, scenario='expedition'), [])

    def test_malformed_or_ambiguous_clues_are_not_guessed(self):
        for message in ('Поручение «Трава», шаг 2: найти предмет «трава».',
                        'Вы нашли предмет: трава.',
                        'Поручение «Тайное болото», шаг 2: найти предмет «трава» в месте «Тайное болото».'):
            trace = [{'observation': {'room': 'А', 'zone': 'overworld', 'message': message},
                      'action': {'type': 'search'}}]
            probes = build_probes(trace, {'room': 'Б', 'message': ''}, scenario='expedition')
            self.assertFalse(any(p['capability'] == 'quest_memory' for p in probes), message)

    def test_briefing_and_hint_for_same_item_and_location_are_not_double_counted(self):
        messages = ['Старейшина: Найдите сердце звезды в месте «Алтарь» и принесите его домой.',
                    'Поручение «Сердце», шаг 2: найти предмет «сердце звезды» в месте «Алтарь».']
        trace = [{'observation': {'room': 'Поселение', 'zone': 'overworld', 'message': m},
                  'action': {'type': 'talk'}} for m in messages]
        probes = build_probes(trace, {'room': 'Поле', 'message': ''}, scenario='expedition')
        self.assertEqual(sum(p['capability'] == 'quest_memory' for p in probes), 1)

    def test_stairs_and_zone_boundaries_do_not_corrupt_spatial_inference(self):
        trace = [
            {'observation': {'room': 'А', 'zone': 'overworld', 'exits': ['east']},
             'action': {'type': 'move', 'direction': 'east'}},
            {'observation': {'room': 'Б', 'zone': 'overworld', 'exits': ['up']},
             'action': {'type': 'move', 'direction': 'up'}},
            {'observation': {'room': 'В', 'zone': 'tower', 'exits': ['east']},
             'action': {'type': 'move', 'direction': 'east'}},
            {'observation': {'room': 'Г', 'zone': 'tower', 'exits': ['east']},
             'action': {'type': 'move', 'direction': 'east'}},
        ]
        final = {'room': 'Д', 'zone': 'tower', 'exits': ['west']}
        probes = build_probes(trace, final, scenario='expedition', max_per_capability=10)
        recall = [p for p in probes if p['capability'] == 'navigation_recall']
        self.assertEqual([p['answer'] for p in recall if 'направлении up' in p['question']], ['В'])
        spatial = [p for p in probes if p['capability'] == 'spatial_reasoning']
        self.assertEqual(len(spatial), 1)
        self.assertIn('В', spatial[0]['question'])
        self.assertIn('Д', spatial[0]['question'])
        self.assertEqual(spatial[0]['answer'], 'east')


if __name__ == '__main__':
    unittest.main()
