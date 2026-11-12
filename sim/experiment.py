"""Run many games headlessly, in parallel, with a balanced seating design.

    python sim/experiment.py --games 27 --workers 9 --out results/run1

Each game gets its own state file, usage log and console log under --out.
Re-running the same command resumes: finished games are skipped and
half-played games continue from where they stopped.

Design: games come in blocks of nine. Within a block every model sits in
every seat (character) exactly once and starts with the money exactly once,
so a model's results are not tied to one character's name or backstory.
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import json
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List

SIM_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SIM_DIR)
sys.path.insert(0, SIM_DIR)

MAX_STEPS = 40  # a nine-player game needs 14 steps (7 discussions + 7 votes)


def build_schedule(model_ids: List[str], seat_ids: List[str], games: int, seed: int) -> List[Dict[str, Any]]:
    """Latin-square seating: game g of a block shifts the model order by g seats."""
    rng = random.Random(seed)
    n = len(seat_ids)
    schedule: List[Dict[str, Any]] = []
    block: Dict[str, Any] = {}
    for g in range(games):
        if g % n == 0:
            block = {
                "models": rng.sample(model_ids, n),
                "shifts": rng.sample(range(n), n),
                "holders": rng.sample(model_ids, n),
            }
        shift = block["shifts"][g % n]
        assignment = {seat_ids[i]: block["models"][(i + shift) % n] for i in range(n)}
        holder_model = block["holders"][g % n]
        holder_seat = next(seat for seat, model in assignment.items() if model == holder_model)
        schedule.append(
            {
                "game_id": f"game_{g:03d}",
                "seed": seed * 100_000 + g,
                "assignment": assignment,
                "money_holder": holder_seat,
            }
        )
    return schedule


def spent(out_dir: str) -> float:
    """Total API cost logged so far for this run, in dollars."""
    total = 0.0
    for path in glob.glob(os.path.join(out_dir, "usage", "*.jsonl")):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    total += json.loads(line).get("cost") or 0
                except json.JSONDecodeError:
                    pass
    return total


def play_game(spec: Dict[str, Any], out_dir: str, mock: bool, budget: float) -> Dict[str, Any]:
    game_id = spec["game_id"]
    state_file = os.path.join(out_dir, "games", f"{game_id}.json")
    os.environ["SIM_STATE_PATH"] = state_file
    os.environ["SIM_USAGE_PATH"] = os.path.join(out_dir, "usage", f"{game_id}.jsonl")
    if mock:
        os.environ["SIM_MOCK"] = "1"
    os.makedirs(os.path.join(out_dir, "logs"), exist_ok=True)

    import controller
    from storage import load_state

    started = time.time()
    with open(os.path.join(out_dir, "logs", f"{game_id}.log"), "a", encoding="utf-8") as log:
        with contextlib.redirect_stdout(log):
            random.seed(spec["seed"])
            state = load_state() if os.path.exists(state_file) else None
            if state is None or not state.players:
                state = controller.init_game(
                    assignment=spec["assignment"],
                    money_holder=spec["money_holder"],
                    meta={"game_id": game_id, "seed": spec["seed"], "initial_money_holder": spec["money_holder"]},
                )
            steps = 0
            while not state.game_over and steps < MAX_STEPS:
                if spent(out_dir) > budget:
                    print(f"[budget] stopping: spend passed ${budget}")
                    break
                state = controller.start_vote() if state.discussion_done else controller.run_round()
                steps += 1
                log.flush()
    return {
        "game_id": game_id,
        "finished": state.game_over,
        "winner_model": state.players[state.winner].model_id if state.winner else "",
        "minutes": round((time.time() - started) / 60, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--games", type=int, default=9)
    parser.add_argument("--workers", type=int, default=6, help="games played at the same time")
    parser.add_argument("--out", default="results/run1")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--max-messages", type=int, default=10, help="messages one player may send per round")
    parser.add_argument("--budget", type=float, default=float("inf"), help="stop starting new rounds once the run has cost this many dollars")
    parser.add_argument("--mock", action="store_true", help="use fake offline players (free, for testing)")
    args = parser.parse_args()

    from controller import MODELS_PATH, load_players_config
    from agents import load_model_configs

    os.environ["SIM_MAX_MESSAGES"] = str(args.max_messages)
    out_dir = os.path.join(REPO_ROOT, args.out) if not os.path.isabs(args.out) else args.out
    os.makedirs(out_dir, exist_ok=True)
    seat_ids = [p["id"] for p in load_players_config()]
    model_ids = list(load_model_configs(MODELS_PATH).keys())
    if len(model_ids) != len(seat_ids):
        sys.exit(f"Need one model per seat: {len(model_ids)} models, {len(seat_ids)} seats.")
    if not args.mock and not os.getenv("OPENROUTER_API_KEY"):
        sys.exit("OPENROUTER_API_KEY is not set. Put it in .env at the repo root, or use --mock.")

    schedule = build_schedule(model_ids, seat_ids, args.games, args.seed)
    with open(os.path.join(out_dir, "schedule.json"), "w", encoding="utf-8") as f:
        json.dump(schedule, f, indent=2)

    todo = []
    for spec in schedule:
        path = os.path.join(out_dir, "games", f"{spec['game_id']}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                if json.load(f).get("game_over"):
                    continue
        todo.append(spec)
    print(f"{len(schedule) - len(todo)} of {len(schedule)} games already finished; playing {len(todo)}.")

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(play_game, spec, out_dir, args.mock, args.budget): spec for spec in todo}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                result = future.result()
                print(f"{result['game_id']}: finished={result['finished']} winner={result['winner_model']} ({result['minutes']} min)")
            except Exception as exc:
                print(f"{spec['game_id']}: FAILED {type(exc).__name__}: {exc}")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
