from __future__ import annotations

import os
from flask import Flask, jsonify, request, render_template, send_from_directory

from agents import load_model_configs
import threading

from controller import MODELS_PATH, init_game, run_round, start_vote, auto_loop
from storage import load_state


app = Flask(__name__, static_folder="static", template_folder="templates")
IMG_DIR = os.path.join(os.path.dirname(__file__), "img")
AUTO_STATE = {"running": False, "stop": False}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/img/<path:filename>")
def serve_image(filename: str):
    return send_from_directory(IMG_DIR, filename)


@app.get("/api/state")
def api_state():
    state = load_state()
    payload = state.to_dict()
    models = load_model_configs(MODELS_PATH)
    payload["models"] = {mid: cfg.model for mid, cfg in models.items()}
    return jsonify(payload)


@app.post("/api/init")
def api_init():
    payload = request.get_json(silent=True) or {}
    force = bool(payload.get("force_regen_bios"))
    state = init_game(force_regen_bios=force)
    return jsonify(state.to_dict())


@app.post("/api/run_round")
def api_run_round():
    print("[api] advance round")
    state = run_round()
    return jsonify(state.to_dict())


@app.post("/api/start_vote")
def api_start_vote():
    state = load_state()
    print(
        f"[api] start_vote round={state.round_number} discussion_done={state.discussion_done} alive={len(state.alive_players)}"
    )
    state = start_vote()
    return jsonify(state.to_dict())


@app.post("/api/auto_step")
def api_auto_step():
    state = load_state()
    if state.game_over:
        return jsonify(state.to_dict())
    if state.discussion_done:
        state = start_vote()
    else:
        state = run_round()
    return jsonify(state.to_dict())


@app.post("/api/auto_start")
def api_auto_start():
    if AUTO_STATE["running"]:
        return jsonify({"status": "already_running"})
    AUTO_STATE["running"] = True
    AUTO_STATE["stop"] = False

    def runner():
        try:
            auto_loop(lambda: AUTO_STATE["stop"])
        finally:
            AUTO_STATE["running"] = False

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.post("/api/auto_stop")
def api_auto_stop():
    AUTO_STATE["stop"] = True
    return jsonify({"status": "stopping"})


@app.get("/api/auto_status")
def api_auto_status():
    return jsonify({"running": AUTO_STATE["running"]})




if __name__ == "__main__":
    port = int(os.getenv("PORT", "7691"))
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
