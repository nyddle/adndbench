#!/usr/bin/env python3
"""Publish only whitelisted aggregates/episode facts, never private plans or traces.

Run from repository root after refreshing behavior-profile snapshots:
    python3 pages/update_dashboard_data.py [--extra PATH ...]
Each extra file must be a public-safe behavior-profile JSON with a scenarios list.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = [ROOT / 'docs/behavior-profile-results.json',
            ROOT / 'docs/behavior-profile-holdout.json']
SCENARIO_KEYS = ('axis', 'level', 'split', 'measurement', 'fixed_case', 'effort',
                 'context_turns', 'cli_version', 'max_actions', 'label', 'execution_note')
CONFIG_KEYS = ('combat', 'max_turns', 'memory', 'navigation', 'party', 'quests')
RESULT_KEYS = ('terminal_reason', 'turns', 'invalid_actions', 'completed_tasks',
               'rooms_visited', 'rooms_total', 'relic', 'combat_status', 'combat_rounds',
               'unlocked', 'recruited_count', 'selected', 'hero_hp', 'damage_dealt',
               'healing', 'charges_used')
ALLOWED_MODELS = {'gpt-6-luna', 'gpt-6.2-sol', 'gpt-6.2-astra'}


def sanitize(source):
    if not isinstance(source, dict) or not isinstance(source.get('scenarios'), list):
        raise ValueError('Expected object with scenarios list')
    out = []
    for scenario in source['scenarios']:
        episodes = []
        for episode in scenario.get('episodes', []):
            if episode.get('model') not in ALLOWED_MODELS:
                continue
            result = episode.get('result') or {}
            components = episode.get('components') or {}
            progress = components.get('progress') or {}
            efficiency = components.get('efficiency') or {}
            score_breakdown = None
            if episode.get('score_version') == 'radical-efficiency-score-0.2.0':
                score_breakdown = {
                    'progress': {k: progress[k] for k in ('weight', 'earned') if k in progress},
                    'efficiency': {k: efficiency[k] for k in ('weight', 'earned', 'turns', 'turn_limit') if k in efficiency},
                }
            episodes.append({'world': episode.get('world'), 'model': episode['model'],
                             'status': episode.get('status'),
                             'result': {k: result[k] for k in RESULT_KEYS if k in result},
                             'score': episode.get('score'),
                             'score_version': episode.get('score_version'),
                             'score_breakdown': score_breakdown})
        clean = {key: scenario[key] for key in SCENARIO_KEYS if key in scenario}
        config = scenario.get('game_config')
        clean['game_config'] = ({k: config[k] for k in CONFIG_KEYS if k in config}
                                if isinstance(config, dict) else None)
        clean['episodes'] = episodes
        out.append(clean)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--extra', action='append', type=Path, default=[])
    args = parser.parse_args()
    missing = [path for path in DEFAULTS + args.extra if not path.is_file()]
    if missing:
        parser.error('Profile JSON is missing. Generate local dev and holdout profiles first; see docs/behavior-profile.md. Existing model-data.js was not changed.')
    scenarios = []
    for path in DEFAULTS + args.extra:
        scenarios.extend(sanitize(json.loads(path.read_text(encoding='utf-8'))))
    # Escape HTML-sensitive characters because this is a standalone script file.
    data = json.dumps({'updated_at': datetime.now(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M МСК'),
                       'scenarios': scenarios}, ensure_ascii=False, separators=(',', ':'))
    data = data.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    (ROOT / 'pages/model-data.js').write_text('window.ADND_MODEL_DATA=' + data + ';\n', encoding='utf-8')
    print(f'Exported {len(scenarios)} isolated scenario snapshots.')


if __name__ == '__main__':
    main()
