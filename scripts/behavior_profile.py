#!/usr/bin/env python3
"""Export replay-verified, seed-free model behavior profiles for calibration pilots."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))
MODELS = ('gpt-6-luna', 'gpt-6.2-sol', 'gpt-6.2-astra')
# Each line is its own condition: never pool denominators across these protocols.
SCENARIOS = (
    ('Квест hard', 'sol_quest', 'radical-quest-sol'),
    ('Память 12 обменов', 'sol_memory', 'radical-memory-base-sol'),
    ('Память 24 обмена', 'intermediate', 'middle-memory'),
    ('Память 36 обменов', 'pair', 'radical-memory-hard'),
    ('Память 72 обмена', 'pair', 'radical-memory'),
    ('Ориентирование base', 'pair', 'radical-nav'),
    ('Память 4 обмена, balanced', 'balanced', 'short-memory-4'),
    ('Память 8 обменов, 6 миров', 'balanced', 'expanded-memory-s8'),
    ('Квест extreme, 2 мира', 'three_quest', 'expanded-quest-extreme'),
    ('Выбор партии, фиксированный случай', 'party_tactics', 'party-case'),
    ('Тактика, три врага: фиксированный случай', 'party_tactics', 'tactics-three'),
    ('Полная игра', 'integrated', 'integrated-gradient-dev'),
    ('Полная игра hard, 3 мира', 'independent_integrated', 'full-hard-3'),
)


def configured(kind, name):
    if kind == 'pair':
        from scripts import paired_codex_calibration as engine
        return engine
    if kind == 'intermediate':
        from scripts import paired_intermediate_memory as runner
        runner.configure(); return runner.engine
    if kind == 'balanced':
        from scripts import three_model_balanced_memory as runner
        runner.configure_existing(name); return runner.engine
    if kind == 'three_quest':
        from scripts import three_model_quest as runner
        runner.configure(); return runner.engine
    if kind == 'integrated':
        from scripts import gradient_codex_calibration as runner
        runner.configure(); return runner.engine
    if kind == 'independent_integrated':
        from scripts import independent_gradient_calibration as runner
        runner.configure(); return runner.engine
    if kind == 'party_tactics':
        from scripts import three_model_party_tactics as runner
        runner.configure(); return runner.engine
    if kind == 'sol_quest':
        from scripts import sol_paired_quest_extension as runner
        runner.configure(); return runner.engine
    if kind == 'sol_memory':
        from scripts import sol_paired_memory_extension as runner
        runner.configure_bridge(); runner.bridge.configure(); return runner.engine
    raise ValueError('unsupported run kind')


def public_result(result):
    # Explicit allowlist: never emit seeds, action journals, clues or room names.
    keys = ('terminal_reason', 'turns', 'invalid_actions', 'completed_tasks',
            'rooms_visited', 'rooms_total', 'relic', 'combat_status', 'combat_rounds', 'unlocked',
            'selected', 'hero_hp', 'damage_dealt', 'healing', 'charges_used')
    out = {key: result[key] for key in keys if key in result}
    if 'recruited' in result: out['recruited_count'] = len(result['recruited'])
    return out


def extract(kind, name, split):
    engine = configured(kind, name)
    _, plan, state = engine.load(name)
    if kind.startswith('sol_') and split != 'dev':
        return None  # Sol extensions intentionally do not copy holdout.
    episodes = []
    for world, seed, model in engine.specs(plan, split):
        record = state['episodes'].get(engine.key_for(split, world, model), {'status':'pending', 'turns':[]})
        status = record['status']
        # Pending episodes are intentionally not played, viewed or scored.
        if not record.get('turns') and status != 'completed':
            episodes.append({'world':world, 'model':model, 'status':status, 'result':None, 'score':None, 'components':None})
            continue
        game, _ = engine.reconstruct(plan, seed, record)
        result = public_result(game.result())
        score = components = None
        score_version = None
        if kind in ('integrated', 'independent_integrated') and status == 'completed':
            from benchmark import radical_efficiency_score
            grade = radical_efficiency_score.score(game, [turn['action'] for turn in record['turns']], episode_status=status)
            score = grade['score']
            components = grade['components']
            score_version = grade['version']
        episodes.append({'world':world, 'model':model, 'status':status, 'result':result, 'score':score, 'score_version':score_version, 'components':components})
    if kind.startswith('sol_'):
        # References were copied only after verified source replay; no raw traces.
        for ref in plan['reference_dev']['records']:
            episodes.append({'world':ref['world'], 'model':ref['model'], 'status':'completed',
                             'result':public_result(ref['result']), 'score':None, 'components':None})
    fork = plan.get('fork_provenance') or {}
    provenance = ({k:fork[k] for k in ('version','source_name','fresh_holdout_worlds','old_budget','new_budget') if k in fork}
                  if fork else None)
    measurement = ('party_choice_feasible_by_oracle' if kind == 'party_tactics' and plan['axis']=='party'
                   else 'model_played_combat' if kind == 'party_tactics' else 'game_outcome')
    return {'axis':plan['axis'], 'level':plan['level'], 'split':split, 'measurement':measurement,
            'fixed_case':kind == 'party_tactics',
            'success_definition':('BFS finds a winning strategy for the chosen party, without model executing it'
                                  if measurement == 'party_choice_feasible_by_oracle' else
                                  'Model plays and wins the battle' if measurement == 'model_played_combat'
                                  else 'Completed game outcome'),
            'effort':plan['reasoning_effort'], 'context_turns':plan['context_turns'],
            'cli_version':plan['cli_version'], 'adapter':plan['adapter'],
            'max_actions':plan['max_actions_per_game'], 'game_config':plan.get('game_config'),
            'plan_name':name, 'fork_provenance':provenance, 'episodes':episodes}


def summarize(episodes, model, measurement='game_outcome', fixed_case=False):
    relevant = [e for e in episodes if e['model'] == model]
    done = [e for e in relevant if e['status'] == 'completed']
    reasons = Counter(e['result']['terminal_reason'] for e in done)
    wins = reasons.get('completed', 0)
    vals = lambda key: [e['result'][key] for e in done if e['result'] is not None and e['result'].get(key) is not None]
    mean = lambda values: round(statistics.mean(values), 2) if values else None
    return {'planned':len(relevant), 'terminal':len(done),
            'successes':wins, 'success_rate':round(wins/len(done), 4) if done and not fixed_case else None,
            'wins':wins if measurement != 'party_choice_feasible_by_oracle' else None,
            'win_rate':round(wins/len(done), 4) if done and not fixed_case and measurement != 'party_choice_feasible_by_oracle' else None,
            'outcomes':dict(reasons), 'statuses':dict(Counter(e['status'] for e in relevant)),
            'mean_turns_terminal':mean(vals('turns')),
            'mean_invalid_terminal':mean(vals('invalid_actions')),
            'mean_score_terminal':mean([e['score'] for e in done if e['score'] is not None])}


def scenario_for_split(kind, name, split):
    # The fresh fork copies the already observed dev records; the original
    # holdout remains unused. Never combine or double-count either pool.
    if split == 'holdout' and kind == 'balanced' and name == 'short-memory-4':
        return kind, 'short-memory-4-fresh-holdout'
    if split == 'holdout' and kind in ('sol_quest', 'sol_memory'):
        return 'pair', 'radical-quest' if kind == 'sol_quest' else 'radical-memory-base'
    return kind, name


def generate(split):
    scenarios = []
    for label, kind, name in SCENARIOS:
        # The two hand-crafted diagnostics have no independent holdout.
        if split != 'dev' and kind == 'party_tactics':
            continue
        kind, name = scenario_for_split(kind, name, split)
        cmd = [sys.executable, str(Path(__file__).resolve()), '--extract', kind, name, split]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=30)
        if proc.returncode:
            scenarios.append({'label':label, 'available':False, 'reason':'plan unavailable or failed verification'})
            continue
        data = json.loads(proc.stdout)
        if data is None:
            scenarios.append({'label':label, 'available':False, 'reason':'holdout not copied to extension'})
            continue
        data.update({'label':label, 'available':True,
                     'models':{model:summarize(data['episodes'], model, data['measurement'], data['fixed_case']) for model in MODELS}})
        scenarios.append(data)
    return {'version':'behavior-profile-0.1.0', 'split':split, 'scenarios':scenarios,
            'note':'Dev is exploratory. Scores and win rates only describe completed games; incomplete episodes are not losses. Different scenarios are not pooled. No model calls.'}


def fmt(n):
    return '—' if n is None else str(n)


def markdown(data):
    lines = ['# Профиль поведения моделей', '', f"Выборка: **{data['split']}**. Условия приведены отдельно; показатели не объединяются между сценариями.",
             'Исходы и средние баллы рассчитаны только по завершённым игровым партиям; незавершённые не считаются поражениями. Модель без запусков обозначена «—».', '']
    for model in MODELS:
        lines += [f'## {model}', '', '| Сценарий | Завершено / запланировано | Успехи | Исходы | Ходы, среднее | Ошибочные действия, среднее | Балл |',
                  '|---|---:|---:|---|---:|---:|---:|']
        for scenario in data['scenarios']:
            if not scenario['available']:
                continue
            s = scenario['models'][model]
            if not s['planned']:
                lines.append(f"| {scenario['label']} | — | — | не запускалась | — | — | — |")
                continue
            outcomes = ', '.join(f'{k}: {v}' for k,v in sorted(s['outcomes'].items())) or '—'
            pending = ', '.join(f'{k}: {v}' for k,v in sorted(s['statuses'].items()) if k != 'completed')
            if pending: outcomes += f'; вне игровых исходов: {pending}'
            wins = f"{s['successes']}/{s['terminal']}" if s['terminal'] else '—'
            lines.append(f"| {scenario['label']} | {s['terminal']}/{s['planned']} | {wins} | {outcomes} | {fmt(s['mean_turns_terminal'])} | {fmt(s['mean_invalid_terminal'])} | {fmt(s['mean_score_terminal'])} |")
        lines.append('')
    lines += ['## Детали партий', '', 'Частичные показатели на незавершённых партиях — диагностический срез, а не итог или оценка поражения.', '']
    missing = [s for s in data['scenarios'] if not s['available']]
    if missing:
        lines += ['Недоступные или не прошедшие проверку планы: ' + ', '.join(s['label'] for s in missing) + '.', '']
    for scenario in data['scenarios']:
        if not scenario['available']: continue
        lines += [f"### {scenario['label']}", '']
        if scenario.get('measurement') == 'party_choice_feasible_by_oracle':
            lines += ['Один фиксированный случай: успех означает существование победной стратегии для выбранного состава по BFS; исполнение стратегии моделью не проверяется.', '']
        elif scenario.get('measurement') == 'model_played_combat':
            lines += ['Один фиксированный бой: модель выбирает действия сама. Случай не является выборкой независимых миров.', '']
        if scenario.get('plan_name'):
            provenance = scenario.get('fork_provenance')
            source = f"; исходный dev-план: `{provenance['source_name']}`" if provenance and provenance.get('source_name') else ''
            lines += [f"План: `{scenario['plan_name']}`, выборка: `{scenario['split']}`{source}.", '']
        for e in scenario['episodes']:
            if e['result'] is None: continue
            bits = [f"мир {e['world']}", e['model'], f"статус {e['status']}"]
            for key, label in (('turns','ходы'),('invalid_actions','ошибочных действий'),('completed_tasks','квестовых этапов'),
                               ('rooms_visited','посещено комнат'),('rooms_total','всего комнат'),('relic','реликвия'),
                               ('recruited_count','спутников'),('unlocked','замок открыт'),('combat_status','бой'),('combat_rounds','раундов')):
                if key in e['result'] and e['result'][key] is not None: bits.append(f"{label}: {e['result'][key]}")
            for key, label in (('selected','выбранный спутник'),('hero_hp','HP героя'),('damage_dealt','нанесённый урон'),('healing','лечение'),('charges_used','использованные заряды')):
                if key in e['result'] and e['result'][key] is not None: bits.append(f"{label}: {e['result'][key]}")
            if e['score'] is not None: bits.append(f"балл: {e['score']}")
            lines.append('- ' + '; '.join(bits) + '.')
            if e['components'] is not None:
                for key, component in e['components'].items():
                    lines.append(f"  - {key}: {component.get('status', 'оценён')}; баллы {fmt(component.get('earned'))} / {fmt(component.get('weight'))}.")
        lines.append('')
    lines += ['Число партий мало; данные не подтверждают устойчивый рейтинг. Память здесь проверяет работу с доступной историей. Бой оценивается только у дошедших до него; показатель побед и экспериментальный балл 0–100 различаются. Балл полной игры рассчитан по исследовательской шкале radical-efficiency-score-0.2.0, выбранной после первых результатов; только одинаковые настройки и лимиты сопоставимы.']
    return '\n'.join(lines) + '\n'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--split', choices=('dev','holdout'), default='dev')
    ap.add_argument('--json', dest='json_path', type=Path)
    ap.add_argument('--markdown', dest='markdown_path', type=Path)
    ap.add_argument('--extract', nargs=3, metavar=('KIND','NAME','SPLIT'), help=argparse.SUPPRESS)
    args=ap.parse_args()
    if args.extract:
        print(json.dumps(extract(*args.extract), ensure_ascii=False)); return
    data=generate(args.split)
    if args.json_path: args.json_path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    if args.markdown_path: args.markdown_path.write_text(markdown(data),encoding='utf8')
    if not args.json_path and not args.markdown_path: print(markdown(data),end='')

if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Profile stopped: private plan unavailable or failed verification.',file=sys.stderr);sys.exit(1)
