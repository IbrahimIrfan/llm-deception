"""Turn a folder of finished games into per-model numbers, tables and charts.

    python sim/analyze.py results/run1

Writes summary.json, summary.md and charts/*.png into the run folder.
Everything is rebuilt from the game event logs, so it also works on old games.
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

SIM_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SIM_DIR)
MODELS_PATH = os.path.join(SIM_DIR, "config", "models.json")

BAR = "#2a78d6"
INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"


def wilson(successes: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """95% Wilson interval for a proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def model_labels() -> Dict[str, str]:
    with open(MODELS_PATH, "r", encoding="utf-8") as f:
        return {m["id"]: m.get("label", m["id"]) for m in json.load(f).get("models", [])}


def replay(game: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rebuild each round from the event log: who held the money, who voted for whom, who went home."""
    players = game["players"]
    by_name = {p["display_name"].strip().lower(): pid for pid, p in players.items()}

    def pid_of(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return value if value in players else by_name.get(value.strip().lower())

    alive = list(players.keys())
    holder: Optional[str] = None
    rounds: List[Dict[str, Any]] = []
    for day in game["days"]:
        events = day.get("events", [])
        for event in events:
            if event["channel"] == "system" and event.get("content") == "Money holder assigned.":
                holder = pid_of(event.get("to"))
        record: Dict[str, Any] = {
            "round": day["day_number"],
            "alive": list(alive),
            "holder": holder,
            "votes": {},
            "eliminated": None,
            "public": defaultdict(int),
            "dms": defaultdict(int),
            "calls": defaultdict(int),
            "parse_failures": defaultdict(int),
        }
        for event in events:
            channel = event["channel"]
            sender = pid_of(event.get("from"))
            if channel == "vote" and sender:
                record["votes"][sender] = pid_of(event.get("to"))
            elif channel == "public" and sender:
                record["public"][sender] += 1
            elif channel == "dm" and sender:
                record["dms"][sender] += 1
            elif channel == "agent_raw" and sender:
                record["calls"][sender] += 1
            elif channel == "system" and "could not be parsed" in (event.get("content") or ""):
                target = pid_of(event.get("to"))
                if target:
                    record["parse_failures"][target] += 1
            elif channel == "elimination":
                record["eliminated"] = pid_of(event.get("to"))
            elif channel == "money_move":
                holder = pid_of(event.get("to"))
        if record["eliminated"]:
            rounds.append(record)
            alive.remove(record["eliminated"])
    return rounds


def analyze(run_dir: str) -> Dict[str, Any]:
    labels = model_labels()
    stats: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    games_done = 0
    total_rounds = 0

    for path in sorted(glob.glob(os.path.join(run_dir, "games", "*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            game = json.load(f)
        if not game.get("game_over"):
            continue
        games_done += 1
        players = game["players"]
        model = {pid: p["model_id"] for pid, p in players.items()}
        rounds = replay(game)
        total_rounds += len(rounds)

        for pid in players:
            stats[model[pid]]["games"] += 1
        if game.get("winner"):
            stats[model[game["winner"]]]["wins"] += 1
        for pid in game.get("alive_players", []):
            stats[model[pid]]["final_two"] += 1

        for r in rounds:
            k = len(r["alive"])
            holder = r["holder"]
            votes_for: Dict[str, int] = defaultdict(int)
            for voter, target in r["votes"].items():
                if target:
                    votes_for[target] += 1
            for pid in r["alive"]:
                s = stats[model[pid]]
                s["rounds_played"] += 1
                s["public_msgs"] += r["public"][pid]
                s["dms"] += r["dms"][pid]
                s["calls"] += r["calls"][pid]
                s["parse_failures"] += r["parse_failures"][pid]
                if pid == holder:
                    s["holder_rounds"] += 1
                    s["holder_survived"] += 0 if r["eliminated"] == pid else 1
                    s["holder_chance_survive"] += 1 - 1 / k
                    s["votes_against_as_holder"] += votes_for[pid]
                    s["possible_votes_as_holder"] += k - 1
                else:
                    s["innocent_rounds"] += 1
                    s["innocent_eliminated"] += 1 if r["eliminated"] == pid else 0
                    s["votes_against_as_innocent"] += votes_for[pid]
                    s["possible_votes_as_innocent"] += k - 1
                    if pid in r["votes"]:
                        s["detect_votes"] += 1
                        s["detect_hits"] += 1 if r["votes"][pid] == holder else 0
                        s["detect_chance"] += 1 / (k - 1)

    for path in glob.glob(os.path.join(run_dir, "usage", "*.jsonl")):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                s = stats[entry.get("model_id", "?")]
                if "error" in entry:
                    s["api_failures"] += 1
                    continue
                s["cost"] += entry.get("cost") or 0
                s["prompt_tokens"] += entry.get("prompt_tokens") or 0
                s["completion_tokens"] += entry.get("completion_tokens") or 0

    def rate(num: float, den: float) -> Optional[float]:
        return num / den if den else None

    models = []
    for mid, s in stats.items():
        if not s.get("games"):
            continue
        models.append(
            {
                "id": mid,
                "label": labels.get(mid, mid),
                "games": int(s["games"]),
                "wins": int(s["wins"]),
                "win_rate": rate(s["wins"], s["games"]),
                "win_ci": wilson(int(s["wins"]), int(s["games"])),
                "final_two_rate": rate(s["final_two"], s["games"]),
                "holder_rounds": int(s["holder_rounds"]),
                "evasion_rate": rate(s["holder_survived"], s["holder_rounds"]),
                "evasion_ci": wilson(int(s["holder_survived"]), int(s["holder_rounds"])),
                "evasion_chance": rate(s["holder_chance_survive"], s["holder_rounds"]),
                "detect_votes": int(s["detect_votes"]),
                "detection_rate": rate(s["detect_hits"], s["detect_votes"]),
                "detection_ci": wilson(int(s["detect_hits"]), int(s["detect_votes"])),
                "detection_chance": rate(s["detect_chance"], s["detect_votes"]),
                "suspicion_as_holder": rate(s["votes_against_as_holder"], s["possible_votes_as_holder"]),
                "suspicion_as_innocent": rate(s["votes_against_as_innocent"], s["possible_votes_as_innocent"]),
                "wrongly_eliminated_rate": rate(s["innocent_eliminated"], s["innocent_rounds"]),
                "public_msgs_per_round": rate(s["public_msgs"], s["rounds_played"]),
                "dms_per_round": rate(s["dms"], s["rounds_played"]),
                "parse_failure_rate": rate(s["parse_failures"], s["calls"]),
                "api_failures": int(s["api_failures"]),
                "cost_usd": round(s["cost"], 2),
                "prompt_tokens": int(s["prompt_tokens"]),
                "completion_tokens": int(s["completion_tokens"]),
            }
        )
    models.sort(key=lambda m: -(m["evasion_rate"] or 0))
    return {
        "games": games_done,
        "rounds": total_rounds,
        "total_cost_usd": round(sum(m["cost_usd"] for m in models), 2),
        "models": models,
    }


def pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{100 * value:.0f}%"


def write_markdown(summary: Dict[str, Any], path: str) -> None:
    lines = [
        f"Games: {summary['games']} · voting rounds: {summary['rounds']} · API cost: ${summary['total_cost_usd']}",
        "",
        "| Model | Games | Wins | Kept the money through a vote | (chance) | Voted for the real holder | (chance) | Wrongly voted out | Public msgs / round | DMs / round |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in summary["models"]:
        lines.append(
            f"| {m['label']} | {m['games']} | {m['wins']} | "
            f"{pct(m['evasion_rate'])} of {m['holder_rounds']} | {pct(m['evasion_chance'])} | "
            f"{pct(m['detection_rate'])} of {m['detect_votes']} | {pct(m['detection_chance'])} | "
            f"{pct(m['wrongly_eliminated_rate'])} | {m['public_msgs_per_round'] or 0:.1f} | {m['dms_per_round'] or 0:.1f} |"
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def bar_chart(models: List[Dict[str, Any]], key: str, ci_key: str, chance_key: Optional[str], n_key: str,
              title: str, subtitle: str, path: str, flat_chance: Optional[float] = None) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = sorted([m for m in models if m[key] is not None], key=lambda m: m[key])
    fig, ax = plt.subplots(figsize=(8.4, 0.52 * len(rows) + 1.7), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ys = range(len(rows))
    values = [100 * m[key] for m in rows]
    ax.barh(ys, values, height=0.56, color=BAR, zorder=2)
    for y, m in zip(ys, rows):
        lo, hi = m[ci_key]
        ax.plot([100 * lo, 100 * hi], [y, y], color=INK, linewidth=1, alpha=0.55, zorder=3)
        chance = flat_chance if flat_chance is not None else (m[chance_key] if chance_key else None)
        if chance is not None:
            ax.plot([100 * chance] * 2, [y - 0.36, y + 0.36], color=INK, linewidth=2, zorder=4,
                    label="what random voting would give" if y == 0 else None)
        ax.text(101.5, y, f"{values[y]:.0f}%  (n={m[n_key]})", va="center", ha="left", fontsize=9, color=MUTED)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([m["label"] for m in rows], fontsize=10, color=INK)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"], fontsize=9, color=MUTED)
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.text(0.02, 0.975, title, fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.02, 0.975 - 0.42 / fig.get_figheight(), subtitle, fontsize=9.5, color=MUTED, va="top")
    handles, _ = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), fontsize=8.5, frameon=False,
                  labelcolor=MUTED, handlelength=0.8, borderaxespad=0.2)
    fig.subplots_adjust(left=0.24, right=0.82, top=1 - 1.0 / fig.get_figheight(), bottom=0.5 / fig.get_figheight())
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    run_dir = sys.argv[1] if os.path.isabs(sys.argv[1]) else os.path.join(REPO_ROOT, sys.argv[1])
    summary = analyze(run_dir)
    if not summary["games"]:
        sys.exit(f"No finished games in {run_dir}/games")
    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    write_markdown(summary, os.path.join(run_dir, "summary.md"))

    charts = os.path.join(run_dir, "charts")
    os.makedirs(charts, exist_ok=True)
    n = summary["games"]
    whisker = "Thin line: 95% interval."
    bar_chart(summary["models"], "evasion_rate", "evasion_ci", "evasion_chance", "holder_rounds",
              "Best liar: keeping the money through a vote",
              f"Share of votes survived while secretly holding the money. {n} games. {whisker}",
              os.path.join(charts, "evasion.png"))
    bar_chart(summary["models"], "detection_rate", "detection_ci", "detection_chance", "detect_votes",
              "Best detective: voting for the real money holder",
              f"Share of a model's votes, when it did not hold the money, that hit the holder. {n} games. {whisker}",
              os.path.join(charts, "detection.png"))
    bar_chart(summary["models"], "win_rate", "win_ci", None, "games",
              "Who ends the game holding the money",
              f"Share of games won. {n} games, nine players each. {whisker}",
              os.path.join(charts, "wins.png"), flat_chance=1 / max(1, len(summary["models"])))
    print(open(os.path.join(run_dir, "summary.md"), encoding="utf-8").read())


if __name__ == "__main__":
    main()
