"""Paired control/memory game experiment built on the unchanged calibrator.

Memory is derived only from observations and canonical actions. The upstream
action protocol and gameplay remain unchanged. Output directories are private
and dedicated to one mode and one normalized plan.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from benchmark import calibration as cal

MEMORY_VERSION = 'visible-map-notes-v2'
MAX_MEMORY_CHARS = 20000
MAX_NOTES = 40
MEMORY_DESCRIPTION = ('Only observed locations, traversed directed links, and observed dialogue/search messages. '
                      'Note turns are when messages were last observed; missing facts are unknown.')


def _location(obs: dict[str, Any]) -> tuple[str, str] | None:
    zone, room = obs.get('zone'), obs.get('room')
    return (zone, room) if isinstance(zone, str) and isinstance(room, str) else None


def _label(loc: tuple[str, str]) -> str:
    return f'{loc[0]} / {loc[1]}'


def visible_memory(history: list[dict[str, str]]) -> dict[str, Any]:
    """Compress public interaction history without reading the environment.

    Record exits and NPCs from observations, directed connections only when a
    move is visibly followed by a changed location, and dialogue/search
    messages after the corresponding action. A repeated note moves to the most
    recent position and retains its latest observed turn. Unknown connections
    stay unknown.
    """
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str]] = set()
    notes: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}
    previous_obs = None
    previous_action = None
    for message in history:
        try:
            content = json.loads(message['content'])
        except (ValueError, TypeError, KeyError):
            continue
        if not isinstance(content, dict):
            continue
        if message.get('role') == 'assistant':
            previous_action = content
            continue
        if message.get('role') != 'user':
            continue
        location = _location(content)
        if location is None:
            continue
        key = _label(location)
        entry = nodes.setdefault(key, {'location': key})
        exits = content.get('exits')
        if isinstance(exits, list) and all(isinstance(x, str) for x in exits):
            entry['exits'] = list(exits)
        npc = content.get('npc')
        if isinstance(npc, str) and npc:
            entry['npc'] = npc
        if previous_obs is not None and previous_action is not None:
            old_location = _location(previous_obs)
            kind = previous_action.get('type')
            direction = previous_action.get('direction')
            if (old_location is not None and old_location != location and kind == 'move'
                    and isinstance(direction, str)):
                edges.add((_label(old_location), direction, key))
            text = content.get('message')
            if kind in ('ask', 'talk', 'search') and isinstance(text, str) and text:
                item = {'location': key, 'after': str(kind), 'message': text}
                topic = previous_action.get('topic') if kind == 'ask' else None
                if isinstance(topic, str):
                    item['topic'] = topic
                else:
                    topic = None
                observed_turn = content.get('turn')
                if type(observed_turn) is int and observed_turn >= 0:
                    item['observed_turn'] = observed_turn
                identity = (key, kind, text, topic)
                notes.pop(identity, None)
                notes[identity] = item
        previous_obs, previous_action = content, None
    truncated_notes = max(0, len(notes) - MAX_NOTES)
    recent_notes = list(notes.values())[-MAX_NOTES:]
    memory = {'description': MEMORY_DESCRIPTION,
              'locations': [nodes[k] for k in sorted(nodes)],
              'connections': [{'from': a, 'direction': d, 'to': b} for a, d, b in sorted(edges)],
              'notes': recent_notes, 'omitted_notes': truncated_notes, 'omitted_locations': 0, 'omitted_connections': 0}
    # Bound context overhead deterministically; never claim the map is complete.
    def size() -> int:
        return len(json.dumps(memory, ensure_ascii=False, sort_keys=True))
    while size() > MAX_MEMORY_CHARS and memory['notes']:
        memory['notes'].pop(0)
        memory['omitted_notes'] += 1
    while size() > MAX_MEMORY_CHARS and memory['connections']:
        memory['connections'].pop()
        memory['omitted_connections'] += 1
    while size() > MAX_MEMORY_CHARS and memory['locations']:
        memory['locations'].pop()
        memory['omitted_locations'] += 1
    return memory


class MemoryClient(cal._Client):
    def _messages(self, history: list[dict[str, str]]) -> list[dict[str, str]]:
        messages = super()._messages(history)
        if not messages or messages[-1].get('role') != 'user':
            raise ValueError('current observation missing')
        observation = json.loads(messages[-1]['content'])
        if not isinstance(observation, dict) or 'visible_memory' in observation:
            raise ValueError('unexpected observation')
        observation['visible_memory'] = visible_memory(history)
        messages[-1] = {'role': 'user', 'content': json.dumps(observation, ensure_ascii=False, sort_keys=True)}
        return messages


@contextmanager
def experiment_protocol(mode: str):
    if mode not in ('control', 'memory'):
        raise ValueError('mode must be control or memory')
    original_fingerprint, original_spec, original_client = cal._code_fingerprint, cal._game_spec, cal._client
    def fingerprint():
        h = hashlib.sha256()
        h.update(original_fingerprint().encode('ascii') + b'\0')
        h.update(Path(__file__).read_bytes())
        return h.hexdigest()
    def game_spec(*args, **kwargs):
        spec = original_spec(*args, **kwargs)
        spec.update(experiment=MEMORY_VERSION, memory_mode=mode,
                    memory_prompt_sha256=hashlib.sha256(MEMORY_DESCRIPTION.encode('utf8')).hexdigest(),
                    memory_max_chars=MAX_MEMORY_CHARS, memory_max_notes=MAX_NOTES)
        return spec
    def client(spec, key):
        cls = MemoryClient if spec.get('memory_mode') == 'memory' else cal._Client
        if spec.get('memory_mode') != mode or spec.get('experiment') != MEMORY_VERSION:
            raise ValueError('experiment protocol mismatch')
        return cls(spec['model'], spec['endpoint'], key, temperature=spec['temperature'],
                   context_turns=spec['context_turns'], timeout=spec['timeout'],
                   max_tokens=spec['max_tokens'], system_prompt=cal.STRICT_PROMPT)
    cal._code_fingerprint, cal._game_spec, cal._client = fingerprint, game_spec, client
    try:
        yield
    finally:
        cal._code_fingerprint, cal._game_spec, cal._client = original_fingerprint, original_spec, original_client


def run(plan: dict[str, Any], *, mode: str, api_url: str, api_key: str,
        output_dir: str | Path, resume: bool = False, summary_only: bool = False) -> dict[str, Any]:
    normalized = cal.validate_plan(plan)
    if normalized['fixed_probe_difficulty'] is not None:
        raise ValueError('disable fixed probes for this game-only experiment')
    if not summary_only and (not isinstance(api_key, str) or not api_key):
        raise ValueError('OPENAI_API_KEY is required')
    if api_key and cal._contains_secret(plan, api_key):
        raise ValueError('plan must not contain the API key')
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.stat().st_mode & 0o077:
        raise ValueError('output directory must be private')
    # Independent lock protects the mode/plan manifest and entire run.
    fd = os.open(folder / '.experiment.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with experiment_protocol(mode):
            manifest = {'experiment': MEMORY_VERSION, 'mode': mode, 'plan': normalized,
                        'endpoint': cal._endpoint(api_url, api_key), 'source_fingerprint': cal._code_fingerprint()}
            path = folder / 'experiment.json'
            if path.exists():
                if json.loads(path.read_text(encoding='utf8')) != manifest:
                    raise ValueError('output directory belongs to a different experiment')
            else:
                if any(p.name != '.experiment.lock' for p in folder.iterdir()):
                    raise ValueError('refusing to mix with an existing output directory')
                if summary_only:
                    raise ValueError('experiment does not exist')
                cal._write_private(path, manifest)
            summary = cal.run_calibration(plan, api_url=api_url, api_key=api_key,
                                          output_dir=folder, resume=resume, summary_only=summary_only)
            return {'experiment': MEMORY_VERSION, 'mode': mode, 'summary': summary}
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--mode', required=True, choices=['control', 'memory', 'paired'])
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--api-url', default=os.getenv('OPENAI_API_URL'))
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--summary-only', action='store_true')
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding='utf8'))
    modes = ('control', 'memory') if args.mode == 'paired' else (args.mode,)
    results = [run(plan, mode=mode, api_url=args.api_url, api_key=os.getenv('OPENAI_API_KEY', ''),
                   output_dir=Path(args.output_dir) / mode if args.mode == 'paired' else args.output_dir,
                   resume=args.resume, summary_only=args.summary_only) for mode in modes]
    result = results if args.mode == 'paired' else results[0]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        # Do not expose exception text which could include sensitive data.
        print(f'Experiment failed: {type(exc).__name__}', file=__import__('sys').stderr)
        raise SystemExit(1)
