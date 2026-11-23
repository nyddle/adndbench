import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import fork_balanced_holdout as fork
from scripts import three_model_balanced_memory as wrap


def fake_call(text, model, timeout):
    content = json.loads(text.split('\n', 1)[1])
    obs = content['current_observation']
    if obs['location'] != 'ворота':
        action = {'type': 'move', 'direction': 'forward'}
    else:
        hist = [x['observation'] for x in content['past_turns']]
        holdings = {x['person']: x['item'] for x in hist[0]['assignments']}
        for previous in hist:
            for event in previous.get('events', []):
                x, y = event['people']; holdings[x], holdings[y] = holdings[y], holdings[x]
        action = {'type': 'deliver', 'person': next(k for k, v in holdings.items() if v == obs['query']['item'])}
    return {'action': action, 'usage': {'input_tokens': 1}}


class ForkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        e, m = wrap.engine, wrap.middle
        patches = [patch.object(wrap, 'BASE', Path(self.tmp.name)),
                   patch.multiple(e, BASE=e.BASE, MODELS=e.MODELS, fingerprint=e.fingerprint,
                                  create_game=e.create_game, rule=e.rule, actions=e.actions, status=e.status),
                   patch.multiple(m, BASE=m.BASE, ADAPTER=m.ADAPTER, AXIS=m.AXIS, LEVEL=m.LEVEL,
                                  MIN_ACTIONS=m.MIN_ACTIONS, EXTRA_ALLOWED_ACTIONS=m.EXTRA_ALLOWED_ACTIONS,
                                  fingerprint=m.fingerprint, module=m.module),
                   patch.object(e, 'cli_version', return_value='test-cli')]
        for item in patches: item.start(); self.addCleanup(item.stop)
        wrap.configure('s4')
        with contextlib.redirect_stdout(io.StringIO()):
            m.init('source', 2, 3, 8, 30, 850000, 8)
            with patch.object(e, 'call', side_effect=fake_call): e.run('source', 'dev')

    def test_new_fresh_holdout_with_replay_and_budgets(self):
        e = wrap.engine; d, old, old_state = e.load('source')
        original = {p.name: p.read_bytes() for p in d.iterdir() if p.is_file()}
        with contextlib.redirect_stdout(io.StringIO()): fork.fork('source', 'fresh')
        self.assertEqual(original, {p.name: p.read_bytes() for p in d.iterdir() if p.is_file()})
        nd, plan, state = e.load('fresh')
        self.assertEqual(plan['seeds']['dev'], old['seeds']['dev'])
        self.assertEqual(len(plan['seeds']['holdout']), 3)
        self.assertFalse(set(plan['seeds']['holdout']) & set(old['seeds']['holdout'] + old['seeds']['dev']))
        self.assertEqual(state['episodes'], old_state['episodes'])
        self.assertEqual(state['receipts']['dev'], old_state['receipts']['dev'])
        for k in old:
            if k not in ('seeds', 'max_calls_per_split', 'max_input_tokens_per_split'):
                self.assertEqual(plan[k], old[k])
        audit = json.loads((nd/'audit.json').read_text())
        self.assertEqual(audit['source_plan_sha256'], e.digest(old))
        self.assertEqual(audit['new_plan_sha256'], e.digest(plan))
        self.assertEqual(plan['max_calls_per_split'], 75)
        with contextlib.redirect_stdout(io.StringIO()):
            e.seal('fresh')
            with patch.object(e, 'call', side_effect=fake_call) as mocked: e.run('fresh', 'holdout')
        self.assertEqual(mocked.call_count, 36)
        _, _, done = e.load('fresh')
        self.assertEqual(sum(k.startswith('holdout:') and v['status'] == 'completed'
                             for k, v in done['episodes'].items()), 9)

    def test_refuses_accessed_holdout_and_insufficient_budget(self):
        e = wrap.engine; d, p, st = e.load('source')
        with self.assertRaises(ValueError): fork.fork('source', 'small', max_calls=35)
        st['receipts']['holdout'].append({'status': 'inflight'})
        e.write(d/'state.json', st)
        with self.assertRaises(ValueError): fork.fork('source', 'bad')
        self.assertFalse((Path(self.tmp.name)/'bad').exists())

    def test_refuses_tampered_replay(self):
        e = wrap.engine; d, p, st = e.load('source')
        key = next(iter(st['episodes'])); st['episodes'][key]['turns'][0]['observation_sha256'] = 'bad'
        e.write(d/'state.json', st)
        with self.assertRaises(ValueError): fork.fork('source', 'bad')
        self.assertFalse((Path(self.tmp.name)/'bad').exists())


    def test_refuses_existing_destination_and_changed_source(self):
        e = wrap.engine
        with contextlib.redirect_stdout(io.StringIO()): fork.fork('source', 'fresh')
        before = (Path(self.tmp.name)/'fresh'/'plan.json').read_bytes()
        with self.assertRaises(FileExistsError): fork.fork('source', 'fresh')
        self.assertEqual(before, (Path(self.tmp.name)/'fresh'/'plan.json').read_bytes())
        d, p, st = e.load('source')
        p['source_sha256'] = 'tampered'
        e.write(d/'plan.json', p)
        with self.assertRaises(ValueError): fork.fork('source', 'bad')
        self.assertFalse((Path(self.tmp.name)/'bad').exists())


if __name__ == '__main__': unittest.main()
