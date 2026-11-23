import unittest

from pages.update_dashboard_data import sanitize


class DashboardExportTest(unittest.TestCase):
    def test_public_export_keeps_score_components_but_excludes_private_fields(self):
        source = {'scenarios': [{
            'label': 'adventure', 'axis': 'radical-adventure', 'split': 'dev',
            'seed': 'private', 'game_config': {'max_turns': 100, 'seed': 'private'}, 'episodes': [{
                'world': 1, 'model': 'gpt-6.2-astra', 'status': 'completed',
                'seed': 'private', 'actions': ['secret'], 'score': 93.85,
                'score_version': 'radical-efficiency-score-0.2.0',
                'result': {'turns': 41, 'terminal_reason': 'completed', 'clue': 'secret'},
                'components': {
                    'progress': {'weight': 85, 'earned': 85, 'private': 'secret'},
                    'efficiency': {'weight': 15, 'earned': 8.85, 'turns': 41,
                                   'turn_limit': 100, 'private': 'secret'},
                },
            }],
        }]}
        scenario = sanitize(source)[0]
        episode = scenario['episodes'][0]
        self.assertNotIn('seed', scenario)
        self.assertEqual(scenario['game_config'], {'max_turns': 100})
        self.assertNotIn('seed', episode)
        self.assertNotIn('actions', episode)
        self.assertEqual(episode['result'], {'turns': 41, 'terminal_reason': 'completed'})
        self.assertEqual(episode['score_breakdown']['progress'], {'weight': 85, 'earned': 85})
        self.assertEqual(episode['score_breakdown']['efficiency']['earned'], 8.85)
        self.assertNotIn('private', episode['score_breakdown']['efficiency'])

    def test_execution_note_is_exported_as_public_metadata(self):
        source = {'scenarios': [{'execution_note': 'Параллельный исполнитель',
                                'private_note': 'not public', 'episodes': []}]}
        scenario = sanitize(source)[0]
        self.assertEqual(scenario['execution_note'], 'Параллельный исполнитель')
        self.assertNotIn('private_note', scenario)

    def test_unknown_score_protocol_does_not_invent_components(self):
        result = sanitize({'scenarios': [{'episodes': [{
            'model': 'gpt-6-luna', 'score_version': 'unknown',
            'components': {'progress': {'earned': 85}},
        }]}]})
        self.assertIsNone(result[0]['episodes'][0]['score_breakdown'])


if __name__ == '__main__':
    unittest.main()
