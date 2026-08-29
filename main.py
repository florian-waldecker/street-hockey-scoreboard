import asyncio
import json
import logging
from typing import Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Scoreboard")

app = FastAPI(title="Street Hockey Scoreboard")

# ==========================================
# STATE & DATA MODEL
# ==========================================
class Penalty:
    def __init__(self, player: str = "99", duration_seconds: int = 120):
        self.player = player
        self.duration_seconds = duration_seconds
        self.remaining_seconds = duration_seconds
        self.is_active = False

    def to_dict(self):
        return {
            "player": self.player,
            "remaining_seconds": self.remaining_seconds,
            "is_active": self.is_active
        }

class ScoreboardState:
    def __init__(self):
        # Teams
        self.home_name = "HEIM"
        self.away_name = "GAST"
        self.home_score = 0
        self.away_score = 0
        self.home_shots = 0
        self.away_shots = 0
        
        # Period & Timer
        self.period = "1"  # "1", "2", "3", "OT"
        self.period_duration = 15 * 60  # Default 15 Minuten
        self.time_remaining = self.period_duration
        self.timer_running = False

        # Penalties: list of active penalty slots for Home and Away (max 2 per team)
        self.home_penalties = []
        self.away_penalties = []
        
        # Audio Buzzer Event Flag
        self.buzzer_trigger = 0

    def to_dict(self):
        return {
            "home_name": self.home_name,
            "away_name": self.away_name,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "home_shots": self.home_shots,
            "away_shots": self.away_shots,
            "period": self.period,
            "period_duration": self.period_duration,
            "time_remaining": self.time_remaining,
            "timer_running": self.timer_running,
            "home_penalties": self.home_penalties,
            "away_penalties": self.away_penalties,
            "buzzer_trigger": self.buzzer_trigger
        }

state = ScoreboardState()

# ==========================================
# WEBSOCKET CONNECTION MANAGER
# ==========================================
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        payload = json.dumps(message)
        dead_connections = set()
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception:
                dead_connections.add(connection)
        for dead in dead_connections:
            self.active_connections.discard(dead)

manager = ConnectionManager()

# ==========================================
# BACKGROUND TIMER LOOP (Asyncio)
# ==========================================
async def timer_loop():
    while True:
        await asyncio.sleep(1.0)
        if state.timer_running:
            if state.time_remaining > 0:
                state.time_remaining -= 1
                
                # Update Home Penalties
                expired_home = []
                for p in state.home_penalties:
                    if p["remaining_seconds"] > 0:
                        p["remaining_seconds"] -= 1
                    else:
                        expired_home.append(p)
                for p in expired_home:
                    state.home_penalties.remove(p)

                # Update Away Penalties
                expired_away = []
                for p in state.away_penalties:
                    if p["remaining_seconds"] > 0:
                        p["remaining_seconds"] -= 1
                    else:
                        expired_away.append(p)
                for p in expired_away:
                    state.away_penalties.remove(p)

                if state.time_remaining == 0:
                    state.timer_running = False
                    state.buzzer_trigger += 1

                await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})
            else:
                state.timer_running = False
                await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(timer_loop())

# ==========================================
# COMMAND HANDLER
# ==========================================
async def handle_command(cmd: dict):
    action = cmd.get("action")

    if action == "TIMER_START":
        if state.time_remaining > 0:
            state.timer_running = True
    elif action == "TIMER_PAUSE":
        state.timer_running = False
    elif action == "TIMER_TOGGLE":
        if state.time_remaining > 0:
            state.timer_running = not state.timer_running
    elif action == "TIMER_RESET":
        state.timer_running = False
        state.time_remaining = state.period_duration
    elif action == "TIMER_SET_DURATION":
        minutes = int(cmd.get("minutes", 15))
        state.period_duration = minutes * 60
        state.time_remaining = state.period_duration
        state.timer_running = False
    elif action == "TIMER_ADJUST":
        seconds = int(cmd.get("seconds", 0))
        state.time_remaining = max(0, min(state.period_duration, state.time_remaining + seconds))

    # Score
    elif action == "SCORE_ADJUST":
        team = cmd.get("team")
        delta = int(cmd.get("delta", 0))
        if team == "home":
            state.home_score = max(0, state.home_score + delta)
        elif team == "away":
            state.away_score = max(0, state.away_score + delta)

    # Shots on Goal
    elif action == "SHOTS_ADJUST":
        team = cmd.get("team")
        delta = int(cmd.get("delta", 0))
        if team == "home":
            state.home_shots = max(0, state.home_shots + delta)
        elif team == "away":
            state.away_shots = max(0, state.away_shots + delta)

    # Period
    elif action == "PERIOD_SET":
        state.period = str(cmd.get("period", "1"))
    elif action == "PERIOD_NEXT":
        period_sequence = ["1", "2", "3", "OT"]
        if state.period in period_sequence:
            idx = period_sequence.index(state.period)
            if idx < len(period_sequence) - 1:
                state.period = period_sequence[idx + 1]
                state.time_remaining = state.period_duration
                state.timer_running = False

    # Team Names
    elif action == "SET_TEAM_NAMES":
        state.home_name = cmd.get("home_name", state.home_name)[:12]
        state.away_name = cmd.get("away_name", state.away_name)[:12]

    # Penalties
    elif action == "PENALTY_ADD":
        team = cmd.get("team")
        player = str(cmd.get("player", "00"))
        seconds = int(cmd.get("seconds", 120))
        pen = {"player": player, "remaining_seconds": seconds, "initial": seconds}
        if team == "home" and len(state.home_penalties) < 2:
            state.home_penalties.append(pen)
        elif team == "away" and len(state.away_penalties) < 2:
            state.away_penalties.append(pen)

    elif action == "PENALTY_REMOVE":
        team = cmd.get("team")
        idx = int(cmd.get("index", 0))
        if team == "home" and 0 <= idx < len(state.home_penalties):
            state.home_penalties.pop(idx)
        elif team == "away" and 0 <= idx < len(state.away_penalties):
            state.away_penalties.pop(idx)

    # Manual Buzzer
    elif action == "BUZZER_TRIGGER":
        state.buzzer_trigger += 1

    # Reset Game Entirely
    elif action == "GAME_RESET":
        state.home_score = 0
        state.away_score = 0
        state.home_shots = 0
        state.away_shots = 0
        state.period = "1"
        state.time_remaining = state.period_duration
        state.timer_running = False
        state.home_penalties = []
        state.away_penalties = []

    await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})

# ==========================================
# ROUTES
# ==========================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # Send initial state
    await websocket.send_text(json.dumps({"type": "STATE_UPDATE", "state": state.to_dict()}))
    try:
        while True:
            data = await websocket.receive_text()
            try:
                cmd = json.loads(data)
                await handle_command(cmd)
            except Exception as e:
                logger.error(f"Error handling message: {e}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/control", response_class=HTMLResponse)
async def get_control_page():
    with open("templates/control.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/board", response_class=HTMLResponse)
async def get_board_page():
    with open("templates/board.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/", response_class=HTMLResponse)
async def get_index_page():
    return """
    <!DOCTYPE html>
    <html lang="de">
    <head>
        <meta charset="UTF-8">
        <title>Street Hockey Scoreboard Hub</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
            h1 { font-size: 2.5rem; margin-bottom: 2rem; color: #38bdf8; text-transform: uppercase; letter-spacing: 2px; }
            .cards { display: flex; gap: 2rem; }
            .card { background: #1e293b; padding: 2rem 3rem; border-radius: 1rem; text-align: center; text-decoration: none; color: white; border: 2px solid #334155; transition: all 0.2s; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
            .card:hover { transform: translateY(-5px); border-color: #38bdf8; box-shadow: 0 15px 35px rgba(56,189,248,0.2); }
            .card h2 { margin: 0 0 0.5rem 0; font-size: 1.8rem; }
            .card p { margin: 0; color: #94a3b8; }
        </style>
    </head>
    <body>
        <h1>🏒 Street Hockey Scoreboard</h1>
        <div class="cards">
            <a class="card" href="/control" target="_blank">
                <h2>🎛️ Bedienfeld</h2>
                <p>Für den Zeitnehmer-Laptop (/control)</p>
            </a>
            <a class="card" href="/board" target="_blank">
                <h2>📺 Beamer-Anzeige</h2>
                <p>Fullscreen Großanzeige (/board)</p>
            </a>
        </div>
    </body>
    </html>
    """

