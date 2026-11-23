"""Independent tests of paired short-memory story prefixes and outcomes."""
from collections import Counter
import json
import os
import subprocess
import sys
import unittest
from benchmark.balanced_short_memory import LEVELS,LENGTHS,VERSION,generate,create_game,allowed_actions,source_fingerprint

class ShortMemoryTests(unittest.TestCase):
    def test_nested_prefixes_independent_replay_and_one_attempt(self):
        for i in range(150):
            seed=f'short-test-{i}'
            games={level:create_game('memory-compact',seed,level) for level in LEVELS}
            self.assertEqual(games['s4'].initial,games['s6'].initial)
            self.assertEqual(games['s6'].initial,games['s8'].initial)
            self.assertEqual(games['s4'].events,games['s8'].events[:4])
            self.assertEqual(games['s6'].events,games['s8'].events[:6])
            self.assertEqual(len({g.target for g in games.values()}),1)
            for level,game in games.items():
                initial={x['person']:x['item'] for x in game.observe()['assignments']}
                self.assertEqual(len(initial),6);self.assertEqual(len(set(initial.values())),6)
                holding=dict(initial);events=[];actions=[];group_sizes=[]
                while game.observe()['location']!='ворота':
                    obs=game.observe();self.assertNotIn('query',obs)
                    if 'events' in obs:
                        group_sizes.append(len(obs['events']))
                        for event in obs['events']:
                            a,b=event['people'];self.assertNotEqual(a,b)
                            events.append((a,b));holding[a],holding[b]=holding[b],holding[a]
                    action={'type':'move','direction':'forward'};actions.append(action);game.step(action)
                obs=game.observe();n=LENGTHS[level]
                self.assertEqual(group_sizes,[n//2,n//2]);self.assertEqual(len(events),n)
                target=obs['query']['item'];owner=next(p for p,v in holding.items() if v==target)
                recheck=dict(initial);touched=0
                for a,b in events:
                    touched+=int(target in (recheck[a],recheck[b]));recheck[a],recheck[b]=recheck[b],recheck[a]
                answer={'type':'deliver','person':owner};self.assertIn(answer,allowed_actions('memory-compact',obs))
                actions.append(answer);game.step(answer)
                self.assertEqual(game.result()['terminal_reason'],'completed');self.assertEqual(game.result()['turns'],4)
                clone=create_game('memory-compact',seed,level)
                for action in actions:clone.step(action)
                self.assertEqual(clone.observe(),game.observe());self.assertEqual(clone.result(),game.result())
                wrong=create_game('memory-compact',seed,level)
                for action in actions[:-1]:wrong.step(action)
                other=next(x for x in obs['query']['candidates'] if x!=owner)
                wrong.step({'type':'deliver','person':other})
                self.assertEqual(wrong.result()['terminal_reason'],'incorrect_answer')
                with self.assertRaises(RuntimeError):wrong.step(answer)

    def test_private_values_not_exposed(self):
        secret='PRIVATE-SEED-d6c9'
        g=create_game('memory-compact',secret,'s8')
        while not g.done:
            obs=g.observe();s=json.dumps(obs,ensure_ascii=False)
            for hidden in (secret,'"answer"','"target"','"seed"'):self.assertNotIn(hidden,s)
            if obs['location']=='ворота':break
            g.step({'type':'move','direction':'forward'})

    def test_hash_seed_and_invalid_arguments(self):
        code=('import json; from benchmark.balanced_short_memory import generate; '
              'print(json.dumps(generate("dev-hash"),sort_keys=True,ensure_ascii=False))')
        a=subprocess.check_output([sys.executable,'-c',code],env={**os.environ,'PYTHONHASHSEED':'1'})
        b=subprocess.check_output([sys.executable,'-c',code],env={**os.environ,'PYTHONHASHSEED':'999'})
        self.assertEqual(a,b);self.assertEqual(len(source_fingerprint()),64);self.assertEqual(VERSION,'balanced-short-memory-0.1.0')
        for axis,level in (('memory','s4'),('memory-compact','s5')):
            with self.assertRaises(ValueError):create_game(axis,'x',level)
        with self.assertRaises(ValueError):generate(True)
        game=create_game('memory-compact','x','s4')
        while not game.done:game.step({'type':'move','direction':'forward','notes':'hidden'})
        self.assertEqual(game.terminal_reason,'turn_limit')

if __name__=='__main__':unittest.main()
