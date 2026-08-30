import asyncio
import json
import logging
import os
import shutil
import uuid
from typing import Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Scoreboard")

app = FastAPI(title="Street Hockey Scoreboard")

# Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
SPONSORS_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "sponsors")
DATA_DIR = os.path.join(BASE_DIR, "data")
STATIC_DIR = os.path.join(BASE_DIR, "static")

TEAMS_FILE = os.path.join(DATA_DIR, "teams.json")
SPONSORS_FILE = os.path.join(DATA_DIR, "sponsors.json")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SPONSORS_UPLOAD_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Static mounts
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Helper: Team Database Management
def load_saved_teams() -> list:
    if os.path.exists(TEAMS_FILE):
        try:
            with open(TEAMS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_teams_db(teams: list):
    with open(TEAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(teams, f, ensure_ascii=False, indent=2)

# Helper: Sponsors Database Management
def load_sponsors() -> list:
    if os.path.exists(SPONSORS_FILE):
        try:
            with open(SPONSORS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_sponsors_db(sponsors: list):
    with open(SPONSORS_FILE, "w", encoding="utf-8") as f:
        json.dump(sponsors, f, ensure_ascii=False, indent=2)

# ==========================================
# STATE & DATA MODEL
# ==========================================
class ScoreboardState:
    def __init__(self):
        # Teams
        self.home_name = "BREMERHAVEN WHALES"
        self.home_logo = ""
        self.home_color = "#ef4444"
        self.home_text_color = "#ffffff"
        self.home_score = 0
        self.home_shots = 0
        self.home_players = [] # [{'number': '10', 'name': 'M. Mustermann'}]
        self.home_goals = []   # [{'player': '#10 Mustermann', 'time': '04:12', 'period': '1'}]

        self.away_name = "WOLFSBURG WOLFRIDERS"
        self.away_logo = ""
        self.away_color = "#00e5ff"
        self.away_text_color = "#ffffff"
        self.away_score = 0
        self.away_shots = 0
        self.away_players = []
        self.away_goals = []
        
        # Period & Game Timer
        self.period = "1"
        self.period_duration = 15 * 60
        self.time_remaining = self.period_duration
        self.timer_running = False

        # Break / Intermission Timer
        self.break_mode = False
        self.break_duration = 10 * 60
        self.break_time_remaining = self.break_duration
        self.break_timer_running = False

        # Penalties: list of active penalty slots
        self.home_penalties = []
        self.away_penalties = []
        
        # Audio Buzzer Event Flag
        self.buzzer_trigger = 0

    def to_dict(self):
        return {
            "home_name": self.home_name,
            "home_logo": self.home_logo,
            "home_color": self.home_color,
            "home_text_color": self.home_text_color,
            "home_score": self.home_score,
            "home_shots": self.home_shots,
            "home_players": self.home_players,
            "home_goals": self.home_goals,

            "away_name": self.away_name,
            "away_logo": self.away_logo,
            "away_color": self.away_color,
            "away_text_color": self.away_text_color,
            "away_score": self.away_score,
            "away_shots": self.away_shots,
            "away_players": self.away_players,
            "away_goals": self.away_goals,

            "period": self.period,
            "period_duration": self.period_duration,
            "time_remaining": self.time_remaining,
            "timer_running": self.timer_running,

            "break_mode": self.break_mode,
            "break_duration": self.break_duration,
            "break_time_remaining": self.break_time_remaining,
            "break_timer_running": self.break_timer_running,

            "home_penalties": self.home_penalties,
            "away_penalties": self.away_penalties,
            "buzzer_trigger": self.buzzer_trigger,
            "sponsors": load_sponsors()
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
# BACKGROUND TIMERS LOOP (Asyncio)
# ==========================================
async def timer_loop():
    while True:
        await asyncio.sleep(1.0)
        state_changed = False

        # 1. Main Game Timer Loop
        if state.timer_running and not state.break_mode:
            if state.time_remaining > 0:
                state.time_remaining -= 1
                state_changed = True
                
                # Update Home Penalties
                expired_home = []
                active_count = 0
                for p in state.home_penalties:
                    if active_count < 2:
                        active_count += 1
                        if p["remaining_seconds"] > 0:
                            p["remaining_seconds"] -= 1
                        else:
                            expired_home.append(p)
                for p in expired_home:
                    if p in state.home_penalties:
                        state.home_penalties.remove(p)

                # Update Away Penalties
                expired_away = []
                active_count = 0
                for p in state.away_penalties:
                    if active_count < 2:
                        active_count += 1
                        if p["remaining_seconds"] > 0:
                            p["remaining_seconds"] -= 1
                        else:
                            expired_away.append(p)
                for p in expired_away:
                    if p in state.away_penalties:
                        state.away_penalties.remove(p)

                if state.time_remaining == 0:
                    state.timer_running = False
                    state.buzzer_trigger += 1

            else:
                state.timer_running = False
                state_changed = True

        # 2. Break / Intermission Timer Loop
        if state.break_timer_running and state.break_mode:
            if state.break_time_remaining > 0:
                state.break_time_remaining -= 1
                state_changed = True
                if state.break_time_remaining == 0:
                    state.break_timer_running = False
                    state.buzzer_trigger += 1
            else:
                state.break_timer_running = False
                state_changed = True

        if state_changed:
            await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(timer_loop())

def format_game_time(seconds: int) -> str:
    m = seconds // 60
    s = seconds % 60
    return f"{m:02d}:{s:02d}"

# ==========================================
# COMMAND HANDLER
# ==========================================
async def handle_command(cmd: dict):
    action = cmd.get("action")

    # Game Timer
    if action == "TIMER_START":
        if state.time_remaining > 0:
            state.timer_running = True
            state.break_mode = False
            state.break_timer_running = False
    elif action == "TIMER_PAUSE":
        state.timer_running = False
    elif action == "TIMER_TOGGLE":
        if state.time_remaining > 0:
            state.timer_running = not state.timer_running
            if state.timer_running:
                state.break_mode = False
                state.break_timer_running = False
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

    # Break Timer Controls
    elif action == "BREAK_START":
        minutes = int(cmd.get("minutes", 10))
        state.break_duration = minutes * 60
        state.break_time_remaining = state.break_duration
        state.break_mode = True
        state.break_timer_running = True
        state.timer_running = False
    elif action == "BREAK_TOGGLE":
        state.break_mode = True
        state.break_timer_running = not state.break_timer_running
        state.timer_running = False
    elif action == "BREAK_END":
        state.break_mode = False
        state.break_timer_running = False

    # Score & Goal Event Trigger
    elif action == "SCORE_ADJUST":
        team = cmd.get("team")
        delta = int(cmd.get("delta", 0))
        scorer = cmd.get("scorer", "")

        if team == "home":
            state.home_score = max(0, state.home_score + delta)
            if delta > 0:
                cur_time_str = format_game_time(state.period_duration - state.time_remaining)
                state.home_goals.append({
                    "player": scorer or "Tor",
                    "time": cur_time_str,
                    "period": state.period
                })
                await manager.broadcast({
                    "type": "goal",
                    "team": "home",
                    "team_name": state.home_name,
                    "scorer": scorer,
                    "logo_url": state.home_logo,
                    "color": state.home_color,
                    "text_color": state.home_text_color
                })
        elif team == "away":
            state.away_score = max(0, state.away_score + delta)
            if delta > 0:
                cur_time_str = format_game_time(state.period_duration - state.time_remaining)
                state.away_goals.append({
                    "player": scorer or "Tor",
                    "time": cur_time_str,
                    "period": state.period
                })
                await manager.broadcast({
                    "type": "goal",
                    "team": "away",
                    "team_name": state.away_name,
                    "scorer": scorer,
                    "logo_url": state.away_logo,
                    "color": state.away_color,
                    "text_color": state.away_text_color
                })

    elif action == "GOAL_REMOVE":
        team = cmd.get("team")
        idx = int(cmd.get("index", 0))
        if team == "home" and 0 <= idx < len(state.home_goals):
            state.home_goals.pop(idx)
        elif team == "away" and 0 <= idx < len(state.away_goals):
            state.away_goals.pop(idx)

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

    # Team Names, Card Colors & Text Colors
    elif action == "SET_TEAM_DETAILS":
        if "home_name" in cmd: state.home_name = cmd["home_name"][:40]
        if "away_name" in cmd: state.away_name = cmd["away_name"][:40]
        if "home_color" in cmd: state.home_color = cmd["home_color"]
        if "away_color" in cmd: state.away_color = cmd["away_color"]
        if "home_text_color" in cmd: state.home_text_color = cmd["home_text_color"]
        if "away_text_color" in cmd: state.away_text_color = cmd["away_text_color"]

    elif action == "ASSIGN_SAVED_TEAM":
        team_slot = cmd.get("slot")
        team_id = cmd.get("team_id")
        teams = load_saved_teams()
        selected = next((t for t in teams if t["id"] == team_id), None)
        if selected:
            if team_slot == "home":
                state.home_name = selected["name"]
                state.home_logo = selected.get("logo_url", "")
                state.home_players = selected.get("players", [])
                if "color" in selected and selected["color"]:
                    state.home_color = selected["color"]
                if "text_color" in selected and selected["text_color"]:
                    state.home_text_color = selected["text_color"]
            elif team_slot == "away":
                state.away_name = selected["name"]
                state.away_logo = selected.get("logo_url", "")
                state.away_players = selected.get("players", [])
                if "color" in selected and selected["color"]:
                    state.away_color = selected["color"]
                if "text_color" in selected and selected["text_color"]:
                    state.away_text_color = selected["text_color"]

    # Penalties
    elif action == "PENALTY_ADD":
        team = cmd.get("team")
        player = str(cmd.get("player", "00"))
        seconds = int(cmd.get("seconds", 120))
        pen = {"player": player, "remaining_seconds": seconds, "initial": seconds}
        if team == "home":
            state.home_penalties.append(pen)
        elif team == "away":
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
        state.home_goals = []
        state.away_goals = []
        state.period = "1"
        state.time_remaining = state.period_duration
        state.timer_running = False
        state.break_mode = False
        state.break_timer_running = False
        state.home_penalties = []
        state.away_penalties = []

    await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})

# ==========================================
# REST API: TEAM & SPONSOR MANAGEMENT
# ==========================================
@app.get("/api/teams")
async def get_teams():
    return load_saved_teams()

@app.post("/api/teams")
async def save_or_update_team(
    team_id: str = Form(None),
    name: str = Form(...),
    color: str = Form("#ef4444"),
    text_color: str = Form("#ffffff"),
    players_json: str = Form("[]"),
    logo: UploadFile = File(None),
    keep_logo: str = Form(None)
):
    teams = load_saved_teams()
    logo_url = keep_logo or ""

    try:
        players = json.loads(players_json)
    except Exception:
        players = []

    if team_id:
        existing_idx = next((i for i, t in enumerate(teams) if t["id"] == team_id), None)
        if existing_idx is None:
            raise HTTPException(status_code=404, detail="Team nicht gefunden")
        target_id = team_id
        if not logo_url and teams[existing_idx].get("logo_url"):
            logo_url = teams[existing_idx]["logo_url"]
    else:
        target_id = str(uuid.uuid4())[:8]

    if logo and logo.filename:
        ext = os.path.splitext(logo.filename)[1]
        filename = f"{target_id}{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(logo.file, buffer)
        logo_url = f"/uploads/{filename}"

    team_entry = {
        "id": target_id,
        "name": name.strip(),
        "color": color,
        "text_color": text_color,
        "logo_url": logo_url,
        "players": players
    }

    if team_id:
        teams[existing_idx] = team_entry
    else:
        teams.append(team_entry)

    save_teams_db(teams)
    return JSONResponse(team_entry)

@app.delete("/api/teams/{team_id}")
async def delete_team(team_id: str):
    teams = load_saved_teams()
    team = next((t for t in teams if t["id"] == team_id), None)
    if not team:
        raise HTTPException(status_code=404, detail="Team nicht gefunden")
    
    if team.get("logo_url") and team["logo_url"].startswith("/uploads/"):
        filename = os.path.basename(team["logo_url"])
        path = os.path.join(UPLOAD_DIR, filename)
        if os.path.exists(path):
            try: os.remove(path)
            except Exception: pass

    teams = [t for t in teams if t["id"] != team_id]
    save_teams_db(teams)
    return {"status": "ok"}

# Sponsors API
@app.get("/api/sponsors")
async def get_sponsors():
    return load_sponsors()

@app.post("/api/sponsors")
async def add_sponsor(
    name: str = Form(""),
    image: UploadFile = File(...)
):
    sponsors = load_sponsors()
    sponsor_id = str(uuid.uuid4())[:8]
    ext = os.path.splitext(image.filename)[1]
    filename = f"sponsor_{sponsor_id}{ext}"
    filepath = os.path.join(SPONSORS_UPLOAD_DIR, filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(image.file, buffer)
    
    entry = {
        "id": sponsor_id,
        "name": name.strip() or f"Sponsor {len(sponsors)+1}",
        "image_url": f"/uploads/sponsors/{filename}"
    }
    sponsors.append(entry)
    save_sponsors_db(sponsors)
    await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})
    return JSONResponse(entry)

@app.delete("/api/sponsors/{sponsor_id}")
async def delete_sponsor(sponsor_id: str):
    sponsors = load_sponsors()
    sp = next((s for s in sponsors if s["id"] == sponsor_id), None)
    if sp:
        if sp.get("image_url") and sp["image_url"].startswith("/uploads/sponsors/"):
            filename = os.path.basename(sp["image_url"])
            path = os.path.join(SPONSORS_UPLOAD_DIR, filename)
            if os.path.exists(path):
                try: os.remove(path)
                except Exception: pass
        sponsors = [s for s in sponsors if s["id"] != sponsor_id]
        save_sponsors_db(sponsors)
        await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})
    return {"status": "ok"}

# ==========================================
# ROUTES
# ==========================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
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
    with open(os.path.join(BASE_DIR, "templates/control.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.get("/board", response_class=HTMLResponse)
async def get_board_page():
    with open(os.path.join(BASE_DIR, "templates/board.html"), "r", encoding="utf-8") as f:
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
