from __future__ import annotations

import json
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional

from agents import LLMClient, load_model_configs, now_iso
from prompts import build_messages, build_bio_messages, build_revote_messages, build_vote_messages
from state import GameState, Player, Bio, DayState
from storage import load_state, save_state, load_bios, save_bio


CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
MODELS_PATH = os.path.join(CONFIG_DIR, "models.json")
PLAYERS_PATH = os.path.join(CONFIG_DIR, "players.json")


def max_messages() -> int:
    """How many times one player may speak in a single discussion round."""
    return int(os.getenv("SIM_MAX_MESSAGES", "10"))


def load_players_config() -> List[Dict[str, Any]]:
    with open(PLAYERS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("players", [])


def build_players(assignment: Optional[Dict[str, str]] = None) -> Dict[str, Player]:
    """Seats come from players.json. `assignment` (seat id -> model id) overrides which model plays each seat."""
    players_config = load_players_config()
    players: Dict[str, Player] = {}
    for item in players_config:
        pid = item["id"]
        players[pid] = Player(
            id=pid,
            model_id=(assignment or {}).get(pid, item["model_id"]),
            persona=item.get("persona", ""),
        )
    return players


def chat_all(requests: Dict[str, Any]) -> Dict[str, str]:
    """Send several players' prompts at the same time. `requests` maps player id -> (model config, messages)."""
    if not requests:
        return {}
    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        futures = {pid: pool.submit(LLMClient(cfg).chat, messages) for pid, (cfg, messages) in requests.items()}
        return {pid: future.result() for pid, future in futures.items()}


def parse_json_block(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def ensure_day(state: GameState) -> DayState:
    if not state.days:
        day = DayState(day_number=state.round_number or 1)
        state.days.append(day)
        return day
    return state.days[-1]


def add_event(day: DayState, event: Dict[str, Any]) -> None:
    event["id"] = len(day.events)
    day.events.append(event)


def resolve_player_id(state: GameState, value: str) -> Optional[str]:
    if not value:
        return None
    value_norm = value.strip().lower()
    if value_norm == "null":
        return None

    if value in state.players:
        return value

    for pid, player in state.players.items():
        if player.display_name and player.display_name.strip().lower() == value_norm:
            return pid
    return None


def init_game(
    force_regen_bios: bool = False,
    assignment: Optional[Dict[str, str]] = None,
    money_holder: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> GameState:
    state = GameState()
    state.players = build_players(assignment)
    state.alive_players = list(state.players.keys())
    state.eliminated_players = []
    state.round_number = 1
    state.winner = ""
    state.game_over = False
    state.discussion_done = False
    print(f"[init] players={len(state.alive_players)} force_regen_bios={force_regen_bios}")

    bios_data = load_bios()
    if force_regen_bios:
        bios_data = {}

    models = load_model_configs(MODELS_PATH)

    for pid, player in state.players.items():
        bio_data = bios_data.get(pid)
        if not bio_data:
            model_cfg = models[player.model_id]
            print(f"[init] generating bio pid={pid} model={model_cfg.model}")
            client = LLMClient(model_cfg)
            raw = client.chat(build_bio_messages())
            parsed = parse_json_block(raw) or {}
            if not parsed:
                print(f"[init] bio_retry pid={pid}")
                raw = client.chat(build_bio_messages())
                parsed = parse_json_block(raw) or {}
            if not parsed or not parsed.get("name"):
                print(f"[init] bio_parse_warning pid={pid} raw_chars={len(raw)}")
                print(f"[init] bio_raw pid={pid} raw={raw}")
            bio_data = {
                "name": parsed.get("name", f"Player {pid}"),
                "career": parsed.get("career", ""),
                "personality_traits": parsed.get("personality_traits", []),
                "interests": parsed.get("interests", []),
                "family": parsed.get("family", ""),
                "fun_facts": parsed.get("fun_facts", []),
            }
            bios_data[pid] = bio_data
            path = save_bio(pid, bio_data)
            print(f"[init] bio_saved pid={pid} path={path}")
        else:
            print(f"[init] using cached bio pid={pid}")

        player.display_name = bio_data.get("name", pid)
        player.bio = Bio(
            name=bio_data.get("name", pid),
            career=bio_data.get("career", ""),
            personality_traits=bio_data.get("personality_traits", []),
            interests=bio_data.get("interests", []),
            family=bio_data.get("family", ""),
            fun_facts=bio_data.get("fun_facts", []),
        )

    print(f"[init] bios_cached={len(bios_data)} dir=sim/bios")

    state.money_holder = money_holder if money_holder in state.alive_players else random.choice(state.alive_players)
    print(f"[init] money_holder={state.money_holder}")
    state.meta = dict(meta or {})
    state.meta["started_at"] = now_iso()
    state.meta["models"] = {mid: cfg.model for mid, cfg in models.items()}
    state.private_notes = {pid: "" for pid in state.alive_players}

    day = DayState(day_number=state.round_number)
    add_event(
        day,
        {
            "ts": now_iso(),
            "channel": "system",
            "from": "system",
            "to": state.players[state.money_holder].display_name,
            "content": "Money holder assigned.",
            "day": day.day_number,
        },
    )
    state.days.append(day)

    save_state(state)
    return state


def append_note(state: GameState, pid: str, note: str) -> None:
    if not note:
        return
    existing = state.private_notes.get(pid, "")
    updated = (existing + "\n" + note).strip() if existing else note
    state.private_notes[pid] = updated


def run_round() -> GameState:
    state = load_state()
    if not state.alive_players or state.game_over or state.discussion_done:
        return state

    print(f"[round] start round={state.round_number} alive={len(state.alive_players)}")
    day = ensure_day(state)
    day.order = list(state.alive_players)
    random.shuffle(day.order)
    print(f"[round] order={day.order}")

    models = load_model_configs(MODELS_PATH)
    counts: Dict[str, int] = {pid: 0 for pid in state.alive_players}
    done: Dict[str, bool] = {pid: False for pid in state.alive_players}
    inbox_seen: Dict[str, int] = {
        pid: len(day.dm_inbox.get(pid, [])) for pid in state.alive_players
    }

    while True:
        # One wave: every player who still wants to speak answers the same snapshot of the
        # conversation at the same time, like people typing at once in a group chat.
        active = []
        for pid in day.order:
            if pid not in state.alive_players or counts[pid] >= max_messages():
                continue
            has_new_dm = len(day.dm_inbox.get(pid, [])) > inbox_seen[pid]
            if done[pid] and not has_new_dm:
                continue
            active.append(pid)
        if not active:
            break

        prompts = {
            pid: build_messages(
                state=state,
                player=state.players[pid],
                public_messages=day.public_messages,
                inbox=day.dm_inbox.get(pid, []),
            )
            for pid in active
        }
        seen_now = {pid: len(day.dm_inbox.get(pid, [])) for pid in active}
        print(f"[round] wave players={active}")
        raws = chat_all({pid: (models[state.players[pid].model_id], prompts[pid]) for pid in active})

        for pid in active:
            player = state.players[pid]
            raw = raws[pid]
            inbox_seen[pid] = seen_now[pid]
            counts[pid] += 1
            print(f"[round] raw_response pid={pid} chars={len(raw)}")

            add_event(
                day,
                {
                    "ts": now_iso(),
                    "channel": "agent_raw",
                    "from": player.display_name,
                    "to": None,
                    "content": raw,
                    "day": day.day_number,
                },
            )

            parsed = parse_json_block(raw)
            if not parsed:
                print(f"[round] parse_failed pid={pid}")
                add_event(
                    day,
                    {
                        "ts": now_iso(),
                        "channel": "system",
                        "from": "system",
                        "to": player.display_name,
                        "content": "Agent output could not be parsed as JSON.",
                        "day": day.day_number,
                    },
                )
                continue

            public_message = (parsed.get("public_message") or "").strip()
            private_to = parsed.get("private_message_to")
            private_message = (parsed.get("private_message") or "").strip()
            notes_update = (parsed.get("notes_update") or "").strip()
            done_flag = bool(parsed.get("done"))
            if public_message:
                print(f"[round] public pid={pid} chars={len(public_message)}")
                print(f"[round] public_text pid={pid} text={public_message}")
                msg = {
                    "ts": now_iso(),
                    "from": player.display_name,
                    "content": public_message,
                }
                day.public_messages.append(msg)
                add_event(
                    day,
                    {
                        "ts": msg["ts"],
                        "channel": "public",
                        "from": player.display_name,
                        "to": None,
                        "content": public_message,
                        "day": day.day_number,
                    },
                )
                save_state(state)

            target_pid = None
            if isinstance(private_to, str):
                target_pid = resolve_player_id(state, private_to)
            if target_pid and private_message:
                print(f"[round] dm from={pid} to={target_pid} chars={len(private_message)}")
                print(f"[round] dm_text from={pid} to={target_pid} text={private_message}")
                dm = {
                    "ts": now_iso(),
                    "from": player.display_name,
                    "content": private_message,
                }
                day.dm_inbox.setdefault(target_pid, []).append(dm)
                add_event(
                    day,
                    {
                        "ts": dm["ts"],
                        "channel": "dm",
                        "from": player.display_name,
                        "to": state.players[target_pid].display_name,
                        "content": private_message,
                        "day": day.day_number,
                    },
                )
                save_state(state)

            append_note(state, pid, notes_update)
            if notes_update:
                print(f"[round] notes_update pid={pid} chars={len(notes_update)}")
                save_state(state)
            if done_flag:
                done[pid] = True
                print(f"[round] done pid={pid}")

        save_state(state)

    state.discussion_done = True
    save_state(state)
    print(f"[round] end round={state.round_number} alive={len(state.alive_players)}")
    return state


def auto_loop(stop_check) -> None:
    while True:
        state = load_state()
        if stop_check():
            print("[auto] stop requested")
            break
        if state.game_over:
            print("[auto] game over")
            break
        if state.discussion_done:
            start_vote()
        else:
            run_round()


def start_vote() -> GameState:
    state = load_state()
    if not state.alive_players or state.game_over or not state.discussion_done:
        print(
            f"[vote] skipped alive={len(state.alive_players)} game_over={state.game_over} discussion_done={state.discussion_done}"
        )
        return state

    print(f"[vote] start round={state.round_number} alive={len(state.alive_players)}")
    day = ensure_day(state)
    if not day.order:
        day.order = list(state.alive_players)
    print(f"[vote] day={day.day_number} order={day.order} events={len(day.events)}")
    models = load_model_configs(MODELS_PATH)

    all_public = []
    for past in state.days:
        all_public.extend(past.public_messages)
    print(f"[vote] public_messages={len(all_public)}")

    inbox_all: Dict[str, List[Dict[str, str]]] = {}
    for past in state.days:
        for pid, msgs in past.dm_inbox.items():
            inbox_all.setdefault(pid, []).extend(msgs)
    print(f"[vote] inbox_players={len(inbox_all)} inbox_messages={sum(len(v) for v in inbox_all.values())}")

    tally: Dict[str, int] = {}
    voters = [pid for pid in day.order if pid in state.alive_players]
    raws = chat_all(
        {
            pid: (
                models[state.players[pid].model_id],
                build_vote_messages(
                    state=state,
                    player=state.players[pid],
                    all_public_messages=all_public,
                    inbox_all=inbox_all.get(pid, []),
                ),
            )
            for pid in voters
        }
    )
    for pid in voters:
        player = state.players[pid]
        raw = raws[pid]
        print(f"[vote] raw_response pid={pid} chars={len(raw)}")
        add_event(
            day,
            {
                "ts": now_iso(),
                "channel": "agent_raw",
                "from": player.display_name,
                "to": None,
                "content": raw,
                "day": day.day_number,
            },
        )
        parsed = parse_json_block(raw)
        if not parsed:
            print(f"[vote] parse_failed pid={pid}")
            continue
        vote_out = (parsed.get("vote_out") or "").strip()
        print(f"[vote] vote pid={pid} target={vote_out}")
        target_pid = resolve_player_id(state, vote_out)
        if target_pid and target_pid in state.alive_players:
            tally[target_pid] = tally.get(target_pid, 0) + 1
            add_event(
                day,
                {
                    "ts": now_iso(),
                    "channel": "vote",
                    "from": player.display_name,
                    "to": vote_out,
                    "content": vote_out,
                    "day": day.day_number,
                },
            )
            save_state(state)
        else:
            print(f"[vote] invalid_vote pid={pid} target={vote_out}")

    eliminated = resolve_elimination(state, day, tally)
    print(f"[vote] tally={tally}")
    if eliminated:
        print(f"[vote] eliminated pid={eliminated}")
        state.alive_players.remove(eliminated)
        state.eliminated_players.append(eliminated)
        had_money = eliminated == state.money_holder
        summary = f"Eliminated: {state.players[eliminated].display_name}. "
        add_event(
            day,
            {
                "ts": now_iso(),
                "channel": "elimination",
                "from": "system",
                "to": state.players[eliminated].display_name,
                "content": "Eliminated by vote.",
                "day": day.day_number,
            },
        )
        if had_money and state.alive_players:
            state.money_holder = random.choice(state.alive_players)
            print(f"[vote] money_moved to={state.money_holder}")
            add_event(
                day,
                {
                    "ts": now_iso(),
                    "channel": "money_move",
                    "from": "system",
                    "to": state.players[state.money_holder].display_name,
                    "content": "Money reassigned after elimination.",
                    "day": day.day_number,
                },
            )
            summary += "They had the money. Money reassigned."
        else:
            summary += "They did NOT have the money."
        state.last_round_summary = summary

    if len(state.alive_players) <= 2:
        state.game_over = True
        if state.money_holder in state.alive_players:
            state.winner = state.money_holder
        elif state.alive_players:
            state.winner = random.choice(state.alive_players)
        print(f"[vote] game_over winner={state.winner}")
        add_event(
            day,
            {
                "ts": now_iso(),
                "channel": "game_over",
                "from": "system",
                "to": state.players.get(state.winner, Player("", "", "")).display_name,
                "content": "Game over.",
                "day": day.day_number,
            },
        )

    state.round_number += 1
    state.days.append(DayState(day_number=state.round_number))
    state.discussion_done = False
    save_state(state)
    print(f"[vote] end round={state.round_number - 1} alive={len(state.alive_players)}")
    return state


def resolve_elimination(state: GameState, day: DayState, tally: Dict[str, int]) -> str:
    if not state.alive_players:
        return ""

    if not tally:
        top = list(state.alive_players)
        add_event(
            day,
            {
                "ts": now_iso(),
                "channel": "system",
                "from": "system",
                "to": None,
                "content": "No valid votes. Revote among all living players.",
                "day": day.day_number,
            },
        )
    else:
        max_votes = max(tally.values())
        top = [pid for pid, count in tally.items() if count == max_votes]
        if len(top) == 1:
            return top[0]

    tied_names = [state.players[pid].display_name for pid in top]
    if tally:
        add_event(
            day,
            {
                "ts": now_iso(),
                "channel": "system",
                "from": "system",
                "to": None,
                "content": f"Vote tied. Revote among: {', '.join(tied_names)}.",
                "day": day.day_number,
            },
        )

    models = load_model_configs(MODELS_PATH)
    revote_tally: Dict[str, int] = {}
    voters = [pid for pid in day.order if pid in state.alive_players]
    raws = chat_all(
        {
            pid: (
                models[state.players[pid].model_id],
                build_revote_messages(
                    state=state,
                    player=state.players[pid],
                    public_messages=day.public_messages,
                    tied_candidates=tied_names,
                ),
            )
            for pid in voters
        }
    )
    for pid in voters:
        player = state.players[pid]
        raw = raws[pid]
        add_event(
            day,
            {
                "ts": now_iso(),
                "channel": "agent_raw",
                "from": player.display_name,
                "to": None,
                "content": raw,
                "day": day.day_number,
            },
        )
        parsed = parse_json_block(raw)
        if not parsed:
            continue
        vote_out = (parsed.get("vote_out") or "").strip()
        target_pid = resolve_player_id(state, vote_out)
        if target_pid and target_pid in top:
            revote_tally[target_pid] = revote_tally.get(target_pid, 0) + 1
            add_event(
                day,
                {
                    "ts": now_iso(),
                    "channel": "vote_re",
                    "from": player.display_name,
                    "to": vote_out,
                    "content": vote_out,
                    "day": day.day_number,
                },
            )

    revote_top: List[str] = []
    if not revote_tally:
        add_event(
            day,
            {
                "ts": now_iso(),
                "channel": "system",
                "from": "system",
                "to": None,
                "content": "No valid revotes. Money holder vote will decide.",
                "day": day.day_number,
            },
        )
    else:
        revote_max = max(revote_tally.values())
        revote_top = [pid for pid, count in revote_tally.items() if count == revote_max]
        if len(revote_top) == 1:
            return revote_top[0]

    money_vote = None
    money_name = state.players[state.money_holder].display_name
    for event in day.events:
        if event.get("channel") == "vote_re" and event.get("from") == money_name:
            money_vote = resolve_player_id(state, event.get("to") or "")
            break
    if money_vote and money_vote in (revote_top or top):
        add_event(
            day,
            {
                "ts": now_iso(),
                "channel": "system",
                "from": "system",
                "to": state.players[money_vote].display_name,
                "content": "Tie broken by money holder vote.",
                "day": day.day_number,
            },
        )
        return money_vote

    fallback_pool = revote_top or top
    fallback = sorted(fallback_pool)[0]
    add_event(
        day,
        {
            "ts": now_iso(),
            "channel": "system",
            "from": "system",
            "to": state.players[fallback].display_name,
            "content": "Tie unresolved. Defaulted to deterministic fallback.",
            "day": day.day_number,
        },
    )
    return fallback

def set_money_holder(pid: str) -> GameState:
    state = load_state()
    if pid in state.players:
        state.money_holder = pid
    save_state(state)
    return state

def eliminate_player(pid: str) -> GameState:
    state = load_state()
    if pid in state.alive_players:
        state.alive_players.remove(pid)
        state.eliminated_players.append(pid)
    save_state(state)
    return state
