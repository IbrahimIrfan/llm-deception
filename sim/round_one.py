"""Round-one analysis: what happens in the first discussion and vote of each game.

    python sim/round_one.py results/round1

Reads the games in <run>/games and the labels in <run>/judge, then writes
round_one.json, round_one.md and charts/*.png into the run folder.
"""
from __future__ import annotations

import glob
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List

SIM_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SIM_DIR)
sys.path.insert(0, SIM_DIR)

from analyze import BAR, GRID, INK, MUTED, SURFACE, model_labels, replay  # noqa: E402

ORANGE = "#eb6834"


def load(run_dir: str) -> List[Dict[str, Any]]:
    labels = model_labels()
    games = []
    for path in sorted(glob.glob(os.path.join(run_dir, "games", "*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            game = json.load(f)
        gid = os.path.basename(path)[:-5]
        r = replay(game)[0]
        model = {pid: labels.get(p["model_id"], p["model_id"]) for pid, p in game["players"].items()}
        name = {pid: p["display_name"] for pid, p in game["players"].items()}
        judge_path = os.path.join(run_dir, "judge", f"{gid}.json")
        judged = {}
        if os.path.exists(judge_path):
            with open(judge_path, "r", encoding="utf-8") as f:
                judged = {row["player"]: row for row in json.load(f)["labels"]}
        tally = Counter(t for t in r["votes"].values() if t)
        games.append(
            {
                "id": gid,
                "model": model,
                "name": name,
                "holder": r["holder"],
                "eliminated": r["eliminated"],
                "votes": r["votes"],
                "tally": tally,
                "public": {pid: r["public"][pid] for pid in model},
                "dms": {pid: r["dms"][pid] for pid in model},
                "judge": judged,
            }
        )
    return games


def summarise(games: List[Dict[str, Any]]) -> Dict[str, Any]:
    per: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    rows = []
    for g in games:
        h, out = g["holder"], g["eliminated"]
        non_holder_votes = {v: t for v, t in g["votes"].items() if v != h}
        top_votes = max(g["tally"].values())
        others_public = [n for pid, n in g["public"].items() if pid != out]
        rows.append(
            {
                "game": g["id"],
                "holder_model": g["model"][h],
                "eliminated_model": g["model"][out],
                "holder_caught": h == out,
                "votes_on_holder": sum(1 for t in non_holder_votes.values() if t == h),
                "non_holder_votes": len(non_holder_votes),
                "votes_on_eliminated": top_votes,
                "votes_cast": sum(g["tally"].values()),
                "holder_voted_with_majority": g["votes"].get(h) == out,
                "eliminated_public_msgs": g["public"][out],
                "median_public_msgs_others": statistics.median(others_public),
                "holder_public_msgs": g["public"][h],
                "holder_public_claim": g["judge"].get(h, {}).get("public_claim"),
                "holder_notes_plan_deception": g["judge"].get(h, {}).get("notes_plan_deception"),
            }
        )
        for pid, m in g["model"].items():
            s = per[m]
            s["games"] += 1
            s["votes_received"] += g["tally"][pid]
            s["eliminated"] += pid == out
            s["public_msgs"] += g["public"][pid]
            s["dms"] += g["dms"][pid]
            s["held"] += pid == h
            s["caught"] += pid == h and pid == out
            if pid != h and pid in g["votes"]:
                s["votes_cast_as_innocent"] += 1
                s["votes_hit_holder"] += g["votes"][pid] == h
            label = g["judge"].get(pid)
            if label:
                s["labelled"] += 1
                s["public_denies"] += label["public_claim"] == "denies"
                s["public_claims"] += label["public_claim"] == "claims"
                s["notes_plan_deception"] += bool(label["notes_plan_deception"])
                if pid != h:
                    s["innocent_labelled"] += 1
                    s["innocent_denies"] += label["public_claim"] == "denies"
                    s["innocent_plans_deception"] += bool(label["notes_plan_deception"])

    models = [{"model": m, **{k: (int(v) if float(v).is_integer() else v) for k, v in s.items()}} for m, s in per.items()]
    models.sort(key=lambda m: -m["votes_received"])
    n = len(rows)
    totals = {
        "games": n,
        "holder_caught": sum(r["holder_caught"] for r in rows),
        "votes_on_holder": sum(r["votes_on_holder"] for r in rows),
        "non_holder_votes": sum(r["non_holder_votes"] for r in rows),
        "chance_votes_on_holder": round(sum(r["non_holder_votes"] for r in rows) / 8, 1),
        "mean_share_of_votes_on_eliminated": round(
            sum(r["votes_on_eliminated"] / r["votes_cast"] for r in rows) / n, 3
        ),
        "holder_voted_with_majority": sum(r["holder_voted_with_majority"] for r in rows if not r["holder_caught"]),
        "holder_survived": sum(not r["holder_caught"] for r in rows),
        "eliminated_spoke_less_than_median": sum(
            r["eliminated_public_msgs"] < r["median_public_msgs_others"] for r in rows
        ),
        "holders_publicly_denied": sum(r["holder_public_claim"] == "denies" for r in rows),
        "holders_planned_deception_in_notes": sum(bool(r["holder_notes_plan_deception"]) for r in rows),
    }
    return {"totals": totals, "games": rows, "models": models}


def style(ax, fig) -> None:
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)


def chart_votes(summary: Dict[str, Any], path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = sorted(summary["models"], key=lambda m: m["votes_received"])
    total = sum(m["votes_received"] for m in rows)
    fig, ax = plt.subplots(figsize=(8.4, 0.52 * len(rows) + 1.7), dpi=200)
    style(ax, fig)
    ys = range(len(rows))
    ax.barh(ys, [m["votes_received"] for m in rows], height=0.56, color=BAR, zorder=2)
    top = max(m["votes_received"] for m in rows)
    for y, m in zip(ys, rows):
        held = f"held the money {m['held']}x, caught {m['caught']}x" if m["held"] else "never held the money"
        ax.text(m["votes_received"] + top * 0.015, y, f"{m['votes_received']}   voted out {m['eliminated']}x · {held}",
                va="center", ha="left", fontsize=8.5, color=MUTED)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([m["model"] for m in rows], fontsize=10, color=INK)
    ax.set_xlim(0, top * 2.1)
    ax.set_xticks([0, 10, 20, 30])
    ax.tick_params(axis="x", labelsize=9, labelcolor=MUTED)
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    n = summary["totals"]["games"]
    fig.text(0.02, 0.975, "Two models drew 70% of all first-round votes", fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.02, 0.975 - 0.42 / fig.get_figheight(),
             f"Votes received in round one, summed over {n} games ({total} votes). Each model played every game.",
             fontsize=9.5, color=MUTED, va="top")
    fig.subplots_adjust(left=0.24, right=0.98, top=1 - 1.0 / fig.get_figheight(), bottom=0.5 / fig.get_figheight())
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def chart_quiet(summary: Dict[str, Any], path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = summary["games"]
    fig, ax = plt.subplots(figsize=(8.4, 4.4), dpi=200)
    style(ax, fig)
    xs = range(len(rows))
    w = 0.36
    ax.bar([x - w / 2 - 0.01 for x in xs], [r["eliminated_public_msgs"] for r in rows], width=w, color=ORANGE, zorder=2,
           label="player who was voted out")
    ax.bar([x + w / 2 + 0.01 for x in xs], [r["median_public_msgs_others"] for r in rows], width=w, color=BAR, zorder=2,
           label="median of the other eight")
    for x, r in zip(xs, rows):
        ax.text(x - w / 2 - 0.01, r["eliminated_public_msgs"] + 0.15, str(r["eliminated_public_msgs"]), ha="center",
                fontsize=8.5, color=MUTED)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([f"{r['eliminated_model']}{' *' if r['holder_caught'] else ''}".replace(" ", "\n", 1) for r in rows],
                       fontsize=7.5, color=INK)
    ax.tick_params(axis="y", labelsize=9, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.legend(loc="upper right", bbox_to_anchor=(1.0, 1.12), ncol=2, fontsize=8.5, frameon=False, labelcolor=MUTED)
    quiet = summary["totals"]["eliminated_spoke_less_than_median"]
    fig.text(0.02, 0.975, f"In {quiet} of {len(rows)} games the player voted out had spoken less than the typical player",
             fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.02, 0.905, "Public messages sent in round one. One pair of bars per game, labelled with the model that was voted out. "
             "* = it held the money.", fontsize=9, color=MUTED, va="top")
    fig.subplots_adjust(left=0.06, right=0.98, top=0.78, bottom=0.14)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def write_markdown(summary: Dict[str, Any], path: str) -> None:
    lines = ["| Game | Held the money | Voted out | Votes on the holder | Votes on the player voted out | Holder caught |",
             "|---|---|---|---|---|---|"]
    for r in summary["games"]:
        lines.append(
            f"| {r['game'][-3:]} | {r['holder_model']} | {r['eliminated_model']} | {r['votes_on_holder']} of {r['non_holder_votes']} | "
            f"{r['votes_on_eliminated']} of {r['votes_cast']} | {'yes' if r['holder_caught'] else 'no'} |"
        )
    lines += ["", "| Model | Votes received | Voted out | Held money | Caught | Votes that hit the holder | Public msgs / game | DMs / game | Notes plan deception |",
              "|---|---|---|---|---|---|---|---|---|"]
    for m in summary["models"]:
        g = m["games"]
        lines.append(
            f"| {m['model']} | {m['votes_received']} | {m['eliminated']} | {m['held']} | {m['caught']} | "
            f"{m.get('votes_hit_holder', 0)} of {m.get('votes_cast_as_innocent', 0)} | {m['public_msgs'] / g:.1f} | {m['dms'] / g:.1f} | "
            f"{m.get('notes_plan_deception', 0)} of {m.get('labelled', 0)} |"
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    run_dir = sys.argv[1] if os.path.isabs(sys.argv[1]) else os.path.join(REPO_ROOT, sys.argv[1])
    summary = summarise(load(run_dir))
    with open(os.path.join(run_dir, "round_one.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    write_markdown(summary, os.path.join(run_dir, "round_one.md"))
    os.makedirs(os.path.join(run_dir, "charts"), exist_ok=True)
    chart_votes(summary, os.path.join(run_dir, "charts", "votes_received.png"))
    chart_quiet(summary, os.path.join(run_dir, "charts", "quiet_players.png"))
    print(json.dumps(summary["totals"], indent=2))
    print(open(os.path.join(run_dir, "round_one.md"), encoding="utf-8").read())


if __name__ == "__main__":
    main()
