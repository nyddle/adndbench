"""Common, private-by-default episode harness for independent skill vectors.

The harness passes observations only, records canonical actions and replays them
before resumption. It makes no provider calls by itself. `decide` receives only
public history and must raise on a transport error; such errors are not losses.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable

VERSION = 'vector-harness-0.1.1'


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _terminal(obs: dict) -> bool:
    return bool(obs.get('done')) or obs.get('terminal_reason') is not None


def canonical_action(raw: Any, allowed: list[dict[str, str]]) -> dict[str, str]:
    """Return an exact public action or a fixed invalid sentinel, without scratchpads."""
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        return {'type': 'invalid'}
    # An arbitrary code is still an attempt at the lock: normalize unknown
    # codes to a guaranteed-wrong sentinel rather than allowing free retries.
    if (set(raw) == {'type', 'code'} and raw['type'] == 'unlock'
            and any(a.get('type') == 'unlock' for a in allowed)):
        return dict(raw) if raw in allowed else {'type': 'unlock', 'code': '__invalid_code__'}
    return dict(raw) if raw in allowed else {'type': 'invalid'}


def replay(game: Any, journal: list[dict], allowed_actions: Callable[[dict], list[dict]]) -> tuple[dict, list[dict]]:
    """Replay and validate a journal against current deterministic observations."""
    obs = game.observe()
    history = []
    for entry in journal:
        if _terminal(obs) or set(entry) != {'observation_sha256', 'action'}:
            raise ValueError('invalid replay entry')
        if _digest(obs) != entry['observation_sha256']:
            raise ValueError('observation mismatch during replay')
        action = entry['action']
        if action != canonical_action(action, allowed_actions(obs)) and action != {'type': 'invalid'}:
            raise ValueError('noncanonical replay action')
        history.append({'observation': copy.deepcopy(obs), 'action': copy.deepcopy(action)})
        obs = game.step(action)
    return obs, history


def advance(game: Any, journal: list[dict], decide: Callable[[list[dict], dict], Any],
            allowed_actions: Callable[[dict], list[dict]],
            checkpoint: Callable[[list[dict]], None] | None = None) -> dict:
    """Continue a deterministic episode; callback failures propagate unchanged.

    Checkpoint is invoked after an applied move, not before the external call.
    A network caller must separately record an in-flight marker before sending
    and must not automatically replay an uncertain request.
    """
    obs, history = replay(game, journal, allowed_actions)
    while not _terminal(obs):
        raw = decide(copy.deepcopy(history), copy.deepcopy(obs))
        action = canonical_action(raw, allowed_actions(obs))
        entry = {'observation_sha256': _digest(obs), 'action': action}
        history.append({'observation': copy.deepcopy(obs), 'action': copy.deepcopy(action)})
        obs = game.step(action)
        journal.append(entry)
        if checkpoint is not None:
            checkpoint(copy.deepcopy(journal))
    return {'result': game.result(), 'journal': journal}
