from __future__ import annotations

import json
import os
from typing import Any, Dict

from state import GameState


STATE_PATH = os.path.join(os.path.dirname(__file__), "logs", "state.json")
BIOS_DIR = os.path.join(os.path.dirname(__file__), "bios")


def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_state() -> GameState:
    data = load_json(STATE_PATH)
    if not data:
        return GameState()
    return GameState.from_dict(data)


def save_state(state: GameState) -> None:
    save_json(STATE_PATH, state.to_dict())


def load_bios() -> Dict[str, Any]:
    bios: Dict[str, Any] = {}
    if not os.path.exists(BIOS_DIR):
        return bios
    for filename in os.listdir(BIOS_DIR):
        if not filename.endswith(".json"):
            continue
        pid = filename[:-5]
        bios[pid] = load_json(os.path.join(BIOS_DIR, filename))
    return bios


def save_bio(pid: str, bio: Dict[str, Any]) -> str:
    os.makedirs(BIOS_DIR, exist_ok=True)
    path = os.path.join(BIOS_DIR, f"{pid}.json")
    save_json(path, bio)
    return path
