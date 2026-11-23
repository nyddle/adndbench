"""Run an agent in the deterministic world; the model only sees observations."""
from __future__ import annotations

import argparse
from collections import deque
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

from benchmark.engine import ENGINE_VERSION, Game
from benchmark.scoring import score
from benchmark.probes import build_probes, public_probe, check_answer

SYSTEM_PROMPT = """You are playing a turn-based fantasy adventure. Complete the quests, explore,
and survive. You only know information you have observed. Each turn, answer with
exactly one JSON object and no other text. Actions: {"type":"move","direction":
"north|south|east|west"}, {"type":"talk"}, {"type":"search"},
{"type":"attack"}, {"type":"defend"}, {"type":"potion"}, {"type":"rest"}.
Use only exits listed in the current observation. Quest details may be given only
once, so remember them. The observation is supplied as JSON each turn. The
initial room is a refuge: rest there consumes one ration and restores 8 HP.
Search quest locations after accepting their quest. Attack deals 3 damage;
defend costs 1 HP and makes the next attack deal 5. Enemies deal 2 damage when
they survive an attack, when you use a potion in combat, or when you retreat.
A potion heals up to 6 HP. Defeated enemies do not retaliate."""


class BaselineAgent:
    """A deterministic, observation-only exploration baseline, not an oracle."""

    def __init__(self) -> None:
        self.graph: dict[str, dict[str, str]] = {}
        self.exits: dict[str, list[str]] = {}
        self.searched: set[tuple[str, int]] = set()
        self.refuge: str | None = None
        self.quests: dict[str, tuple[str, str]] = {}
        self.spoken_inventory: dict[str, str] = {}
        self.previous_room: str | None = None
        self.previous_direction: str | None = None

    def act(self, obs: dict[str, Any]) -> dict[str, Any]:
        room = obs["room"]
        if self.refuge is None:
            self.refuge = room
        match = re.search(r"найдите (.+?) в месте «(.+?)» и принесите мне сюда, в «(.+?)»", obs.get("message", ""))
        if match:
            item, target, giver = match.groups()
            self.quests[item] = (target, giver)
        self.graph.setdefault(room, {})
        self.exits[room] = list(obs.get("exits", []))
        if self.previous_room is not None and self.previous_direction and room != self.previous_room:
            opposite = {"north": "south", "south": "north", "east": "west", "west": "east"}
            self.graph[self.previous_room][self.previous_direction] = room
            self.graph[room][opposite[self.previous_direction]] = self.previous_room
        self.previous_room, self.previous_direction = None, None

        if obs.get("enemy"):
            if obs.get("potions", 0) and obs.get("hp", 0) <= obs.get("max_hp", 0) // 3:
                return {"type": "potion"}
            return {"type": "attack"}
        inventory = json.dumps(obs.get("inventory", []), sort_keys=True, ensure_ascii=False)
        if obs.get("npc") and self.spoken_inventory.get(room) != inventory:
            self.spoken_inventory[room] = inventory
            return {"type": "talk"}
        inventory_items = obs.get("inventory", [])
        search_key = (room, len(self.quests))
        if search_key not in self.searched:
            self.searched.add(search_key)
            return {"type": "search"}
        if room == self.refuge and obs.get("rations", 0) and obs.get("hp", 0) <= obs.get("max_hp", 0) // 2:
            return {"type": "rest"}

        # Route to a known quest giver or target using only the observed graph.
        targets = {giver if item in inventory_items else target
                   for item, (target, giver) in self.quests.items()
                   if self.spoken_inventory.get(giver) != inventory or item not in inventory_items}
        queue = deque([(room, None)])
        visited = {room}
        while queue:
            current, first = queue.popleft()
            if first and current in targets and ((current, len(self.quests)) not in self.searched
                    or self.spoken_inventory.get(current) != inventory and current in self.spoken_inventory):
                self.previous_room, self.previous_direction = room, first
                return {"type": "move", "direction": first}
            for direction, target in self.graph[current].items():
                if target not in visited:
                    visited.add(target)
                    queue.append((target, first or direction))

        # BFS through known rooms to the nearest unseen exit. No engine state is read.
        queue = deque([(room, None)])
        visited = {room}
        while queue:
            current, first = queue.popleft()
            for direction in self.exits[current]:
                target = self.graph[current].get(direction)
                if target is None:
                    chosen = first or direction
                    self.previous_room, self.previous_direction = room, chosen
                    return {"type": "move", "direction": chosen}
                if target not in visited:
                    visited.add(target)
                    queue.append((target, first or direction))
        # A complete exploration can still require revisiting quest givers after
        # collecting an item. Cycle known rooms until the turn budget is exhausted.
        if self.exits[room]:
            direction = self.exits[room][0]
            self.previous_room, self.previous_direction = room, direction
            return {"type": "move", "direction": direction}
        return {"type": "search"}


class OpenAICompatibleAgent:
    """Minimal chat-completions client; credentials are never included in traces."""

    def __init__(self, model: str, api_url: str, api_key: str, *,
                 temperature: float = 0, context_turns: int | None = None,
                 timeout: float = 90, system_prompt: str | None = None) -> None:
        if not api_key:
            raise ValueError("Set OPENAI_API_KEY in the environment")
        if context_turns is not None and context_turns < 1:
            raise ValueError("context_turns must be at least 1")
        self.model, self.api_url, self.api_key = model, api_url, api_key
        self.temperature, self.context_turns, self.timeout = temperature, context_turns, timeout
        self._system_prompt_explicit = system_prompt is not None
        self.system_prompt = SYSTEM_PROMPT if system_prompt is None else system_prompt
        self.history: list[dict[str, str]] = []
        self.last_response: str | None = None

    def _complete(self, messages: list[dict[str, str]]) -> str:
        payload = {"model": self.model, "temperature": self.temperature, "messages": messages}
        request = urllib.request.Request(self.api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Response content is not a string")
            return content
        except urllib.error.HTTPError as exc:
            # Providers may echo request headers or prompt content in error bodies.
            raise RuntimeError(f"Model API returned HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError("Could not reach the model API") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise RuntimeError("Model API returned an invalid chat-completions response") from None

    def _messages(self, history: list[dict[str, str]]) -> list[dict[str, str]]:
        if self.context_turns is not None:
            history = history[-(2 * self.context_turns - 1):]
        return [{"role": "system", "content": self.system_prompt}, *history]

    def act(self, obs: dict[str, Any]) -> dict[str, Any]:
        self.history.append({"role": "user", "content": json.dumps(obs, ensure_ascii=False, sort_keys=True)})
        content = self._complete(self._messages(self.history))
        self.last_response = content
        self.history.append({"role": "assistant", "content": content})
        try:
            action = json.loads(content)
            if not isinstance(action, dict):
                raise ValueError
            return action
        except (ValueError, TypeError):
            # Invalid JSON is a model mistake, counted by the environment.
            return {"type": "invalid"}

    def answer_probe(self, final_observation: dict[str, Any], question: dict[str, str]) -> str | None:
        # Each probe is independent: earlier questions and answers do not prime later ones.
        text = ("Game over. Final observation: " + json.dumps(final_observation, ensure_ascii=False, sort_keys=True)
                + "\nAnswer this recall question using exactly a JSON object with id and answer string: "
                + json.dumps(question, ensure_ascii=False, sort_keys=True))
        content = self._complete(self._messages([*self.history, {"role": "user", "content": text}]))
        try:
            answer = json.loads(content)
            if isinstance(answer, dict) and answer.get("id") == question["id"] and isinstance(answer.get("answer"), str):
                return answer["answer"]
        except (ValueError, TypeError):
            pass
        return None


def run_episode(seed: int, agent: Any, max_turns: int | None = None, *,
                probes: bool = True, scenario: str = "classic") -> dict[str, Any]:
    """Return a local trace and outcomes; never pass hidden game state to agent."""
    if scenario == "classic":
        game = Game(seed, max_turns=120 if max_turns is None else max_turns)
        scenario_prompt = SYSTEM_PROMPT
    elif scenario == "realms":
        from benchmark.realms import DEFAULT_MAX_TURNS, Game as RealmsGame, SYSTEM_PROMPT as scenario_prompt
        game = RealmsGame(seed, max_turns=DEFAULT_MAX_TURNS if max_turns is None else max_turns)
    else:
        raise ValueError(f"Unknown scenario: {scenario}")
    if isinstance(agent, OpenAICompatibleAgent) and not agent._system_prompt_explicit:
        agent.system_prompt = scenario_prompt
    obs = game.observe()
    trace = []
    while not obs.get("done", False):
        action = agent.act(obs)
        entry = {"observation": obs, "action": action}
        if isinstance(getattr(agent, "last_response", None), str):
            entry["model_response"] = agent.last_response
        trace.append(entry)
        obs = game.step(action)
    result = game.result()
    evaluated_probes = []
    if probes and hasattr(agent, "answer_probe"):
        counts: dict[str, dict[str, int]] = {}
        for probe in build_probes(trace, obs, scenario=scenario):
            answer = agent.answer_probe(obs, public_probe(probe))
            correct = check_answer(probe, answer)
            count = counts.setdefault(probe["capability"], {"correct": 0, "total": 0})
            count["total"] += 1
            count["correct"] += int(correct)
            evaluated_probes.append({**probe, "model_answer": answer, "correct": correct})
        result["probe_results"] = counts
    return {"seed": seed, "scenario": scenario, "score": score(result), "trace": trace,
            "final_observation": obs, "result": result, "probes": evaluated_probes}


def aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Macro-average each available per-seed metric; report its denominator."""
    paths = {
        "quest_completion_rate": ("outcomes", "quests", "completion_rate"),
        "exploration_coverage": ("outcomes", "exploration", "coverage"),
        "valid_action_rate": ("outcomes", "actions", "valid_rate"),
        "navigation_recall": ("capability_scores", "navigation_recall"),
        "quest_memory": ("capability_scores", "quest_memory"),
        "spatial_reasoning": ("capability_scores", "spatial_reasoning"),
        "tactics": ("capability_scores", "tactics"),
        "strategy": ("capability_scores", "strategy"),
    }
    aggregate = {}
    for name, path in paths.items():
        values = []
        for run in runs:
            value: Any = run.get("score", {})
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(value)
        aggregate[name] = {"mean": sum(values) / len(values) if values else None,
                           "seeds_with_data": len(values)}
    # A side quest is optional in realms, so total quest completion is not the
    # success rate for the main objective. Exclude unknown/unfinished results.
    main_values = []
    for run in runs:
        value = run.get("score", {}).get("outcomes", {}).get("quests", {}).get("main_completed")
        if isinstance(value, bool):
            main_values.append(int(value))
    if main_values:
        aggregate["main_quest_success"] = {
            "mean": sum(main_values) / len(main_values),
            "seeds_with_data": len(main_values),
        }
    return aggregate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate an agent on deterministic fantasy adventures")
    parser.add_argument("--agent", choices=("baseline", "openai"), default="baseline")
    parser.add_argument("--scenario", choices=("classic", "realms"), default="classic",
                        help="Scenario to run (default: classic)")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--max-turns", type=int, help="Override scenario turn limit (classic: 120; realms: 300)")
    parser.add_argument("--model", help="Model name for the OpenAI-compatible chat-completions API")
    parser.add_argument("--api-url", default=os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions"), help="Complete chat-completions endpoint URL")
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--context-turns", type=int, help="Number of observations in the model's context (default: full history)")
    parser.add_argument("--no-probes", action="store_true", help="Skip post-game recall questions")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--output", help="Write JSON results to this path (default: stdout)")
    args = parser.parse_args(argv)
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("--seeds must not contain duplicates")
    if (args.max_turns is not None and args.max_turns < 1) or args.timeout <= 0:
        parser.error("--max-turns and --timeout must be positive")
    if args.context_turns is not None and args.context_turns < 1:
        parser.error("--context-turns must be positive")
    if args.agent == "openai" and not args.model:
        parser.error("--model is required with --agent openai")
    if args.scenario == "realms":
        from benchmark.realms import DEFAULT_MAX_TURNS, ENGINE_VERSION as scenario_version, SYSTEM_PROMPT as scenario_prompt
        max_turns = DEFAULT_MAX_TURNS if args.max_turns is None else args.max_turns
    else:
        scenario_version, scenario_prompt = ENGINE_VERSION, SYSTEM_PROMPT
        max_turns = 120 if args.max_turns is None else args.max_turns
    runs = []
    try:
        for seed in args.seeds:
            if args.agent == "baseline":
                if args.scenario == "realms":
                    from benchmark.realms_baseline import RealmsBaselineAgent
                    agent = RealmsBaselineAgent()
                else:
                    agent = BaselineAgent()
            else:
                agent = OpenAICompatibleAgent(args.model, args.api_url,
                    os.getenv("OPENAI_API_KEY", ""), temperature=args.temperature,
                    context_turns=args.context_turns, timeout=args.timeout,
                    system_prompt=scenario_prompt)
            runs.append(run_episode(seed, agent, max_turns=max_turns, probes=not args.no_probes, scenario=args.scenario))
        report = {"engine_version": scenario_version, "scenario": args.scenario, "max_turns": max_turns,
                  "aggregate": aggregate_runs(runs),
                  "agent": args.agent, "model": args.model if args.agent == "openai" else None,
                  "temperature": args.temperature if args.agent == "openai" else None,
                  "context_turns": args.context_turns, "probes_enabled": not args.no_probes and args.agent == "openai", "runs": runs}
        output = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output + "\n")
        else:
            print(output)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
