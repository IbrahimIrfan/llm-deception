from __future__ import annotations

from typing import Dict, List

from state import Player, GameState


SYSTEM_TEMPLATE = """You are Player {player_name} in an online game show. 

The game is a social deduction game where one player secretly holds $1 million dollars.
At the end of each round, everyone will vote for who they think holds the money.
If correct, the money holder is eliminated and the money is reassigned randomly.
If incorrect, the money holder remains hidden and the game continues.

The game is based on deception, strategy, and social interaction.

This is a life changing, high-stakes game. Trust no one. If a player is eliminated, they go home with NOTHING.

Goal:
Survive and end the game holding the money.

Rules:
- You may lie or manipulate. This includes any personal facts, accusations, or alliances.
- You have a private notepad you can write to.
- If you do not hold the money, watch for odd behavior from the money holder.
- At the end of each round, you must vote to eliminate one living player.
- If the vote is tied, there will be a revote among the tied players.
- If the revote is tied, the money holder's vote breaks the tie.
- Public conversation resets each round; remember details in your notes.
- If the money holder is eliminated, the money is reassigned randomly among the living players.
- When only two players remain, the money holder wins.
You may send multiple messages in a round (up to 10). When you are finished for the round, set "done": true.
"""

OUTPUT_FORMAT = """Required output format (strict JSON):
{
  "public_message": "...",
  "private_message_to": "Player_X or null",
  "private_message": "...",
  "notes_update": "...",
  "done": false
}
"""


def build_player_profile(player: Player) -> str:
    bio = player.bio
    if not bio:
        return "(No bio available)"

    traits = ", ".join(bio.personality_traits)
    interests = ", ".join(bio.interests)
    fun_facts = " | ".join(bio.fun_facts)

    return (
        f"Name: {bio.name}\n"
        f"Career: {bio.career}\n"
        f"Personality Traits: {traits}\n"
        f"Interests: {interests}\n"
        f"Family: {bio.family}\n"
        f"Fun Facts: {fun_facts}"
    )


def build_private_context(
    state: GameState,
    player: Player,
    inbox: List[Dict[str, str]],
) -> str:
    notes = state.private_notes.get(player.id, "")

    eliminated_names = [state.players[p].display_name for p in state.eliminated_players]
    eliminated_text = ", ".join(eliminated_names) if eliminated_names else "None"
    alive_names = [state.players[p].display_name for p in state.alive_players]
    alive_text = ", ".join(alive_names) if alive_names else "None"

    inbox_text = "\n".join([f"From {m['from']}: {m['content']}" for m in inbox])
    inbox_text = inbox_text if inbox_text else "None"
    last_summary = state.last_round_summary or "None"

    return (
        f"Round: {state.round_number}\n\n"
        f"You are ALIVE.\n"
        f"Money holder: {'YES' if state.money_holder == player.id else 'NO'}\n\n"
        f"Living players: {alive_text}\n\n"
        f"Eliminated players: {eliminated_text}\n\n"
        f"Last round outcome:\n{last_summary}\n\n"
        f"Your private notes:\n{notes}\n\n"
        f"Private inbox this round:\n{inbox_text}\n"
    )


def build_public_context(public_messages: List[Dict[str, str]]) -> str:
    if not public_messages:
        return "Public conversation so far (this round only):\n<none>"

    lines = []
    for msg in public_messages:
        lines.append(f"{msg['from']}: {msg['content']}")
    return "Public conversation so far (this round only):\n" + "\n".join(lines)


def build_messages(
    state: GameState,
    player: Player,
    public_messages: List[Dict[str, str]],
    inbox: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    system = SYSTEM_TEMPLATE.format(player_name=player.display_name or player.id)
    private_context = build_private_context(state, player, inbox)
    public_context = build_public_context(public_messages)

    user = (
        f"Your player profile:\n{build_player_profile(player)}\n\n"
        f"PRIVATE CONTEXT\n{private_context}\n"
        f"PUBLIC CONTEXT\n{public_context}\n\n"
        f"{OUTPUT_FORMAT}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


REVOTE_OUTPUT_FORMAT = """Required output format (strict JSON):
{
  "vote_out": "Player_X"
}
"""


def build_revote_messages(
    state: GameState,
    player: Player,
    public_messages: List[Dict[str, str]],
    tied_candidates: List[str],
) -> List[Dict[str, str]]:
    system = SYSTEM_TEMPLATE.format(player_name=player.display_name or player.id)
    public_context = build_public_context(public_messages)
    candidates = ", ".join(tied_candidates)
    user = (
        f"REVOTE REQUIRED\n"
        f"Tied candidates: {candidates}\n\n"
        f"Choose ONE player from the tied list and return the JSON only.\n\n"
        f"{public_context}\n\n"
        f"{REVOTE_OUTPUT_FORMAT}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


VOTE_OUTPUT_FORMAT = """Required output format (strict JSON):
{
  "vote_out": "Player_X"
}
"""


def build_vote_messages(
    state: GameState,
    player: Player,
    all_public_messages: List[Dict[str, str]],
    inbox_all: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    system = SYSTEM_TEMPLATE.format(player_name=player.display_name or player.id)
    eliminated_names = [state.players[p].display_name for p in state.eliminated_players]
    eliminated_text = ", ".join(eliminated_names) if eliminated_names else "None"
    alive_names = [state.players[p].display_name for p in state.alive_players]
    alive_text = ", ".join(alive_names) if alive_names else "None"
    notes = state.private_notes.get(player.id, "")

    public_context = build_public_context(all_public_messages)
    inbox_text = "\n".join([f"From {m['from']}: {m['content']}" for m in inbox_all])
    inbox_text = inbox_text if inbox_text else "None"

    user = (
        f"VOTE REQUIRED\n"
        f"Round: {state.round_number}\n\n"
        f"Living players: {alive_text}\n"
        f"Eliminated players: {eliminated_text}\n"
        f"Money holder: {'YES' if state.money_holder == player.id else 'NO'}\n\n"
        f"Your private notes (all rounds):\n{notes}\n\n"
        f"Your private inbox (all rounds):\n{inbox_text}\n\n"
        f"{public_context}\n\n"
        f"Choose ONE living player to eliminate.\n\n"
        f"{VOTE_OUTPUT_FORMAT}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


BIO_SYSTEM = """Write a bio for a real person for a social deduction game. Make it realistic.
Respond with strict JSON only. Do not include code fences or extra text.
"""

BIO_USER = """Create a concise character profile with:
- name
- career
- personality_traits (array)
- interests (array)
- family
- fun_facts (array of 3)
"""


def build_bio_messages() -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": BIO_SYSTEM},
        {"role": "user", "content": BIO_USER},
    ]
