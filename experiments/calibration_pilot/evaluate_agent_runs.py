"""Replay saved Codex-agent actions; score only recorded post-game answers."""
import json
from collections import defaultdict
from pathlib import Path
from benchmark.expedition import Game
from benchmark.probes import build_probes, check_answer

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'agent_runs.json').read_text(encoding='utf-8'))
for run in manifest['runs']:
    path = root / 'agent_traces' / (run['id'] + '.jsonl')
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    game = Game(run['seed'], max_turns=manifest['max_turns'], **run['config'])
    if game.observe() != rows[0]['observation']:
        raise ValueError(f"{run['id']}: initial observation differs")
    trace = []
    for prev, row in zip(rows, rows[1:]):
        trace.append({'observation': prev['observation'], 'action': row['action']})
        if game.step(row['action']) != row['observation']:
            raise ValueError(f"{run['id']}: replay differs at turn {game.turn}")
    if run['agent_outcome'] == 'game_terminal' and not game.done:
        raise ValueError(f"{run['id']}: recorded terminal game is not done")
    if run['agent_outcome'] != 'game_terminal' and game.done:
        raise ValueError(f"{run['id']}: recorded nonterminal game is done")
    scores = defaultdict(lambda: {'correct': 0, 'total': 0})
    answers_file = path.with_name(run['id'] + '-answers.json')
    if answers_file.exists():
        answers = json.loads(answers_file.read_text(encoding='utf-8'))
        for probe in build_probes(trace, rows[-1]['observation'], scenario='expedition'):
            result = scores[probe['capability']]
            result['total'] += 1
            result['correct'] += int(check_answer(probe, answers.get(probe['id'])))
    result = game.result()
    result.pop('events')
    print(json.dumps({'id': run['id'], 'model': run['model'],
                      'agent_outcome': run['agent_outcome'], 'game_result': result,
                      'probe_results': dict(scores)}, ensure_ascii=False))
