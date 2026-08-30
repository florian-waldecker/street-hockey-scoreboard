import os
import json
import logging
import asyncio
import uuid
import shutil
from typing import Set, List, Dict, Any, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scoreboard")

app = FastAPI(title="Street Hockey Scoreboard Hub")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
SPONSORS_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "sponsors")
DATA_DIR = os.path.join(BASE_DIR, "data")
TEAMS_FILE = os.path.join(DATA_DIR, "teams.json")
SPONSORS_FILE = os.path.join(DATA_DIR, "sponsors.json")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SPONSORS_UPLOAD_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# ==========================================
# PERSISTENCE HELPERS
# ==========================================
def load_saved_teams() -> List[Dict[str, Any]]:
    if not os.path.exists(TEAMS_FILE):
        return []
    try:
        with open(TEAMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading teams: {e}")
        return []

def save_teams_db(teams: List[Dict[str, Any]]):
    try:
        with open(TEAMS_FILE, "w", encoding="utf-8") as f:
            json.dump(teams, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving teams: {e}")

def load_sponsors() -> List[Dict[str, Any]]:
    if not os.path.exists(SPONSORS_FILE):
        return []
    try:
        with open(SPONSORS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for s in data:
                if "url" not in s and "image_url" in s:
                    s["url"] = s["image_url"]
            return data
    except Exception as e:
        logger.error(f"Error loading sponsors: {e}")
        return []

def save_sponsors_db(sponsors: List[Dict[str, Any]]):
    try:
        for s in sponsors:
            if "url" not in s and "image_url" in s:
                s["url"] = s["image_url"]
        with open(SPONSORS_FILE, "w", encoding="utf-8") as f:
            json.dump(sponsors, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving sponsors: {e}")


# ==========================================
# SCOREBOARD STATE MODEL
# ==========================================
class ScoreboardState:
    def __init__(self):
        # Home
        self.home_name: str = "HEIM"
        self.home_logo: str = ""
        self.home_color: str = "#ef4444"
        self.home_text_color: str = "#ffffff"
        self.home_score: int = 0
        self.home_shots: int = 0
        self.home_penalties: List[Dict[str, Any]] = []
        self.home_players: List[str] = []
        self.home_goals: List[Dict[str, Any]] = []

        # Away
        self.away_name: str = "GAST"
        self.away_logo: str = ""
        self.away_color: str = "#00d2ff"
        self.away_text_color: str = "#ffffff"
        self.away_score: int = 0
        self.away_shots: int = 0
        self.away_penalties: List[Dict[str, Any]] = []
        self.away_players: List[str] = []
        self.away_goals: List[Dict[str, Any]] = []

        # Game Clock
        self.period: str = "1"
        self.period_duration: int = 900  # 15 minutes default
        self.time_remaining: int = 900
        self.timer_running: bool = False

        # Break / Intermission Mode
        self.break_mode: bool = False
        self.break_duration: int = 300  # 5 minutes default
        self.break_time_remaining: int = 300
        self.break_timer_running: bool = False

        # Triggers
        self.buzzer_trigger: int = 0

    def to_dict(self) -> dict:
        return {
            "home_name": self.home_name,
            "home_logo": self.home_logo,
            "home_color": self.home_color,
            "home_text_color": self.home_text_color,
            "home_score": self.home_score,
            "home_shots": self.home_shots,
            "home_penalties": self.home_penalties,
            "home_players": self.home_players,
            "home_goals": self.home_goals,

            "away_name": self.away_name,
            "away_logo": self.away_logo,
            "away_color": self.away_color,
            "away_text_color": self.away_text_color,
            "away_score": self.away_score,
            "away_shots": self.away_shots,
            "away_penalties": self.away_penalties,
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

            "buzzer_trigger": self.buzzer_trigger
        }

state = ScoreboardState()


# ==========================================
# WEBSOCKET MANAGER
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
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception:
                dead_connections.add(connection)
        for dead in dead_connections:
            self.active_connections.discard(dead)

manager = ConnectionManager()


def format_game_time(seconds: int) -> str:
    m = max(0, seconds) // 60
    s = max(0, seconds) % 60
    return f"{m:02d}:{s:02d}"


# ==========================================
# COMMAND HANDLER
# ==========================================
async def handle_command(cmd: dict):
    action = cmd.get("action")

    # --- Game Timer ---
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
    elif action in ("TIMER_SET_DURATION", "PERIOD_DURATION_SET"):
        if "duration" in cmd:
            state.period_duration = int(cmd["duration"])
        elif "minutes" in cmd:
            state.period_duration = int(cmd["minutes"]) * 60
        state.time_remaining = state.period_duration
        state.timer_running = False
    elif action == "TIMER_ADJUST":
        seconds = int(cmd.get("seconds", 0))
        state.time_remaining = max(0, min(state.period_duration, state.time_remaining + seconds))

    # --- Break / Intermission Timer ---
    elif action in ("BREAK_START", "BREAK_MODE_SET"):
        active = cmd.get("active", True)
        state.break_mode = bool(active)
        if state.break_mode:
            state.timer_running = False
            if "duration" in cmd:
                state.break_duration = int(cmd["duration"])
                state.break_time_remaining = state.break_duration
            elif "minutes" in cmd:
                state.break_duration = int(cmd["minutes"]) * 60
                state.break_time_remaining = state.break_duration
        else:
            state.break_timer_running = False

    elif action in ("BREAK_TOGGLE", "BREAK_TIMER_TOGGLE"):
        state.break_mode = True
        state.timer_running = False
        state.break_timer_running = not state.break_timer_running

    elif action == "BREAK_SET_DURATION":
        duration = int(cmd.get("duration", 300))
        state.break_duration = duration
        state.break_time_remaining = duration
        state.break_mode = True

    elif action == "BREAK_END":
        state.break_mode = False
        state.break_timer_running = False

    # --- Score Adjustments & Goals ---
    elif action == "SCORE_ADJUST":
        team = cmd.get("team")
        delta = int(cmd.get("delta", 0))
        scorer = cmd.get("scorer", "")

        if team == "home":
            state.home_score = max(0, state.home_score + delta)
            if delta > 0:
                elapsed = state.period_duration - state.time_remaining
                cur_time_str = format_game_time(elapsed)
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
                    "team_logo": state.home_logo,
                    "color": state.home_color,
                    "text_color": state.home_text_color
                })
        elif team == "away":
            state.away_score = max(0, state.away_score + delta)
            if delta > 0:
                elapsed = state.period_duration - state.time_remaining
                cur_time_str = format_game_time(elapsed)
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
                    "team_logo": state.away_logo,
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

    # --- Shots on Goal ---
    elif action == "SHOTS_ADJUST":
        team = cmd.get("team")
        delta = int(cmd.get("delta", 0))
        if team == "home":
            state.home_shots = max(0, state.home_shots + delta)
        elif team == "away":
            state.away_shots = max(0, state.away_shots + delta)

    # --- Period ---
    elif action == "PERIOD_SET":
        state.period = str(cmd.get("period", "1"))

    # --- Team Settings ---
    elif action in ("TEAM_SET", "SET_TEAM_DETAILS"):
        team = cmd.get("team")
        if team == "home":
            if "name" in cmd: state.home_name = cmd["name"][:40]
            if "logo" in cmd: state.home_logo = cmd["logo"]
            if "color" in cmd: state.home_color = cmd["color"]
            if "text_color" in cmd: state.home_text_color = cmd["text_color"]
            if "players" in cmd: state.home_players = cmd["players"]
        elif team == "away":
            if "name" in cmd: state.away_name = cmd["name"][:40]
            if "logo" in cmd: state.away_logo = cmd["logo"]
            if "color" in cmd: state.away_color = cmd["color"]
            if "text_color" in cmd: state.away_text_color = cmd["text_color"]
            if "players" in cmd: state.away_players = cmd["players"]
        else:
            if "home_name" in cmd: state.home_name = cmd["home_name"][:40]
            if "away_name" in cmd: state.away_name = cmd["away_name"][:40]
            if "home_color" in cmd: state.home_color = cmd["home_color"]
            if "away_color" in cmd: state.away_color = cmd["away_color"]
            if "home_text_color" in cmd: state.home_text_color = cmd["home_text_color"]
            if "away_text_color" in cmd: state.away_text_color = cmd["away_text_color"]

    # --- Penalties ---
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

    # --- Buzzer Trigger ---
    elif action == "BUZZER_TRIGGER":
        state.buzzer_trigger += 1
        await manager.broadcast({"type": "buzzer"})

    # --- Game Reset ---
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

    # Broadcast state to all clients (Control & Board)
    await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})


# ==========================================
# BACKGROUND TIMER LOOP
# ==========================================
async def timer_loop():
    while True:
        await asyncio.sleep(1.0)
        state_changed = False

        # 1. Main Game Timer
        if state.timer_running and not state.break_mode:
            if state.time_remaining > 0:
                state.time_remaining -= 1
                state_changed = True

                # Home penalties count down
                expired_home = []
                for p in state.home_penalties[:2]:
                    if p["remaining_seconds"] > 0:
                        p["remaining_seconds"] -= 1
                    else:
                        expired_home.append(p)
                for p in expired_home:
                    if p in state.home_penalties:
                        state.home_penalties.remove(p)

                # Away penalties count down
                expired_away = []
                for p in state.away_penalties[:2]:
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
                    await manager.broadcast({"type": "buzzer"})
            else:
                state.timer_running = False
                state_changed = True

        # 2. Break / Intermission Timer
        if state.break_timer_running and state.break_mode:
            if state.break_time_remaining > 0:
                state.break_time_remaining -= 1
                state_changed = True
                if state.break_time_remaining == 0:
                    state.break_timer_running = False
                    state.buzzer_trigger += 1
                    await manager.broadcast({"type": "buzzer"})
            else:
                state.break_timer_running = False
                state_changed = True

        if state_changed:
            await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(timer_loop())


# ==========================================
# REST API: TEAMS & SPONSORS
# ==========================================
@app.get("/api/teams")
async def get_teams():
    return load_saved_teams()

@app.post("/api/teams")
async def save_or_update_team(
    id: Optional[str] = Form(None),
    team_id: Optional[str] = Form(None),
    name: str = Form(...),
    color: str = Form("#ef4444"),
    text_color: str = Form("#ffffff"),
    players_json: str = Form("[]"),
    logo_file: Optional[UploadFile] = File(None),
    logo: Optional[UploadFile] = File(None)
):
    teams = load_saved_teams()
    target_id = id or team_id

    try:
        players = json.loads(players_json)
    except Exception:
        players = []

    logo_url = ""
    if target_id:
        existing = next((t for t in teams if t["id"] == target_id), None)
        if existing:
            logo_url = existing.get("logo_url", "")
    else:
        target_id = str(uuid.uuid4())[:8]

    actual_file = logo_file or logo
    if actual_file and actual_file.filename:
        ext = os.path.splitext(actual_file.filename)[1]
        filename = f"{target_id}{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(actual_file.file, buffer)
        logo_url = f"/uploads/{filename}"

    team_entry = {
        "id": target_id,
        "name": name.strip(),
        "color": color,
        "text_color": text_color,
        "logo_url": logo_url,
        "players": players
    }

    existing_idx = next((i for i, t in enumerate(teams) if t["id"] == target_id), None)
    if existing_idx is not None:
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

@app.get("/api/sponsors")
async def get_sponsors():
    return load_sponsors()

@app.post("/api/sponsors")
async def add_sponsor(
    name: str = Form(""),
    file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None)
):
    actual_file = file or image
    if not actual_file or not actual_file.filename:
        raise HTTPException(status_code=400, detail="Keine Datei hochgeladen")

    sponsors = load_sponsors()
    sponsor_id = str(uuid.uuid4())[:8]
    ext = os.path.splitext(actual_file.filename)[1]
    filename = f"sponsor_{sponsor_id}{ext}"
    filepath = os.path.join(SPONSORS_UPLOAD_DIR, filename)

    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(actual_file.file, buffer)

    url = f"/uploads/sponsors/{filename}"
    entry = {
        "id": sponsor_id,
        "name": name.strip() or f"Sponsor {len(sponsors)+1}",
        "url": url,
        "image_url": url
    }
    sponsors.append(entry)
    save_sponsors_db(sponsors)
    return JSONResponse(entry)

@app.delete("/api/sponsors/{sponsor_id}")
async def delete_sponsor(sponsor_id: str):
    sponsors = load_sponsors()
    sp = next((s for s in sponsors if s["id"] == sponsor_id), None)
    if sp:
        url = sp.get("url") or sp.get("image_url", "")
        if url.startswith("/uploads/sponsors/"):
            filename = os.path.basename(url)
            path = os.path.join(SPONSORS_UPLOAD_DIR, filename)
            if os.path.exists(path):
                try: os.remove(path)
                except Exception: pass
        sponsors = [s for s in sponsors if s["id"] != sponsor_id]
        save_sponsors_db(sponsors)
    return {"status": "ok"}


# ==========================================
# WEBSOCKET & PAGES ROUTING
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
                logger.error(f"Error handling websocket command: {e}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/control", response_class=HTMLResponse)
async def get_control_page():
    path = os.path.join(BASE_DIR, "templates", "control.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/board", response_class=HTMLResponse)
async def get_board_page():
    path = os.path.join(BASE_DIR, "templates", "board.html")
    with open(path, "r", encoding="utf-8") as f:
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
            body { font-family: sans-serif; background: #0b0f19; color: #fff; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
            h1 { margin-bottom: 2rem; }
            .links { display: flex; gap: 1.5rem; }
            a { background: #2563eb; color: #fff; padding: 1rem 2rem; border-radius: 8px; text-decoration: none; font-size: 1.2rem; font-weight: bold; }
            a:hover { background: #1d4ed8; }
        </style>
    </head>
    <body>
        <h1>🏒 Street Hockey Scoreboard Hub</h1>
        <div class="links">
            <a href="/control" target="_blank">🎛️ Zeitnehmer Bedienfeld (/control)</a>
            <a href="/board" target="_blank">📺 Großanzeige Scoreboard (/board)</a>
        </div>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
