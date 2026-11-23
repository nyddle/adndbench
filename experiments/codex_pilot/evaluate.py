"""Replay recorded pilot actions and evaluate the supplied post-game answers."""
import json
from collections import defaultdict
from pathlib import Path

from benchmark.engine import Game
from benchmark.probes import build_probes, check_answer

root = Path(__file__).resolve().parent
for model in ('strong', 'small', 'luna6'):
    for seed in (1, 2, 3):
        name = f'{model}_seed{seed}'
        rows = [json.loads(line) for line in (root / f'{name}.jsonl').read_text(encoding='utf8').splitlines()]
        answers = json.loads((root / f'{name}_answers.json').read_text(encoding='utf8'))
        game = Game(seed, max_turns=120)
        if game.observe() != rows[0]['observation']:
            raise ValueError(f'{name}: initial observation differs')
        trace = []
        for prev, row in zip(rows, rows[1:]):
            trace.append({'observation': prev['observation'], 'action': row['action']})
            if game.step(row['action']) != row['observation']:
                raise ValueError(f'{name}: replay observation differs')
        scores = defaultdict(lambda: {'correct': 0, 'total': 0})
        for probe in build_probes(trace, rows[-1]['observation']):
            counter = scores[probe['capability']]
            counter['total'] += 1
            counter['correct'] += int(check_answer(probe, answers.get(probe['id'])))
        result = game.result()
        result.pop('events')
        print(json.dumps({'agent': model, 'result': result, 'probe_results': dict(scores)}, ensure_ascii=False))
