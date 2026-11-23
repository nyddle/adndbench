# Exploratory Codex-agent pilot

These are **Codex-agent** sessions, not runs of the OpenAI Chat Completions adapter. Each fresh agent was asked to choose each move from its observation, calling a local bridge once per move. The test harness uses engine version 0.1.0; the seeds and 120-turn limit are identical within each paired comparison. The bridge's private state is hidden by instruction, not by a security boundary: agents have filesystem tools, so this is a pilot, not an adversarially isolated benchmark. Agent and model system instructions and sampling settings differ from the API runner and were not controlled.

Each `.jsonl` trace has the initial observation and then one JSON action and the following observation per line. Files with `_answers` record the model's responses to a batch of post-game questions, derived by `benchmark.probes.build_probes`. Unlike the standard runner, these questions were asked together, not independently. Agents retain their game histories, so these are context-retrieval checks. The number and content of questions depend on each agent's trajectory and are not a fixed comparable test set.

Models: `gpt-6.2-astra` (strong), `gpt-5.6-luna` (small), and `gpt-6-luna` (luna6). All received identical task and rule instructions except for run identifiers and initial observations; no codebase, seed, or other player's observations were intentionally included in their instructions. Each model selected one action per tool call.

Seed 1, small model: execution stopped responding at turn 77 and was interrupted and resumed without a game hint. At turn 102 it voluntarily stopped before the game ended; the orchestrator instructed it to continue to `done=true` without giving strategy advice. This additional intervention is an important asymmetry. The small sample is not evidence of reliable model separation. World seeds 1–3 are public exploratory seeds, not a held-out evaluation set.

The shared initial agent instruction is preserved in `prompt_template.txt`; placeholder values are the initial observation and the run ID. Verify all recorded actions by replaying the deterministic engine and recompute question scores:

```bash
PYTHONPATH=. python experiments/codex_pilot/evaluate.py
```

| Seed | Model | Completed quests | Turns | Invalid actions |
|---:|---|---:|---:|---:|
| 1 | strong | 3/3 | 45 | 0 |
| 1 | small | 2/3 | 120 | 6 |
| 2 | strong | 3/3 | 52 | 0 |
| 2 | small | 3/3 | 48 | 0 |
| 3 | strong | 3/3 | 44 | 0 |
| 3 | small | 3/3 | 65 | 0 |
| 1 | luna6 | 3/3 | 64 | 0 |
| 2 | luna6 | 3/3 | 50 | 0 |
| 3 | luna6 | 3/3 | 53 | 0 |

The strong and luna6 agents each answered all 27 questions correctly. The small agent answered 25 of 26 correctly: 9/9 navigation-recall, 9/9 spatial, and 7/8 quest-memory. These are sums over different trajectory-dependent questions; the questions were posed as a batch after each game and had access to the history. They do not establish comparable rates for the cognitive abilities in general.

An additional attempt to run `gpt-5.5` failed because that model is not supported with the current Codex ChatGPT account; it generated no game results. The model names are availability identifiers, not an established capability ranking.
