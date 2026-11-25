import unittest

from benchmark.mechanics_probes import build_mechanics_probes, public_probe, check_answer


def entry(action, next_message):
    """An (action, resulting message) pair; the message lands in the next observation."""
    return action, next_message


def trace_from(pairs):
    trace = []
    previous_message = '...'
    for action, message in pairs:
        trace.append({'observation': {'room': 'A', 'exits': ['north'], 'message': previous_message},
                      'action': action})
        previous_message = message
    return trace, {'room': 'B', 'exits': [], 'message': previous_message}


class MechanicsProbesTest(unittest.TestCase):
    def test_consistent_facts_yield_probes(self):
        trace, final = trace_from([
            entry({'type': 'attack'}, 'Вы нанесли 3 урона. Противник ответил: −2 здоровья.'),
            entry({'type': 'attack'}, 'Вы нанесли 3 урона. Противник ответил: −2 здоровья.'),
            entry({'type': 'defend'}, 'Вы защищаетесь: потеряли 1 здоровье, следующая атака сильнее.'),
            entry({'type': 'attack'}, 'Вы нанесли 5 урона. Противник ответил: −2 здоровья.'),
            entry({'type': 'move', 'direction': 'north'},
                  'Вы перешли в другую комнату. При отступлении вы потеряли 2 здоровья.'),
        ])
        probes = {p['id']: p for p in build_mechanics_probes(trace, final)}
        self.assertEqual(probes['mechanics_attack_plain']['answer'], '3')
        self.assertEqual(probes['mechanics_attack_boosted']['answer'], '5')
        self.assertEqual(probes['mechanics_enemy_response']['answer'], '2')
        self.assertEqual(probes['mechanics_retreat_cost']['answer'], '2')
        self.assertEqual(probes['mechanics_defend_cost']['answer'], '1')
        self.assertTrue(all(p['capability'] == 'mechanics_inference' for p in probes.values()))
        self.assertEqual(set(public_probe(probes['mechanics_attack_plain'])), {'id', 'question'})

    def test_conflicting_and_zero_values_are_skipped(self):
        trace, final = trace_from([
            entry({'type': 'attack'}, 'Вы нанесли 3 урона. Противник ответил: −2 здоровья.'),
            entry({'type': 'attack'}, 'Вы нанесли 3 урона. Противник ответил: −6 здоровья.'),
            entry({'type': 'attack'}, 'Вы нанесли 3 урона. Противник ответил: −0 здоровья. Противник побеждён.'),
        ])
        probes = {p['id']: p for p in build_mechanics_probes(trace, final)}
        self.assertNotIn('mechanics_enemy_response', probes)
        self.assertEqual(probes['mechanics_attack_plain']['answer'], '3')

    def test_unobserved_facts_are_not_asked(self):
        trace, final = trace_from([
            entry({'type': 'move', 'direction': 'north'}, 'Вы перешли в другую комнату.'),
        ])
        self.assertEqual(build_mechanics_probes(trace, final), [])

    def test_check_answer(self):
        probe = {'answer': '3'}
        self.assertTrue(check_answer(probe, '3'))
        self.assertTrue(check_answer(probe, '3 урона'))
        self.assertFalse(check_answer(probe, '5'))
        self.assertFalse(check_answer(probe, '3 или 5'))
        self.assertFalse(check_answer(probe, 'не знаю'))
        self.assertFalse(check_answer(probe, None))

    def test_empty_and_malformed_trace(self):
        self.assertEqual(build_mechanics_probes([], {'message': 'x'}), [])
        self.assertEqual(build_mechanics_probes([{'observation': None, 'action': None}], {}), [])


if __name__ == '__main__':
    unittest.main()
