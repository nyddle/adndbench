"""Resumable paired calibration with private local checkpoints.

See docs/calibration.md for the plan schema and limitations.  Only player
observations (and, optionally, fixed public probes) are sent to the provider.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from benchmark.expedition import Game, ENGINE_VERSION, SYSTEM_PROMPT
from benchmark.runner import OpenAICompatibleAgent
from benchmark.scoring import score

HARNESS_VERSION = 'calibration-0.1.0'
ACTION_POLICY = 'exact-schema-canonical-history-1'
STRICT_PROMPT = SYSTEM_PROMPT + '''\nStrict action protocol: return one JSON object only. For move use exactly
{"type":"move","direction":"north|south|east|west|up|down"}; for ask exactly
{"type":"ask","topic":"one current visible topic ID"}; for ability exactly
{"type":"ability","ability":"one current visible ability ID"}; for talk, search,
attack, defend, potion, rest use only {"type":"ACTION"}. Extra keys or values
outside the schema are invalid actions. Your action history contains only the
canonical action, or {"type":"invalid"} for any schema-invalid response.'''
DEFAULT_CONFIG = {'map_size': 6, 'quest_difficulty': 'easy', 'combat_difficulty': 'easy',
                  'character_class': 'generalist', 'npc_difficulty': 'easy',
                  'map_topology': 'mixed', 'terrain_diversity': 2, 'enemy_count': None}
TERMINAL = {'completed', 'death', 'turn_limit'}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _code_fingerprint() -> str:
    """Refuse to silently resume against a different implementation."""
    folder = Path(__file__).resolve().parent
    sources = [folder / 'expedition.py', folder / 'runner.py', folder / 'scoring.py',
               folder / 'probes.py', folder / 'calibration.py']
    sources.extend(sorted((folder / 'difficulty').glob('*.py')))
    fixed = folder / 'fixed_probes.py'
    if fixed.exists():
        sources.append(fixed)
    h = hashlib.sha256()
    for path in sources:
        h.update(str(path.relative_to(folder)).encode('utf-8') + b'\0')
        h.update(path.read_bytes() + b'\0')
    return h.hexdigest()


def _endpoint(url: str, key: str) -> str:
    if not isinstance(url, str) or not url:
        raise ValueError('API URL is required')
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or (key and key in url)):
        raise ValueError('API URL must have no credentials, query or fragment')
    if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('non-local API URL must use HTTPS')
    return url


def validate_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one-axis plan and expand default parameters without model calls."""
    if not isinstance(plan, Mapping):
        raise ValueError('plan must be a JSON object')
    allowed = {'models', 'seeds', 'repeats', 'max_turns', 'base_config', 'variants',
               'temperature', 'context_turns', 'max_tokens', 'timeout', 'fixed_probe_difficulty'}
    if set(plan) - allowed:
        raise ValueError('unknown plan field')
    models, seeds = plan.get('models'), plan.get('seeds')
    if not isinstance(models, list) or not models or any(not isinstance(m, str) or not m.strip() for m in models) or len(set(models)) != len(models):
        raise ValueError('models must be a nonempty list of unique names')
    if not isinstance(seeds, list) or not seeds or any(isinstance(s, bool) or not isinstance(s, (str, int)) or not str(s) for s in seeds) or len({str(s) for s in seeds}) != len(seeds):
        raise ValueError('seeds must be nonempty unique strings or integers')
    repeats, max_turns = plan.get('repeats', 1), plan.get('max_turns', 600)
    if type(repeats) is not int or repeats < 1 or type(max_turns) is not int or max_turns < 1:
        raise ValueError('repeats and max_turns must be positive integers')
    temp, window, max_tokens, timeout = (plan.get('temperature', 0), plan.get('context_turns'),
                                         plan.get('max_tokens'), plan.get('timeout', 90))
    if type(temp) not in (int, float) or not 0 <= temp <= 2:
        raise ValueError('temperature must be between 0 and 2')
    if window is not None and (type(window) is not int or window < 1):
        raise ValueError('context_turns must be a positive integer or null')
    if max_tokens is not None and (type(max_tokens) is not int or max_tokens < 1):
        raise ValueError('max_tokens must be a positive integer or null')
    if type(timeout) not in (int, float) or not 0 < timeout <= 3600:
        raise ValueError('timeout must be positive and at most 3600 seconds')
    probe_difficulty = plan.get('fixed_probe_difficulty')
    if probe_difficulty is not None and probe_difficulty not in ('easy', 'medium', 'hard'):
        raise ValueError('fixed_probe_difficulty must be easy, medium, hard or null')
    supplied = plan.get('base_config', {})
    if not isinstance(supplied, Mapping) or set(supplied) - set(DEFAULT_CONFIG):
        raise ValueError('base_config has unknown fields')
    base = {**DEFAULT_CONFIG, **supplied}
    variants = plan.get('variants', [{'name': 'control', 'changes': {}}])
    if not isinstance(variants, list) or not variants:
        raise ValueError('variants must be a nonempty list')
    names, normalized = set(), []
    for v in variants:
        if not isinstance(v, Mapping) or set(v) != {'name', 'changes'} or not isinstance(v['name'], str) or not v['name'].strip() or v['name'] in names:
            raise ValueError('variant needs a unique name and changes object')
        changes = v['changes']
        if not isinstance(changes, Mapping) or set(changes) - set(DEFAULT_CONFIG):
            raise ValueError('variant has unknown axis')
        if len(changes) > 1 or any(base[k] == x for k, x in changes.items()):
            raise ValueError('each variant must change exactly one value or be the control')
        if 'combat_difficulty' in changes and base['enemy_count'] is None:
            raise ValueError('fix base_config.enemy_count when comparing combat difficulty')
        names.add(v['name'])
        config = {**base, **changes}
        # Validate against the actual generator, not a second set of guessed ranges.
        Game(seeds[0], max_turns=max_turns, **config)
        normalized.append({'name': v['name'], 'changes': dict(changes), 'config': config})
    if sum(not v['changes'] for v in normalized) != 1:
        raise ValueError('one and only one unchanged control variant is required')
    return {'models': list(models), 'seeds': [str(s) for s in seeds], 'repeats': repeats,
            'max_turns': max_turns, 'temperature': temp, 'context_turns': window,
            'max_tokens': max_tokens, 'timeout': timeout, 'base_config': base,
            'variants': normalized, 'fixed_probe_difficulty': probe_difficulty}


def _allowed_action(action: Any, obs: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize actions and rule out arbitrary extra-field scratchpads."""
    if not isinstance(action, dict) or not isinstance(action.get('type'), str):
        return {'type': 'invalid'}
    kind = action['type']
    if kind in ('talk', 'search', 'attack', 'defend', 'potion', 'rest') and set(action) == {'type'}:
        return {'type': kind}
    if kind == 'move' and set(action) == {'type', 'direction'} and action.get('direction') in ('north', 'south', 'east', 'west', 'up', 'down'):
        return {'type': 'move', 'direction': action['direction']}
    if kind == 'ask' and set(action) == {'type', 'topic'}:
        topics = {x.get('id') for x in obs.get('topics', []) if isinstance(x, dict)}
        if isinstance(action.get('topic'), str) and action['topic'] in topics:
            return {'type': 'ask', 'topic': action['topic']}
    if kind == 'ability' and set(action) == {'type', 'ability'}:
        character = obs.get('character') or {}
        ids = {x.get('id') for x in character.get('abilities', []) if isinstance(x, dict)}
        if isinstance(action.get('ability'), str) and action['ability'] in ids:
            return {'type': 'ability', 'ability': action['ability']}
    return {'type': 'invalid'}


def _unique_action(raw: str, obs: Mapping[str, Any]) -> dict[str, Any]:
    """Reject duplicate JSON keys as well as fields outside the action schema."""
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    try:
        return _allowed_action(json.loads(raw, object_pairs_hook=unique_pairs), obs)
    except (ValueError, TypeError):
        return {'type': 'invalid'}


def _contains_secret(value: Any, key: str) -> bool:
    if not key:
        return False
    if isinstance(value, str):
        return key in value
    if isinstance(value, Mapping):
        return any(_contains_secret(k, key) or _contains_secret(v, key) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(v, key) for v in value)
    return False


def _write_private(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix='.checkpoint-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf8') as f:
            json.dump(payload, f, ensure_ascii=False, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class _Client(OpenAICompatibleAgent):
    def __init__(self, *args: Any, max_tokens: int | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.max_tokens = max_tokens
        self.last_usage: dict[str, int] | None = None

    def _complete(self, messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {'model': self.model, 'temperature': self.temperature, 'messages': messages}
        if self.max_tokens is not None:
            payload['max_tokens'] = self.max_tokens
        request = urllib.request.Request(self.api_url, data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.api_key})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
            content = data['choices'][0]['message']['content']
            if not isinstance(content, str):
                raise ValueError
            usage = data.get('usage')
            self.last_usage = {k: usage[k] for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                               if type(usage.get(k)) is int and usage[k] >= 0} if isinstance(usage, dict) else None
            return content
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'API HTTP {exc.code}') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError('API connection failed') from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise RuntimeError('Invalid API response') from None


def _client(spec: Mapping[str, Any], key: str) -> _Client:
    return _Client(spec['model'], spec['endpoint'], key, temperature=spec['temperature'],
                   context_turns=spec['context_turns'], timeout=spec['timeout'],
                   max_tokens=spec['max_tokens'], system_prompt=STRICT_PROMPT)


def _replay(spec: Mapping[str, Any], trace: list[dict[str, Any]], key: str) -> tuple[Game, _Client]:
    game = Game(spec['seed'], max_turns=spec['max_turns'], **spec['config'])
    if game.component_versions != spec['component_versions']:
        raise ValueError('component versions differ')
    client = _client(spec, key)
    for row in trace:
        obs = game.observe()
        if obs != row.get('observation') or _allowed_action(row.get('action'), obs) != row.get('action') and row.get('action') != {'type':'invalid'}:
            raise ValueError('checkpoint replay mismatch')
        client.history.append({'role':'user', 'content':json.dumps(obs, ensure_ascii=False, sort_keys=True)})
        client.history.append({'role':'assistant', 'content':_json(row['action'])})
        if game.step(row['action']) != row.get('next_observation'):
            raise ValueError('checkpoint replay mismatch')
    return game, client


def _game_spec(plan: Mapping[str, Any], endpoint: str, model: str, seed: str,
               variant: Mapping[str, Any], repeat: int, fingerprint: str) -> dict[str, Any]:
    game = Game(seed, max_turns=plan['max_turns'], **variant['config'])
    return {'harness_version': HARNESS_VERSION, 'action_policy': ACTION_POLICY,
            'engine_version': ENGINE_VERSION, 'component_versions': game.component_versions,
            'source_fingerprint': fingerprint, 'prompt_sha256': hashlib.sha256(STRICT_PROMPT.encode()).hexdigest(),
            'model': model, 'endpoint': endpoint, 'seed': seed, 'variant': variant['name'],
            'config': variant['config'], 'repeat': repeat, 'max_turns': plan['max_turns'],
            'temperature': plan['temperature'], 'context_turns': plan['context_turns'],
            'max_tokens': plan['max_tokens'], 'timeout': plan['timeout']}


def _load_checkpoint(path: Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return {'spec': dict(spec), 'status': 'pending', 'trace': []}
    obj = json.loads(path.read_text(encoding='utf8'))
    if not isinstance(obj, dict) or obj.get('spec') != spec or not isinstance(obj.get('trace'), list):
        raise ValueError('checkpoint metadata mismatch')
    return obj


def _run_game(path: Path, spec: Mapping[str, Any], key: str, *, resume: bool) -> dict[str, Any]:
    record = _load_checkpoint(path, spec)
    if record['status'] == 'completed':
        game, _ = _replay(spec, record['trace'], key)
        if not game.done or game.result() != record.get('result') or score(game.result()) != record.get('score'):
            raise ValueError('completed checkpoint mismatch')
        return record
    if record['status'] not in ('pending',) and not resume:
        return record
    try:
        game, client = _replay(spec, record['trace'], key)
    except (ValueError, KeyError, TypeError):
        # Preserve the existing checkpoint for investigation.
        raise ValueError('checkpoint replay failed') from None
    record['status'] = 'running'
    record.pop('error', None)
    _write_private(path, record)
    try:
        while not game.done:
            obs = game.observe()
            action = client.act(obs)
            raw = client.last_response
            if _contains_secret(raw, key) or _contains_secret(action, key):
                raise RuntimeError('Unsafe response')
            action = _unique_action(raw, obs)
            # The model only sees canonical prior actions, so invalid responses
            # cannot carry covert scratchpad data through extra fields.
            client.history[-1]['content'] = _json(action)
            after = game.step(action)
            record['trace'].append({'observation': obs, 'action': action, 'model_response': raw,
                                    'next_observation': after, 'usage': client.last_usage})
            _write_private(path, record)
        result = game.result()
        record.update(status='completed', result=result, score=score(result))
        _write_private(path, record)
    except Exception as exc:
        # Do not persist exception bodies or HTTP responses: they may contain
        # credentials, proxy diagnostics or user prompts.
        record['status'] = 'technical_error'
        record['error'] = {'type': type(exc).__name__}
        _write_private(path, record)
    return record


def _probe_spec(plan: Mapping[str, Any], endpoint: str, model: str, seed: str, repeat: int,
                probe: Mapping[str, Any], public: Mapping[str, Any], fingerprint: str) -> dict[str, Any]:
    return {'harness_version': HARNESS_VERSION, 'kind': 'fixed_probe', 'model': model,
            'endpoint': endpoint, 'seed': seed, 'repeat': repeat,
            'difficulty': plan['fixed_probe_difficulty'], 'probe_id': probe['id'],
            'capability': probe['capability'], 'public_sha256': _sha(public),
            'source_fingerprint': fingerprint, 'temperature': plan['temperature'],
            'context_turns': plan['context_turns'], 'max_tokens': plan['max_tokens'],
            'timeout': plan['timeout']}


def _run_probe(path: Path, spec: Mapping[str, Any], public: Mapping[str, Any],
               private: Mapping[str, Any], key: str, *, resume: bool) -> dict[str, Any]:
    from benchmark.fixed_probes import check_response
    if path.exists():
        record = json.loads(path.read_text(encoding='utf8'))
        if not isinstance(record, dict) or record.get('spec') != spec or _sha(public) != spec['public_sha256']:
            raise ValueError('probe checkpoint metadata mismatch')
        if record.get('status') == 'completed':
            if record.get('public') != public or check_response(private, record.get('model_response')) != record.get('correct'):
                raise ValueError('probe checkpoint mismatch')
            return record
        if not resume:
            return record
    else:
        record = {'spec': dict(spec), 'status': 'pending'}
    record['status'] = 'running'
    record.pop('error', None)
    _write_private(path, record)
    try:
        client = _client(spec, key)
        # Each question is stateless and gets only its own public context.  Do
        # not pass earlier questions, model answers, or private answer keys.
        messages = [
            {'role': 'system', 'content': 'Answer the question from the supplied context. Return exactly a JSON object with the supplied id and an answer string.'},
            {'role': 'user', 'content': _json(public)},
        ]
        response = client._complete(messages)
        if _contains_secret(response, key):
            raise RuntimeError('Unsafe response')
        record.update(status='completed', public=dict(public), model_response=response,
                      correct=check_response(private, response), usage=client.last_usage)
        _write_private(path, record)
    except Exception as exc:
        record['status'] = 'technical_error'
        record['error'] = {'type': type(exc).__name__}
        _write_private(path, record)
    return record


def summarize(plan: Mapping[str, Any], games: list[dict[str, Any]],
              fixed: list[dict[str, Any]]) -> dict[str, Any]:
    """Return terminal-only denominators and paired comparisons.

    Technical failures, incomplete work and skipped items are explicitly
    counted rather than treated as losses. Fixed probes are reported as cases
    and seed coverage, not as independent samples for confidence intervals.
    """
    game_groups = []
    for model in plan['models']:
        for variant in plan['variants']:
            group = [r for r in games if r['spec']['model'] == model and r['spec']['variant'] == variant['name']]
            terminal = [r for r in group if r.get('status') == 'completed'
                        and r.get('result', {}).get('terminal_reason') in TERMINAL]
            successes = sum(r['result']['terminal_reason'] == 'completed' for r in terminal)
            game_groups.append({'model': model, 'variant': variant['name'],
                'planned': len(plan['seeds']) * plan['repeats'], 'terminal': len(terminal),
                'missing_or_technical': len(plan['seeds']) * plan['repeats'] - len(terminal),
                'technical_errors': sum(r.get('status') == 'technical_error' for r in group),
                'successes': successes, 'deaths': sum(r['result']['terminal_reason'] == 'death' for r in terminal),
                'turn_limits': sum(r['result']['terminal_reason'] == 'turn_limit' for r in terminal),
                'turns': sum(r['result']['turns'] for r in terminal),
                'invalid_actions': sum(r['result']['invalid_actions'] for r in terminal),
                'rooms_visited': sum(r['result']['rooms_visited'] for r in terminal),
                'rooms_total': sum(r['result']['rooms_total'] for r in terminal),
                'side_quests_completed': sum(r['result']['side_quests_completed'] for r in terminal),
                'side_quests_total': sum(r['result']['side_quests_total'] for r in terminal),
                'success_rate_terminal': successes / len(terminal) if terminal else None})
    pairs = []
    control = next(v['name'] for v in plan['variants'] if not v['changes'])
    for model in plan['models']:
        for variant in plan['variants']:
            if variant['name'] == control:
                continue
            lookup = {(r['spec']['variant'], r['spec']['seed'], r['spec']['repeat']): r for r in games
                      if r['spec']['model'] == model and r.get('status') == 'completed'
                      and r.get('result', {}).get('terminal_reason') in TERMINAL}
            observed = []
            for seed in plan['seeds']:
                for repeat in range(plan['repeats']):
                    a, b = lookup.get((control, seed, repeat)), lookup.get((variant['name'], seed, repeat))
                    if a is not None and b is not None:
                        observed.append((a, b))
            both_win = [(a, b) for a, b in observed if a['result']['terminal_reason'] == b['result']['terminal_reason'] == 'completed']
            differences = [b['result']['turns'] - a['result']['turns'] for a, b in both_win]
            pairs.append({'model': model, 'control': control, 'variant': variant['name'],
                          'changed_axis': next(iter(variant['changes'])),
                          'planned_pairs': len(plan['seeds']) * plan['repeats'], 'paired_terminal': len(observed),
                          'excluded_missing_pairs': len(plan['seeds']) * plan['repeats'] - len(observed),
                          'control_success_variant_failure': sum(a['result']['terminal_reason'] == 'completed' and b['result']['terminal_reason'] != 'completed' for a, b in observed),
                          'control_failure_variant_success': sum(a['result']['terminal_reason'] != 'completed' and b['result']['terminal_reason'] == 'completed' for a, b in observed),
                          'both_success': len(both_win),
                          'mean_turn_delta_both_success': sum(differences) / len(differences) if differences else None})
    model_pairs = []
    lookup = {(r['spec']['model'], r['spec']['variant'], r['spec']['seed'], r['spec']['repeat']): r
              for r in games if r.get('status') == 'completed'
              and r.get('result', {}).get('terminal_reason') in TERMINAL}
    for index, first in enumerate(plan['models']):
        for second in plan['models'][index + 1:]:
            for variant in plan['variants']:
                name = variant['name']
                observed = [(lookup[(first, name, seed, repeat)], lookup[(second, name, seed, repeat)])
                            for seed in plan['seeds'] for repeat in range(plan['repeats'])
                            if (first, name, seed, repeat) in lookup and (second, name, seed, repeat) in lookup]
                model_pairs.append({'model_a': first, 'model_b': second, 'variant': name,
                    'planned_pairs': len(plan['seeds']) * plan['repeats'],
                    'paired_terminal': len(observed),
                    'excluded_missing_pairs': len(plan['seeds']) * plan['repeats'] - len(observed),
                    'a_success_b_failure': sum(a['result']['terminal_reason'] == 'completed' and b['result']['terminal_reason'] != 'completed' for a, b in observed),
                    'a_failure_b_success': sum(a['result']['terminal_reason'] != 'completed' and b['result']['terminal_reason'] == 'completed' for a, b in observed),
                    'both_success': sum(a['result']['terminal_reason'] == b['result']['terminal_reason'] == 'completed' for a, b in observed)})
    fixed_groups = []
    for model in plan['models']:
        categories = sorted({r['spec']['capability'] for r in fixed if r['spec']['model'] == model})
        for category in categories:
            group = [r for r in fixed if r['spec']['model'] == model and r['spec']['capability'] == category]
            completed = [r for r in group if r.get('status') == 'completed' and isinstance(r.get('correct'), bool)]
            fixed_groups.append({'model': model, 'capability': category, 'planned': len(group),
                                 'completed': len(completed), 'missing_or_technical': len(group) - len(completed),
                                 'correct': sum(r['correct'] for r in completed),
                                 'seed_repeat_coverage': len({(r['spec']['seed'], r['spec']['repeat']) for r in completed})})
    return {'harness_version': HARNESS_VERSION, 'engine_version': ENGINE_VERSION,
            'action_policy': ACTION_POLICY, 'game_groups': game_groups,
            'paired_with_control': pairs, 'paired_models': model_pairs, 'fixed_probes': fixed_groups,
            'notes': ['Success rates exclude incomplete and technical-error episodes; inspect their counts.',
                      'Fixed probe cases within a seed are correlated and use visible context.',
                      'Changing map size changes the generated world; comparisons are seed-paired, not location-identical.']}


def run_calibration(plan: Mapping[str, Any], *, api_url: str, api_key: str,
                    output_dir: str | Path, resume: bool = False,
                    summary_only: bool = False) -> dict[str, Any]:
    """Execute or inspect an experiment. No raw key is persisted or logged."""
    if summary_only and not api_key:
        api_key = 'summary-only-no-api-key'
    if not isinstance(api_key, str) or not api_key:
        raise ValueError('OPENAI_API_KEY is required')
    endpoint = _endpoint(api_url, api_key)
    if _contains_secret(plan, api_key):
        raise ValueError('plan must not contain the API key')
    normalized = validate_plan(plan)
    fingerprint = _code_fingerprint()
    folder = Path(output_dir)
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    if folder.stat().st_mode & 0o077:
        raise ValueError('output directory must be private (mode 0700)')
    games: list[dict[str, Any]] = []
    fixed: list[dict[str, Any]] = []
    lock_fd = os.open(folder / '.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another calibration is using this directory') from None
        for model in normalized['models']:
            for variant in normalized['variants']:
                for seed in normalized['seeds']:
                    for repeat in range(normalized['repeats']):
                        spec = _game_spec(normalized, endpoint, model, seed, variant, repeat, fingerprint)
                        path = folder / 'games' / (_sha(spec) + '.json')
                        if summary_only:
                            record = _load_checkpoint(path, spec)
                            if record['status'] == 'completed':
                                game, _ = _replay(spec, record['trace'], api_key)
                                if not game.done or game.result() != record.get('result') or score(game.result()) != record.get('score'):
                                    raise ValueError('completed checkpoint mismatch')
                        else:
                            record = _run_game(path, spec, api_key, resume=resume)
                        games.append(record)
        if normalized['fixed_probe_difficulty'] is not None:
            from benchmark.fixed_probes import generate_suite, public_probe
            for model in normalized['models']:
                for seed in normalized['seeds']:
                    for repeat in range(normalized['repeats']):
                        suite = generate_suite(seed, difficulty=normalized['fixed_probe_difficulty'])
                        for probe in suite:
                            public = public_probe(probe)
                            if _contains_secret(public, api_key):
                                raise ValueError('probe unexpectedly contains the API key')
                            spec = _probe_spec(normalized, endpoint, model, seed, repeat, probe, public, fingerprint)
                            path = folder / 'fixed' / (_sha(spec) + '.json')
                            if summary_only:
                                if path.exists():
                                    from benchmark.fixed_probes import check_response
                                    record = json.loads(path.read_text(encoding='utf8'))
                                    if record.get('spec') != spec or (record.get('status') == 'completed' and (record.get('public') != public or check_response(probe, record.get('model_response')) != record.get('correct'))):
                                        raise ValueError('probe checkpoint mismatch')
                                else:
                                    record = {'spec': spec, 'status': 'pending'}
                            else:
                                record = _run_probe(path, spec, public, probe, api_key, resume=resume)
                            fixed.append(record)
        summary = summarize(normalized, games, fixed)
        summary['source_fingerprint'] = fingerprint
        summary['fixed_probe_difficulty'] = normalized['fixed_probe_difficulty']
        summary['temperature'] = normalized['temperature']
        summary['context_turns'] = normalized['context_turns']
        summary['max_tokens'] = normalized['max_tokens']
        summary['endpoint'] = endpoint
        summary['variants'] = normalized['variants']
        summary['max_turns'] = normalized['max_turns']
        summary['repeats'] = normalized['repeats']
        summary['seed_count'] = len(normalized['seeds'])
        _write_private(folder / 'summary.json', summary)
        return summary
    finally:
        os.close(lock_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Run resumable, paired LLM calibration')
    parser.add_argument('--plan', required=True, help='Private JSON plan; do not commit held-out seeds')
    parser.add_argument('--output-dir', default='results/calibration', help='Private checkpoint directory')
    parser.add_argument('--api-url', default=os.getenv('OPENAI_API_URL', 'https://api.openai.com/v1/chat/completions'))
    parser.add_argument('--resume', action='store_true', help='Resume interrupted or technical-error items')
    parser.add_argument('--summary-only', action='store_true', help='Inspect results without API calls')
    args = parser.parse_args(argv)
    try:
        plan = json.loads(Path(args.plan).read_text(encoding='utf8'))
        summary = run_calibration(plan, api_url=args.api_url, api_key=os.getenv('OPENAI_API_KEY', ''),
                                  output_dir=args.output_dir, resume=args.resume, summary_only=args.summary_only)
        # Only aggregate data leaves the private directory; seed values and raw
        # model responses remain in owner-only per-item checkpoints.
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, ImportError, json.JSONDecodeError) as exc:
        # Never echo paths, URLs, provider messages or other potentially secret
        # exception bodies in terminal logs.
        print(f'Calibration failed: {type(exc).__name__}', file=__import__('sys').stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
