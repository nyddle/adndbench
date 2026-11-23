import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import three_model_quest as q

class ThreeQuestTests(unittest.TestCase):
    def test_paired_replay_and_technical_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(q,'BASE',Path(tmp)):
            q.configure()
            with patch.object(q.engine,'cli_version',return_value='test-cli'):
                with contextlib.redirect_stdout(io.StringIO()):
                    q.engine.init('run','quest_trial','quests','extreme',2,1,35,240,12000000,35)
                    d,p,st=q.engine.load('run')
                    self.assertEqual(p['models'],list(q.MODELS))
                    specs=list(q.engine.specs(p,'dev'))
                    self.assertEqual(len(specs),6)
                    self.assertEqual(len({x[1] for x in specs[:3]}),1)
                    self.assertEqual(len({x[1] for x in specs[3:]}),1)
                    self.assertNotEqual(specs[0][1],specs[3][1])
                    with patch.object(q.engine,'call',return_value={'error':'tool_use_detected'}):
                        q.engine.run('run','dev')
                    out=io.StringIO()
                    with contextlib.redirect_stdout(out):q.status('run')
                    data=json.loads(out.getvalue())
                    stats=data['groups'][0]['models']
                    self.assertEqual(stats[q.MODELS[0]]['statuses'],{'technical_error':1,'ready':1})
                    self.assertEqual(stats[q.MODELS[0]]['terminal_games'],0)
                    self.assertEqual(stats[q.MODELS[0]]['wins'],0)
                    self.assertNotIn('seed',out.getvalue())
                    with self.assertRaises(ValueError):q.engine.run('run','dev')

if __name__=='__main__':unittest.main()
