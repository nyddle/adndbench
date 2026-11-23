"""Independent scoring, privacy and replay checks for midpoint memory pilot."""
from collections import Counter
import json
import os
import subprocess
import sys
import unittest
from benchmark.intermediate_memory import (VERSION, source_fingerprint, create_game,
                                           allowed_actions, PEOPLE_COUNT, EVENT_COUNT, MIN_TARGET_MOVES)

class IntermediateMemoryTests(unittest.TestCase):
    def test_independent_tracking_and_replay(self):
        for index in range(100):
            seed=f'mid-dev-{index}';game=create_game('memory-compact',seed,'medium');steps=[]
            obs=game.observe();initial={x['person']:x['item'] for x in obs['assignments']}
            self.assertEqual(len(initial),PEOPLE_COUNT);self.assertEqual(len(set(initial.values())),PEOPLE_COUNT)
            holdings=dict(initial);events=[]
            while game.observe()['location']!='ворота':
                obs=game.observe()
                self.assertNotIn('query',obs)
                if 'events' in obs:
                    self.assertEqual(len(obs['events']),6)
                    for evt in obs['events']:
                        a,b=evt['people'];self.assertNotEqual(a,b)
                        self.assertIn(a,holdings);self.assertIn(b,holdings)
                        events.append((a,b));holdings[a],holdings[b]=holdings[b],holdings[a]
                action={'type':'move','direction':'forward'};steps.append(action);game.step(action)
            obs=game.observe();self.assertEqual(len(events),EVENT_COUNT)
            item=obs['query']['item'];owner=next(p for p,x in holdings.items() if x==item)
            self.assertNotEqual(initial[owner],item);self.assertNotIn(owner,events[-1])
            current=dict(initial);target_moves=0
            for a,b in events:
                target_moves+=int(item in (current[a],current[b]));current[a],current[b]=current[b],current[a]
            self.assertGreaterEqual(target_moves,MIN_TARGET_MOVES)
            answer={'type':'deliver','person':owner};self.assertIn(answer,allowed_actions('memory-compact',obs))
            steps.append(answer);game.step(answer)
            self.assertEqual(game.result()['terminal_reason'],'completed');self.assertEqual(game.result()['turns'],6)
            clone=create_game('memory-compact',seed,'medium')
            for action in steps:clone.step(action)
            self.assertEqual(clone.observe(),game.observe());self.assertEqual(clone.result(),game.result())
            wrong=create_game('memory-compact',seed,'medium')
            for action in steps[:-1]:wrong.step(action)
            other=next(x for x in obs['query']['candidates'] if x!=owner)
            wrong.step({'type':'deliver','person':other})
            self.assertEqual(wrong.result()['terminal_reason'],'incorrect_answer')
            with self.assertRaises(RuntimeError):wrong.step(answer)

    def test_no_seed_or_answer_in_observations(self):
        secret='PRIVATE-SEED-9f0b6'
        g=create_game('memory-compact',secret,'medium')
        while not g.done:
            obs=g.observe();s=json.dumps(obs,ensure_ascii=False)
            for hidden in (secret,'"answer"','"target"','"seed"'):self.assertNotIn(hidden,s)
            if obs['location']=='ворота':break
            g.step({'type':'move','direction':'forward'})

    def test_hash_seed_reproducible(self):
        code=('import json; from benchmark.intermediate_memory import create_game; '
              'g=create_game("memory-compact","hash-test","medium"); '
              'print(json.dumps(g.observe(),sort_keys=True))')
        a=subprocess.check_output([sys.executable,'-c',code],env={**os.environ,'PYTHONHASHSEED':'1'})
        b=subprocess.check_output([sys.executable,'-c',code],env={**os.environ,'PYTHONHASHSEED':'992'})
        self.assertEqual(a,b);self.assertEqual(len(source_fingerprint()),64);self.assertEqual(VERSION,'intermediate-memory-0.1.0')

    def test_invalid_actions_and_limits(self):
        for axis,level in (('memory','medium'),('memory-compact','hard')):
            with self.assertRaises(ValueError):create_game(axis,'x',level)
        with self.assertRaises(ValueError):create_game('memory-compact',True,'medium')
        g=create_game('memory-compact','invalid','medium')
        while not g.done:g.step({'type':'move','direction':'forward','notes':'secret'})
        self.assertEqual(g.terminal_reason,'turn_limit');self.assertEqual(g.invalid_actions,g.max_turns)

if __name__=='__main__':unittest.main()
