# Baseline difficulty check

These are **non-LLM** agents and do not establish separation between language models. All agents receive only the observations returned by the game. These exploratory seeds are public and must not be treated as a hidden evaluation set.

Results were generated with engine 0.1.0 at commit `54f4c54185cf093cb388daa95d68ee07e9d0a9f9`. The comparison uses 1,000 worlds (seeds 0–999) and a 120-turn limit. The reactive random walk remembers visited NPCs and searches but has no map and does not parse quest descriptions; the provided baseline uses quest parsing and a learned graph. Their random state is reproducibly initialized per seed. The random walk without talking is included only as a control, not a competitive strategy.

```bash
PYTHONPATH=. python experiments/compare_baselines.py
PYTHONPATH=. python experiments/turn_limit.py
PYTHONPATH=. python experiments/baseline_10000.py
```

`baseline_comparison.json` contains the full comparison summary, and `turn_limit.json` records the turn-limit sweep over seeds 0–2999. `baseline_10000.json` records a separate 10,000-seed baseline run at the same 120-turn limit. The success rate is the fraction of games in which all three quests were completed, not the fraction of quests completed. The turn-limit sweep changes the maximum number of moves, not the mechanics or the seed set.

The paired-seed comparison and sensitivity to turn limits reveal properties of the current environment, but model performance cannot be inferred from these rules-based agents. A frontier-versus-weaker model evaluation still needs actual model runs with the same seeds, prompts, context policy, turn limit and reported model settings, along with repeated runs and per-seed results. Recall and spatial questions are generated from each model's own trajectory, so their count and composition may differ between models and must be reported.
