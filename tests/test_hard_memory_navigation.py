from collections import deque
import json
import os
import subprocess
import sys
import unittest

from benchmark.hard_memory_navigation import (LEVELS, MEMORY_SETTINGS, NAV_SETTINGS, VERSION,
                                               allowed_actions, create_game, create_compact_memory_game)


class HardVectorsTests(unittest.TestCase):
    def test_memory_independent_replay_and_one_attempt(self):
        for level in LEVELS:
            count_people, count_swaps, minimum = MEMORY_SETTINGS[level]
            for seed in range(30):
                game=create_game('memory',str(seed),level)
                seen=game.observe(); holdings={x['person']:x['item'] for x in seen['assignments']}
                self.assertEqual(len(holdings),count_people)
                self.assertEqual(len(set(holdings.values())),count_people)
                actions=[]; observations=[]; swaps=[]
                while game.observe()['location'] != 'ворота':
                    obs=game.observe(); observations.append(obs)
                    if 'event' in obs:
                        a,b=obs['event']['people'];swaps.append((a,b))
                        self.assertNotEqual(a,b);holdings[a],holdings[b]=holdings[b],holdings[a]
                    action={'type':'move','direction':'forward'}; actions.append(action);game.step(action)
                obs=game.observe();self.assertEqual(len(swaps),count_swaps)
                self.assertNotIn('answer',json.dumps(obs,ensure_ascii=False))
                target=obs['query']['item']; owner=next(p for p,v in holdings.items() if v==target)
                initial={x['person']:x['item'] for x in observations[0]['assignments']}
                self.assertNotEqual(initial[owner],target)
                tmp=dict(initial); touches=0
                for a,b in swaps:
                    touches += target in (tmp[a],tmp[b]);tmp[a],tmp[b]=tmp[b],tmp[a]
                self.assertGreaterEqual(touches,minimum)
                self.assertNotIn(owner,swaps[-1])
                action={'type':'deliver','person':owner};self.assertIn(action,allowed_actions('memory',obs))
                actions.append(action);game.step(action)
                self.assertEqual(game.result()['terminal_reason'],'completed')
                other=create_game('memory',str(seed),level)
                for action in actions:other.step(action)
                self.assertEqual(other.observe(),game.observe())
                self.assertEqual(other.result(),game.result())
                wrong=create_game('memory',str(seed),level)
                for action in actions[:-1]:wrong.step(action)
                another=next(p for p in obs['query']['candidates'] if p != owner)
                wrong.step({'type':'deliver','person':another})
                self.assertEqual(wrong.result()['terminal_reason'],'incorrect_answer')
                with self.assertRaises(RuntimeError):wrong.step({'type':'deliver','person':owner})

    def test_graph_connected_loops_and_independent_shortest_path(self):
        opposite={'north':'south','south':'north','east':'west','west':'east'}
        for level in LEVELS:
            for seed in range(30):
                game=create_game('navigation',str(seed),level)
                self.assertEqual(len(game.edges),NAV_SETTINGS[level]**2)
                self.assertEqual(len(set(game.names.values())),len(game.edges))
                distances={game.home:0}; todo=deque([game.home]);edges=0
                while todo:
                    p=todo.popleft()
                    for d,q in game.edges[p].items():
                        edges+=1;self.assertEqual(game.edges[q][opposite[d]],p)
                        if q not in distances:distances[q]=distances[p]+1;todo.append(q)
                self.assertEqual(len(distances),len(game.edges))
                self.assertGreater(edges//2,len(game.edges)-1)
                self.assertGreaterEqual(distances[game.target],NAV_SETTINGS[level])
                self.assertEqual(distances[game.target],game.result()['shortest_one_way'])

    def test_models_only_observe_current_local_events(self):
        for axis in ('memory','navigation'):
            game=create_game(axis,'private-marker-49340','hard');obs=game.observe()
            encoded=json.dumps(obs,ensure_ascii=False)
            for forbidden in ('private-marker-49340','"answer"','"seed"','"edges"'):
                self.assertNotIn(forbidden,encoded)
            if axis=='memory':
                self.assertNotIn('query',obs)
                game.step({'type':'move','direction':'forward'});obs=game.observe()
                self.assertNotIn('assignments',obs);self.assertNotIn('query',obs)

    def test_compact_preserves_every_event_and_final_answer(self):
        for level in LEVELS:
            for seed in range(30):
                for group in (1, 4, 6):
                    single=create_game('memory',str(seed),level)
                    compact=create_compact_memory_game(str(seed),level,group_size=group)
                    self.assertEqual(single.observe()['assignments'],compact.observe()['assignments'])
                    seen_single=[];seen_compact=[]
                    while single.observe()['location']!='ворота':
                        obs=single.observe()
                        if 'event' in obs:seen_single.append(obs['event'])
                        single.step({'type':'move','direction':'forward'})
                    while compact.observe()['location']!='ворота':
                        obs=compact.observe()
                        seen_compact.extend(obs.get('events',[]))
                        self.assertLessEqual(len(obs.get('events',[])),group)
                        compact.step({'type':'move','direction':'forward'})
                    self.assertEqual(seen_single,seen_compact)
                    self.assertEqual(single.observe()['query'],compact.observe()['query'])
                    self.assertEqual(single.answer,compact.answer)
                    action={'type':'deliver','person':single.answer}
                    single.step(action);compact.step(action)
                    self.assertTrue(single.result()['completed']);self.assertTrue(compact.result()['completed'])
                    self.assertEqual(compact.result()['config']['group_size'],group)
        for group in (0,7,True):
            with self.assertRaises(ValueError):create_compact_memory_game('dev','base',group_size=group)

    def test_hash_seed_reproducible(self):
        code='import json; from benchmark.hard_memory_navigation import create_game; print(json.dumps(create_game("navigation","example","hard").observe(),sort_keys=True))'
        a=subprocess.check_output([sys.executable,'-c',code],env={**os.environ,'PYTHONHASHSEED':'5'})
        b=subprocess.check_output([sys.executable,'-c',code],env={**os.environ,'PYTHONHASHSEED':'9'})
        self.assertEqual(a,b)

if __name__=='__main__':unittest.main()
