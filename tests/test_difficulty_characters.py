"""Character abilities are visible, constrained, and deterministic effects."""
import copy
import unittest

from benchmark.difficulty.characters import (
    advance_turn,
    available_classes,
    create_character,
    describe_character,
    use_ability,
)


class CharacterTests(unittest.TestCase):
    def test_all_classes_expose_explicit_public_rules(self):
        self.assertEqual(available_classes(), ['generalist', 'warrior', 'mage', 'scout'])
        for class_id in available_classes():
            with self.subTest(class_id=class_id):
                state = create_character(class_id)
                visible = describe_character(state)
                self.assertEqual(visible['class_id'], class_id)
                self.assertEqual(visible['energy'], visible['max_energy'])
                self.assertEqual(len(visible['abilities']), 1)
                ability = visible['abilities'][0]
                for key in ('id', 'name', 'description', 'energy_cost', 'cooldown_turns',
                            'cooldown_remaining', 'context', 'ready'):
                    self.assertIn(key, ability)
                self.assertTrue(ability['ready'])
                self.assertGreater(ability['energy_cost'], 0)
                # An observation must not let the consumer mutate player state.
                ability['name'] = 'mutated'
                self.assertNotEqual(describe_character(state)['abilities'][0]['name'], 'mutated')

    def test_character_instances_are_independent(self):
        a, b = create_character('warrior'), create_character('warrior')
        updated, _ = use_ability(a, 'heavy_strike', in_combat=True, hp=18, max_hp=18)
        self.assertEqual(a, b)
        self.assertNotEqual(updated['energy'], b['energy'])
        updated['cooldowns']['heavy_strike'] = 0
        self.assertEqual(a['cooldowns']['heavy_strike'], 0)

    def test_attacks_have_distinct_damage_types_and_consume_energy(self):
        warrior, w = use_ability(create_character('warrior'), 'heavy_strike',
                                 in_combat=True, hp=18, max_hp=18)
        mage, m = use_ability(create_character('mage'), 'fire_bolt',
                              in_combat=True, hp=18, max_hp=18)
        self.assertTrue(w['valid'] and m['valid'])
        self.assertEqual((w['damage'], w['damage_type']), (6, 'physical'))
        self.assertEqual((m['damage'], m['damage_type']), (7, 'fire'))
        self.assertTrue(w['opponent_response'])
        self.assertTrue(m['opponent_response'])
        self.assertEqual(warrior['energy'], 4)
        self.assertEqual(mage['energy'], 3)

    def test_ability_rejects_bad_context_and_unknown_ability_without_cost(self):
        state = create_character('mage')
        for ability, in_combat, reason in (
            ('fire_bolt', False, 'requires_enemy'),
            ('heavy_strike', True, 'unknown_ability'),
        ):
            with self.subTest(reason=reason):
                original = copy.deepcopy(state)
                new_state, effect = use_ability(state, ability, in_combat=in_combat,
                                                hp=17, max_hp=18)
                self.assertEqual(state, original)
                self.assertEqual(new_state, original)
                self.assertFalse(effect['valid'])
                self.assertEqual(effect['reason'], reason)

    def test_heal_is_capped_and_requires_injury(self):
        state = create_character()
        fresh, fail = use_ability(state, 'first_aid', in_combat=False, hp=18, max_hp=18)
        self.assertFalse(fail['valid'])
        self.assertEqual(fail['reason'], 'full_health')
        self.assertEqual(fresh, state)
        used, effect = use_ability(state, 'first_aid', in_combat=True, hp=16, max_hp=18)
        self.assertTrue(effect['valid'])
        self.assertEqual(effect['heal'], 2)
        self.assertTrue(effect['opponent_response'])
        self.assertEqual(used['energy'], 4)

    def test_scout_reveals_only_a_declared_adjacent_room_effect(self):
        state = create_character('scout')
        rejected, fail = use_ability(state, 'recon', in_combat=True, hp=18, max_hp=18)
        self.assertEqual(fail['reason'], 'combat_blocked')
        self.assertEqual(rejected, state)
        updated, effect = use_ability(state, 'recon', in_combat=False, hp=18, max_hp=18)
        self.assertTrue(effect['valid'])
        self.assertEqual(effect['reveal'], 'adjacent_rooms')
        self.assertFalse(effect['opponent_response'])
        self.assertEqual(updated['energy'], 5)
        self.assertNotIn('rooms', effect)
        self.assertNotIn('map', effect)

    def test_cooldown_blocks_exactly_the_next_two_turns(self):
        state = create_character('warrior')
        state, result = use_ability(state, 'heavy_strike', in_combat=True, hp=18, max_hp=18)
        self.assertTrue(result['valid'])
        state = advance_turn(state, used_ability_id='heavy_strike')
        for expected in (2, 1):
            self.assertEqual(state['cooldowns']['heavy_strike'], expected)
            after_fail, failure = use_ability(state, 'heavy_strike', in_combat=True,
                                              hp=18, max_hp=18)
            self.assertEqual(failure['reason'], 'cooldown')
            self.assertEqual(after_fail, state)
            state = advance_turn(after_fail)
        self.assertTrue(describe_character(state)['abilities'][0]['ready'])
        _, result = use_ability(state, 'heavy_strike', in_combat=True, hp=18, max_hp=18)
        self.assertTrue(result['valid'])

    def test_energy_remains_spent_even_after_cooldown(self):
        state = create_character('mage')
        for cast in range(2):
            state, result = use_ability(state, 'fire_bolt', in_combat=True, hp=18, max_hp=18)
            self.assertTrue(result['valid'])
            state = advance_turn(state, used_ability_id='fire_bolt')
            state = advance_turn(advance_turn(state))
        after, failure = use_ability(state, 'fire_bolt', in_combat=True, hp=18, max_hp=18)
        self.assertEqual(failure['reason'], 'insufficient_energy')
        self.assertEqual(after['energy'], 0)
        self.assertFalse(describe_character(after)['abilities'][0]['ready'])

    def test_dead_character_cannot_use_or_pay_for_a_skill(self):
        state = create_character()
        after, result = use_ability(state, 'first_aid', in_combat=False, hp=0, max_hp=18)
        self.assertFalse(result['valid'])
        self.assertEqual(result['reason'], 'incapacitated')
        self.assertEqual(state, after)

    def test_invalid_state_and_health_fail_clearly(self):
        with self.assertRaises(ValueError):
            create_character('dragon')
        with self.assertRaises(ValueError):
            use_ability(create_character(), 'first_aid', in_combat=False, hp=19, max_hp=18)
        with self.assertRaises(ValueError):
            use_ability(create_character(), 'first_aid', in_combat=1, hp=10, max_hp=18)
        with self.assertRaises(ValueError):
            describe_character({'class_id': 'warrior', 'energy': -1, 'cooldowns': {'heavy_strike': 0}})
        with self.assertRaises(ValueError):
            advance_turn(create_character('warrior'), used_ability_id='recon')


if __name__ == '__main__':
    unittest.main()
