"""
Flask API Server
Exposes the Vessel PMS orchestrator via:
  - REST endpoints for status queries and control commands
  - SocketIO for real-time state streaming to the dashboard
"""

import asyncio
import threading
import logging
import json
import sys
import os
from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from agents.orchestrator import VesselPMSOrchestratorAgent

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/home/claude/quantum_vessel_pms/logs/pms.log"),
    ],
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Flask + SocketIO setup
# ------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = "vessel-pms-quantum-2025"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Global orchestrator instance
orchestrator: VesselPMSOrchestratorAgent | None = None
orchestrator_thread: threading.Thread | None = None


def state_broadcaster(state: dict) -> None:
    """Called by orchestrator every tick to push state to all clients."""
    try:
        socketio.emit("system_state", state, namespace="/pms")
    except Exception as e:
        logger.debug(f"Broadcast error: {e}")


def _start_orchestrator() -> None:
    global orchestrator
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    orchestrator = VesselPMSOrchestratorAgent(
        n_quantum_loads=6,
        on_state_update=state_broadcaster,
    )
    loop.run_until_complete(orchestrator.run())


# ------------------------------------------------------------------
# REST endpoints
# ------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "orchestrator_running": orchestrator is not None})


@app.route("/api/state", methods=["GET"])
def get_state():
    if orchestrator is None:
        return jsonify({"error": "orchestrator not running"}), 503
    return jsonify(orchestrator.get_state())


@app.route("/api/quantum/results", methods=["GET"])
def get_quantum_results():
    if orchestrator is None:
        return jsonify({"error": "orchestrator not running"}), 503
    last_n = int(request.args.get("n", 10))
    return jsonify(orchestrator.quantum_results[-last_n:])


@app.route("/api/faults/alerts", methods=["GET"])
def get_alerts():
    if orchestrator is None:
        return jsonify([]), 503
    return jsonify(orchestrator.fault_agent.get_status()["active_alerts"])


@app.route("/api/faults/acknowledge/<alert_id>", methods=["POST"])
def acknowledge_alert(alert_id: str):
    if orchestrator is None:
        return jsonify({"error": "orchestrator not running"}), 503
    ok = orchestrator.fault_agent.acknowledge_alert(alert_id)
    return jsonify({"acknowledged": ok, "alert_id": alert_id})


@app.route("/api/loads", methods=["GET"])
def get_loads():
    if orchestrator is None:
        return jsonify([]), 503
    return jsonify(orchestrator.load_agent.get_status())


@app.route("/api/loads/<load_id>/toggle", methods=["POST"])
def toggle_load(load_id: str):
    if orchestrator is None:
        return jsonify({"error": "orchestrator not running"}), 503
    for load in orchestrator.load_agent.loads:
        if load.id == load_id:
            load.active = not load.active
            return jsonify({"load_id": load_id, "active": load.active})
    return jsonify({"error": f"load {load_id} not found"}), 404


@app.route("/api/fuel/merit_order", methods=["GET"])
def get_merit_order():
    if orchestrator is None:
        return jsonify({}), 503
    demand = orchestrator.load_agent.total_demand_mw
    return jsonify(orchestrator.fuel_agent.compute_merit_order(demand))


@app.route("/api/generation", methods=["GET"])
def get_generation():
    if orchestrator is None:
        return jsonify({}), 503
    return jsonify(orchestrator.generation_agent.get_status())


# ------------------------------------------------------------------
# SocketIO events
# ------------------------------------------------------------------

@socketio.on("connect", namespace="/pms")
def on_connect():
    logger.info(f"Dashboard client connected")
    if orchestrator and orchestrator.system_state:
        emit("system_state", orchestrator.system_state)


@socketio.on("disconnect", namespace="/pms")
def on_disconnect():
    logger.info("Dashboard client disconnected")


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    import os
    os.makedirs("/home/claude/quantum_vessel_pms/logs", exist_ok=True)

    # Start orchestrator in a background thread
    orchestrator_thread = threading.Thread(target=_start_orchestrator, daemon=True)
    orchestrator_thread.start()
    logger.info("Orchestrator thread started — waiting for boot...")

    import time
    time.sleep(4)   # Allow generators to come online

    logger.info("Starting Flask server on http://0.0.0.0:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False)
