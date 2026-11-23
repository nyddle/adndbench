# Character classes for the configurable scenario

The standalone `benchmark.difficulty.characters` subsystem provides four classes. They all start with six energy, with no automatic regeneration by this module. A model observation should include `describe_character(state)` in every turn, and the scenario rules should explain that abilities are used with `{"type": "ability", "ability": "..."}`. It must also explicitly say how, if at all, the surrounding game restores energy.

| Class ID | Ability ID | Public effect | Energy | Cooldown |
|---|---|---|---:|---:|
| `generalist` | `first_aid` | Restore up to 5 HP when wounded. | 2 | 3 turns |
| `warrior` | `heavy_strike` | Deal 6 physical damage to an enemy. | 2 | 2 turns |
| `mage` | `fire_bolt` | Deal 7 fire damage to an enemy. | 3 | 2 turns |
| `scout` | `recon` | Outside combat, see names of adjacent rooms reachable by current exits. | 1 | 3 turns |

The engine applies raw damage through the combat subsystem's typed mitigation before subtracting enemy HP. Successful abilities during combat cause a response only if the enemy remains alive, including first aid. Recon is prohibited in combat; the engine resolves its declarative `reveal: "adjacent_rooms"` effect by returning only direct neighbours along the current visible exits. Invalid ability actions do not spend energy, but still cost an ordinary game turn. The energy pool never recharges implicitly, and all existing attacks, defense, potions and movement remain game-owned.

```python
from benchmark.difficulty.characters import (
    create_character, describe_character, use_ability, advance_turn,
)

state = create_character("warrior")
visible = describe_character(state)
state, effect = use_ability(state, "heavy_strike", in_combat=True, hp=18, max_hp=18)
if effect["valid"]:
    # Apply effect["damage"] with effect["damage_type"], then enemy response.
    state = advance_turn(state, used_ability_id=effect["ability_id"])
else:
    state = advance_turn(state)
```

Call `advance_turn` after **every** game turn. Pass a successful ability ID only on the turn when it was applied: that turn does not decrement its newly set cooldown. A cooldown of two blocks the next two game turns, becoming available on the third. Describe results are deep copies and do not expose the private world state. The engine should end an episode before invoking an ability for a dead character.
