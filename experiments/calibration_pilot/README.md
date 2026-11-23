# Preliminary calibration of expedition-0.1.0

This is exploratory calibration, not a leaderboard or a held-out evaluation.
The [one-axis control](baseline_axes.json) measures an observation-only hand-written
heuristic on common public seeds 0–29, under 600 turns. Each variant changes
one setting from the control; the class variant compares abilities rather than
an ordered difficulty. Map size changes the generated world. A success means
all required quests completed; deaths and turn limits are reported separately.
This control is not a language-model evaluation.

```bash
PYTHONPATH=. python experiments/calibration_pilot/baseline_axes.py
```

The model pilot began with Codex agents playing on common exploratory seed 101, once for each model and profile. After early results arrived, the next consecutive seed 102 was added for the hard profile only; it was not selected using its baseline outcome. The fixed conditions are map size 6,
mixed topology, terrain diversity 2, class generalist, 600 turns. Profiles
`easy` and `hard` simultaneously set quest, combat and NPC axes; any observed
effect cannot be assigned to one of those axes. For each fresh agent, the player
instruction contains the public expedition rules and a one-action-at-a-time
bridge protocol. The actual game state, seed and answer keys are not in the
player's observation. Agents were instructed not to read files or hidden state,
but no hard sandbox or independent tool-history audit enforced this. Codex
agent system instructions, context management and generation settings differ
from the API runner and were not controlled. These sessions must not be reported
as direct Chat Completions evaluations.

Each recorded JSONL has an initial observation and one action/resulting
observation per subsequent line. The game can be replayed to verify the trace;
the trace alone does not reconstruct the agents' hidden reasoning or prove their
model identities. Early stops, technical failures and unfinished sessions are not
recorded as game deaths or turn-limit failures. Any operator intervention should
be recorded explicitly. Post-game questions, when provided, are generated from
each agent's own trajectory and are asked in a single batch with the accumulated agent history (subject to runtime context management);
they are not comparable to the runner's independent-question protocol.

After observing early results, two additional exploratory one-axis comparisons were added on seed 101 for `gpt-6.2-astra` and `gpt-5.6-luna`: `npc_hard_only` and `combat_hard_only`. In each, the quest profile remains easy, and the encounter count is fixed at two. The initial easy control uses the profile default of two encounters and its generated world, quests, enemies and NPC knowledge were verified identical to an explicit count of two. These are adaptive follow-up tests, not an independent held-out evaluation.

`oracle_solvability.py` uses the private map and quest plan solely to construct a route through each selected profile; it makes state changes through public actions. It verifies that a valid path exists within the budget on seeds 101 and 102, but does not establish that the necessary information is discoverable or that a partially observed player can find that path.

```bash
PYTHONPATH=. python experiments/calibration_pilot/oracle_solvability.py
PYTHONPATH=. python experiments/calibration_pilot/evaluate_agent_runs.py
```

## Initial profile results

These rows are separate runs on the same seed, not a statistical estimate. A voluntary stop is not an in-game death or turn-limit outcome.

| Model | Easy seed 101 | Hard seed 101 | Hard seed 102 |
|---|---|---|---|
| gpt-6.2-astra | completed, 129 turns | completed, 157 turns | completed, 155 turns |
| gpt-6-luna | agent stopped, turn 55 | death, turn 138 | agent stopped, turn 132 |
| gpt-5.6-luna | completed, 80 turns | agent stopped, turn 76 | death, turn 28 |

On seed 101 both strong-only follow-ups completed: NPC-hard at turn 120, combat-hard at turn 118. The `gpt-5.6-luna` combat-only session voluntarily stopped at turn 79 before termination. These follow-ups were selected after inspecting initial results. The NPC-only compact-model run is recorded separately in the manifest.

## One-axis model follow-ups on seed 101

| Variant | gpt-6.2-astra | gpt-5.6-luna |
|---|---|---|
| Easy control | completed at turn 129 | completed at turn 80 |
| NPC hard only | completed at turn 120 | agent stopped at turn 196; game active |
| Combat hard only, two additional encounters | completed at turn 118 | agent stopped at turn 79; game active |

The first-wave easy control and each one-axis follow-up were separately generated
and the actual control world, quest plan, encounters, NPC facts, and initial
observation were verified equal with the explicit count of two encounters. The
follow-ups were chosen after the first-wave results. No claim of causality or
model ranking can be supported by one run per cell. Details and partial traces
are in `agent_runs.json` and `agent_traces/`.

`hard` (all three quest/combat/NPC settings hard, 6×6 mixed map, generalist,
600 turns) is a **candidate for a larger pilot**, not a calibrated threshold.
On the two exploratory seeds 101 and 102, the strong agent completed both,
while the compact sessions ended in two deaths and two voluntary stops. These
four sessions are not all terminal games; never count stops as game deaths or
turn-limit losses. The sample is too small and agent context/settings are not
controlled. Next, evaluate pre-specified held-out seeds, multiple replicates,
one axis at a time, and fixed common-state probes in a consistent API harness.

Across the eight terminal sessions that were asked questions, all 64/64
recorded answers matched the corresponding generated answer keys. Questions
were selected from each individual trajectory and asked after the game, so this
is not a shared fixed-state test and the result should not be interpreted as
proof of general memory or spatial reasoning.

## Handwritten one-axis control

| Variant (one change from control) | Completed | Median turns, all 30 runs |
|---|---:|---:|
| Control | 30/30 | 159 |
| Quests hard | 30/30 | 214 |
| Combat hard, fixed two extras | 29/30 | 163 |
| Six extras, easy combat | 30/30 | 169 |
| NPC hard | 30/30 | 151.5 |
| Map size 8 | 30/30 | 225 |
| Warrior instead of generalist | 30/30 | 154 |

These are results for the specific heuristic and public seeds. All-run medians
include a death in the combat-hard variant; they should not be interpreted as
survival-adjusted efficiencies. Changing map size also changes the generated
map and quest locations. Baseline results do not establish LLM performance.
