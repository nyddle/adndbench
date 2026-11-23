"""Versioned completion-and-efficiency score for replayed radical adventures.

Unlike the original progress-only score, this experimental measure allocates
15 points to the turns saved by a winning episode. It never replaces the
underlying terminal outcome and does not award speed to incomplete episodes.
"""
from __future__ import annotations
from typing import Any

from benchmark import radical_score

VERSION = 'radical-efficiency-score-0.2.0'
PROGRESS_WEIGHT = 85.0
EFFICIENCY_WEIGHT = 15.0


def score(game: Any, actions: list[dict], *, episode_status: str) -> dict[str, Any]:
    """Replay and score a recorded episode, respecting the runner's status.

    The caller must supply the recorded status; a game state alone cannot
    establish whether an API call or evaluator stopped the episode. Only
    ``completed`` records with a terminal in-game outcome receive a score.
    ``completed`` is a runner status and includes valid in-game defeats.
    """
    if not isinstance(episode_status, str) or not episode_status:
        raise ValueError('episode_status must be a nonempty runner status')
    original = radical_score.score(game, actions)  # Always validates replay.
    if episode_status == 'completed' and not original['complete_episode']:
        raise ValueError('completed record must have a terminal game outcome')
    terminal = episode_status == 'completed' and original['complete_episode']
    victory = terminal and original['win'] is True
    turns = game.turn
    turn_limit = game.max_turns
    if victory and not 0 < turns <= turn_limit:
        raise ValueError('invalid turn count for a winning episode')

    # The bound is the configured *in-game* turn limit, not the external
    # runner cap. These exploratory weights were chosen after the first dev
    # outcomes; evaluate them on new games without tuning to those games.
    fraction = max(0.0, 1.0 - turns / turn_limit) if victory else (0.0 if terminal else None)
    progress_earned = round(PROGRESS_WEIGHT * original['score'] / 100, 6) if terminal else None
    efficiency_earned = round(EFFICIENCY_WEIGHT * fraction, 6) if terminal else None
    return {
        'version': VERSION,
        'legacy_version': original['version'],
        'episode_status': episode_status,
        'terminal_reason': original['terminal_reason'] if terminal else None,
        'win': original['win'] if terminal else None,
        'score': round(progress_earned + efficiency_earned, 2) if terminal else None,
        'components': {
            'progress': {
                'weight': PROGRESS_WEIGHT,
                'legacy_score': original['score'] if terminal else None,
                'earned': progress_earned,
            },
            'efficiency': {
                'weight': EFFICIENCY_WEIGHT,
                'status': 'measured' if victory else ('not_eligible' if terminal else 'not_scored'),
                'turns': turns if terminal else None,
                'turn_limit': turn_limit,
                'fraction': fraction,
                'earned': efficiency_earned,
            },
        },
        'note': 'Experimental score; compare only identical game configuration and turn limit. '
                'Efficiency points require victory; technical or incomplete records have no score.',
    }
