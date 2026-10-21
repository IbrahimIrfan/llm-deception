# LLM Social Deduction Simulator

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install flask openrouter
```

Set your OpenRouter key:

```bash
export OPENROUTER_API_KEY=your_key_here
```

## Run

```bash
python sim/app.py
```

Round flow:

- Run Discussion (each player speaks once)
- Start Vote (separate voting prompt)

Open `http://localhost:7691`.

## Config

- Models: `sim/config/models.json`
- Players: `sim/config/players.json`
- Logs: `sim/logs/state.json`
- Bios: `sim/bios/{player_id}.json`
