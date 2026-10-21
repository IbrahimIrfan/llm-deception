from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any


@dataclass
class Bio:
    name: str
    career: str
    personality_traits: List[str]
    interests: List[str]
    family: str
    fun_facts: List[str]


@dataclass
class Player:
    id: str
    model_id: str
    persona: str
    display_name: str = ""
    bio: Optional[Bio] = None


@dataclass
class DayState:
    day_number: int
    public_messages: List[Dict[str, Any]] = field(default_factory=list)
    dm_inbox: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class GameState:
    round_number: int = 0
    alive_players: List[str] = field(default_factory=list)
    eliminated_players: List[str] = field(default_factory=list)
    money_holder: str = ""
    winner: str = ""
    game_over: bool = False
    discussion_done: bool = False
    last_round_summary: str = ""
    public_log: List[str] = field(default_factory=list)
    private_notes: Dict[str, str] = field(default_factory=dict)
    days: List[DayState] = field(default_factory=list)
    players: Dict[str, Player] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        def _bio_to_dict(bio: Optional[Bio]) -> Optional[Dict[str, Any]]:
            return asdict(bio) if bio else None

        def _player_to_dict(player: Player) -> Dict[str, Any]:
            return {
                "id": player.id,
                "model_id": player.model_id,
                "persona": player.persona,
                "display_name": player.display_name,
                "bio": _bio_to_dict(player.bio),
            }

        return {
            "round_number": self.round_number,
            "alive_players": list(self.alive_players),
            "eliminated_players": list(self.eliminated_players),
            "money_holder": self.money_holder,
            "winner": self.winner,
            "game_over": self.game_over,
            "discussion_done": self.discussion_done,
            "last_round_summary": self.last_round_summary,
            "public_log": list(self.public_log),
            "private_notes": dict(self.private_notes),
            "days": [asdict(day) for day in self.days],
            "players": {pid: _player_to_dict(p) for pid, p in self.players.items()},
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "GameState":
        state = GameState()
        state.round_number = data.get("round_number", 0)
        state.alive_players = data.get("alive_players", [])
        state.eliminated_players = data.get("eliminated_players", [])
        state.money_holder = data.get("money_holder", "")
        state.winner = data.get("winner", "")
        state.game_over = data.get("game_over", False)
        state.discussion_done = data.get("discussion_done", False)
        state.last_round_summary = data.get("last_round_summary", "")
        state.public_log = data.get("public_log", [])
        state.private_notes = data.get("private_notes", {})

        players_data = data.get("players", {})
        for pid, pdata in players_data.items():
            bio = pdata.get("bio")
            bio_obj = None
            if bio:
                bio_obj = Bio(
                    name=bio.get("name", ""),
                    career=bio.get("career", ""),
                    personality_traits=bio.get("personality_traits", []),
                    interests=bio.get("interests", []),
                    family=bio.get("family", ""),
                    fun_facts=bio.get("fun_facts", []),
                )
            state.players[pid] = Player(
                id=pdata.get("id", pid),
                model_id=pdata.get("model_id", ""),
                persona=pdata.get("persona", ""),
                display_name=pdata.get("display_name", ""),
                bio=bio_obj,
            )

        state.days = []
        for day in data.get("days", []):
            state.days.append(
                DayState(
                    day_number=day.get("day_number", 0),
                    public_messages=day.get("public_messages", []),
                    dm_inbox=day.get("dm_inbox", {}),
                    order=day.get("order", []),
                    events=day.get("events", []),
                )
            )

        return state
