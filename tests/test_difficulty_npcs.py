"""Test deterministic NPC knowledge and its public dialogue boundary."""
import copy
import json
import os
import subprocess
import sys
import unittest

from benchmark.difficulty.npcs import build_npc_knowledge, dialogue, get_topics


def example():
    world = {
        'rooms': [
            {'id': 'v', 'name': 'Деревня', 'zone': 'overworld', 'exits': {}},
            {'id': 'm', 'name': 'Горная башня', 'zone': 'tower', 'exits': {}},
            {'id': 'd', 'name': 'Далёкий склеп', 'zone': 'dungeon', 'exits': {}},
            {'id': 'h', 'name': 'Тихое болото', 'zone': 'overworld', 'exits': {}},
        ],
        'sites': {'elder': 'v', 'wizard': 'm', 'dragon': 'd', 'herbalist': 'h'},
    }
    plan = {
        'npcs': [{'id': 'elder', 'name': 'Старейшина', 'room_id': 'v'},
                 {'id': 'wizard', 'name': 'Маг', 'room_id': 'm'},
                 {'id': 'herbalist', 'name': 'Травница', 'room_id': 'h'}],
        'items': [{'id': 'relic', 'name': 'реликвия'}],
        'quests': [{'id': 'main', 'title': 'Возвращение реликвии', 'giver_id': 'elder',
                    'objectives': [
                        {'id': 'wizard', 'event': 'talk', 'target_id': 'wizard', 'room_id': 'm', 'requires': []},
                        {'id': 'dragon', 'event': 'defeat', 'target_id': 'dragon', 'room_id': 'd', 'requires': ['wizard']},
                        {'id': 'relic', 'event': 'search', 'target_id': 'relic', 'room_id': 'd', 'requires': ['dragon']},
                    ]}],
    }
    return world, plan


class NpcKnowledgeTests(unittest.TestCase):
    def test_topics_never_reveal_room_names_but_requested_fact_is_grounded(self):
        world, plan = example()
        index = build_npc_knowledge(1, world, plan, 'hard')
        found = set()
        for npc in plan['npcs']:
            public = get_topics(index, npc['id'])
            serialized = json.dumps(public, ensure_ascii=False)
            for room in world['rooms']:
                self.assertNotIn(room['name'], serialized)
            for topic in public:
                if topic['id'].startswith('quest:'):
                    found.add(topic['id'])
                    reply = dialogue(index, npc['id'], topic['id'])
                    self.assertTrue(reply['valid'])
                    oid = topic['id'].split(':')[-1]
                    objective = next(x for x in plan['quests'][0]['objectives'] if x['id'] == oid)
                    expected = next(x['name'] for x in world['rooms'] if x['id'] == objective['room_id'])
                    self.assertIn(expected, reply['message'])
        self.assertEqual(found, {'quest:main:wizard', 'quest:main:dragon', 'quest:main:relic'})

    def test_one_dialogue_action_returns_one_fact_not_the_private_index(self):
        world, plan = example()
        index = build_npc_knowledge(99, world, plan, 'easy')
        reply = dialogue(index, 'elder', 'quest:main:wizard')
        self.assertEqual(set(reply), {'valid', 'message'})
        self.assertIn('Горная башня', reply['message'])
        self.assertNotIn('Далёкий склеп', reply['message'])
        self.assertNotIn('Тихое болото', reply['message'])
        follow = dialogue(index, 'elder', 'quest:main:dragon')
        self.assertIn('Далёкий склеп', follow['message'])
        self.assertIn('Сначала выполните: «Возвращение реликвии», шаг 1', follow['message'])

    def test_cross_quest_dependency_is_described_correctly(self):
        world, plan = example()
        plan['quests'].append({'id': 'help', 'title': 'Помощь травнице', 'giver_id': 'herbalist',
                               'objectives': [{'id': 'help_herb', 'event': 'talk', 'target_id': 'herbalist',
                                               'room_id': 'h', 'requires': []}]})
        plan['quests'][0]['objectives'][0]['requires'] = ['help_herb']
        index = build_npc_knowledge(8, world, plan, 'easy')
        msg = dialogue(index, 'elder', 'quest:main:wizard')['message']
        self.assertIn('Сначала выполните: «Помощь травнице», шаг 1', msg)
        self.assertNotIn('Тихое болото', msg)

    def test_harder_profile_distributes_but_does_not_lose_facts(self):
        world, plan = example()
        easy = build_npc_knowledge('same', world, plan, 'easy')
        hard = build_npc_knowledge('same', world, plan, 'hard')
        easy_topics = {t['id'] for t in get_topics(easy, 'elder')}
        hard_topics = {t['id'] for t in get_topics(hard, 'elder')}
        self.assertIn('quest:main:dragon', easy_topics)
        self.assertNotIn('quest:main:dragon', hard_topics)
        owners = [n['id'] for n in plan['npcs'] if any(t['id'] == 'quest:main:dragon' for t in get_topics(hard, n['id']))]
        self.assertEqual(len(owners), 1)
        self.assertIn('Далёкий склеп', dialogue(hard, owners[0], 'quest:main:dragon')['message'])
        self.assertEqual(dialogue(hard, 'elder', 'quest:main:dragon')['valid'], False)

    def test_unknown_topic_and_npc_do_not_reveal_facts(self):
        world, plan = example()
        index = build_npc_knowledge(7, world, plan)
        self.assertEqual(get_topics(index, 'missing'), [])
        self.assertEqual(dialogue(index, 'elder', 'missing'), {'valid': False, 'message': 'Собеседник не знает такой темы.'})
        self.assertEqual(dialogue(index, 'missing', 'quest:main:wizard')['valid'], False)
        self.assertEqual(get_topics(index, []), [])
        self.assertEqual(dialogue(index, {}, 'any')['valid'], False)

    def test_repeatable_across_hash_seeds_and_no_mutation(self):
        world, plan = example()
        orig = copy.deepcopy((world, plan))
        result = build_npc_knowledge(42, world, plan, 'medium')
        self.assertEqual(result, build_npc_knowledge(42, world, plan, 'medium'))
        self.assertEqual((world, plan), orig)
        code = ('import json; from benchmark.difficulty.npcs import build_npc_knowledge; '
                f'w={world!r}; p={plan!r}; '
                "print(json.dumps(build_npc_knowledge(42,w,p,'medium'),sort_keys=True,ensure_ascii=False))")
        outputs = []
        for val in ('1', '8675309'):
            outputs.append(subprocess.check_output([sys.executable, '-c', code], env=dict(os.environ, PYTHONHASHSEED=val), text=True))
        self.assertEqual(outputs[0], outputs[1])

    def test_rejects_mismatched_authoritative_sites(self):
        world, plan = example()
        plan['quests'][0]['objectives'][1]['room_id'] = 'h'
        with self.assertRaises(ValueError):
            build_npc_knowledge(1, world, plan, 'easy')
        with self.assertRaises(ValueError):
            build_npc_knowledge(1, world, plan, 'impossible')


if __name__ == '__main__':
    unittest.main()
