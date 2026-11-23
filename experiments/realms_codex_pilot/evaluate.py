"""Replay recorded realms Codex-agent episodes and score available questions."""
import json
from collections import defaultdict
from pathlib import Path
from benchmark.realms import Game
from benchmark.probes import build_probes, check_answer

root = Path(__file__).resolve().parent
for model in ('luna6', 'luna56'):
    for seed in (1, 2, 3):
        name = f'{model}_seed{seed}'
        path = root / f'{name}.jsonl'
        if not path.exists():
            continue
        rows = [json.loads(line) for line in path.read_text(encoding='utf8').splitlines()]
        game = Game(seed, max_turns=300)
        if game.observe() != rows[0]['observation']:
            raise ValueError(f'{name}: initial observation differs')
        trace = []
        for prev, row in zip(rows, rows[1:]):
            trace.append({'observation': prev['observation'], 'action': row['action']})
            if game.step(row['action']) != row['observation']:
                raise ValueError(f'{name}: replay observation differs')
        scores = defaultdict(lambda: {'correct': 0, 'total': 0})
        answer_path = root / f'{name}_answers.json'
        if answer_path.exists():
            answers = json.loads(answer_path.read_text(encoding='utf8'))
            for probe in build_probes(trace, rows[-1]['observation'], scenario='realms'):
                counter = scores[probe['capability']]
                counter['total'] += 1
                counter['correct'] += int(check_answer(probe, answers.get(probe['id'])))
        result = game.result()
        result.pop('events')
        print(json.dumps({'agent': model, 'result': result, 'probe_results': dict(scores)}, ensure_ascii=False))
