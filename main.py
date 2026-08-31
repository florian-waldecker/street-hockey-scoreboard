import os
import re
import json
import logging
import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Set, List, Dict, Any, Optional, Tuple
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scoreboard")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
SPONSORS_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "sponsors")
ANTHEMS_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "anthems")
SFX_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "sfx")
DATA_DIR = os.path.join(BASE_DIR, "data")
TEAMS_FILE = os.path.join(DATA_DIR, "teams.json")
SPONSORS_FILE = os.path.join(DATA_DIR, "sponsors.json")
GAME_STATE_FILE = os.path.join(DATA_DIR, "game_state.json")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SPONSORS_UPLOAD_DIR, exist_ok=True)
os.makedirs(ANTHEMS_UPLOAD_DIR, exist_ok=True)
os.makedirs(SFX_UPLOAD_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# --- Upload limits -----------------------------------------------------------
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_PLAYERS_PER_TEAM = 40

# Goal anthem (Torhymne): one short audio clip per team, played on the boards
# when that team scores. Hard-capped at 40 s (enforced in the browser before
# upload; the byte cap here is the server-side backstop).
ALLOWED_AUDIO_EXTS = {".mp3", ".ogg", ".oga", ".wav", ".m4a", ".aac", ".webm"}
MAX_AUDIO_BYTES = 8 * 1024 * 1024  # 8 MB
MAX_ANTHEM_SECONDS = 40

# Real-hockey rule: a team can be at most two players short at once, so only the
# first two penalties per side run down while the rest wait ("stacked").
MAX_CONCURRENT_PENALTIES = 2

# ISBHF / Skaterhockey: one team time-out per team per game.
MAX_TEAM_TIMEOUTS = 1
DEFAULT_TIMEOUT_DURATION = 60

# Persist the running game every N timer ticks so a server restart mid-match
# only ever loses a few seconds of clock.
GAME_STATE_SAVE_EVERY = 5


# ==========================================
# TEXT SANITISING
# ==========================================
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ID_SANITISE = re.compile(r"[^A-Za-z0-9_-]")


def clean_text(value: Any, max_len: int = 40) -> str:
    """Strip angle brackets / control chars and trim. Defence-in-depth next to
    the HTML-escaping the frontends do on render."""
    text = str(value if value is not None else "")
    text = text.replace("<", "").replace(">", "")
    text = _CONTROL_CHARS.sub("", text)
    return text.strip()[:max_len]


_LOGO_BORDER_MODES = {"none", "solid", "glow"}


def _clean_border_mode(value: Any) -> str:
    v = str(value if value is not None else "").strip().lower()
    return v if v in _LOGO_BORDER_MODES else "none"


def _clean_border_width(value: Any) -> int:
    try:
        return max(0, min(40, int(float(value))))
    except (TypeError, ValueError):
        return 0


def sanitise_id(value: Optional[str]) -> str:
    return _ID_SANITISE.sub("", str(value or ""))[:32]


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


def save_game_state():
    try:
        tmp = GAME_STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False)
        os.replace(tmp, GAME_STATE_FILE)
    except Exception as e:
        logger.error(f"Error saving game state: {e}")


def load_game_state():
    if not os.path.exists(GAME_STATE_FILE):
        return
    try:
        with open(GAME_STATE_FILE, "r", encoding="utf-8") as f:
            state.from_dict(json.load(f))
        logger.info("Restored previous game state from disk.")
    except Exception as e:
        logger.error(f"Error loading game state: {e}")


# ==========================================
# IMAGE UPLOAD VALIDATION
# ==========================================
_SVG_BLOCKLIST = ("<script", "javascript:", "<foreignobject", "<!entity",
                  "onload=", "onerror=", "onclick=", "onmouseover=", "onbegin=")


def _svg_is_safe(data: bytes) -> bool:
    text = data.decode("utf-8", errors="ignore").lower()
    return not any(token in text for token in _SVG_BLOCKLIST)


async def read_validated_image(upload: UploadFile) -> Tuple[bytes, str]:
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext == ".jpe":
        ext = ".jpg"
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400,
                            detail=f"Dateityp '{ext or '?'}' nicht erlaubt (erlaubt: PNG, JPG, GIF, WEBP, SVG)")
    contents = await upload.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Leere Datei")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Datei zu groß (max. 5 MB)")
    if ext == ".svg" and not _svg_is_safe(contents):
        raise HTTPException(status_code=400,
                            detail="SVG enthält aktive Inhalte (Skripte/Events) und wurde abgelehnt")
    return contents, ext


async def read_validated_audio(upload: UploadFile) -> Tuple[bytes, str]:
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(status_code=400,
                            detail=f"Audioformat '{ext or '?'}' nicht erlaubt (erlaubt: MP3, OGG, WAV, M4A, AAC)")
    contents = await upload.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Leere Datei")
    if len(contents) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="Audiodatei zu groß (max. 8 MB)")
    return contents, ext


def _delete_anthem_file(anthem_url: str):
    """Best-effort removal of a stored goal-anthem clip."""
    if anthem_url and anthem_url.startswith("/uploads/anthems/"):
        path = os.path.join(ANTHEMS_UPLOAD_DIR, os.path.basename(anthem_url))
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


def _delete_sfx_file(url: str):
    """Best-effort removal of a stored sound-effect clip."""
    if url and url.startswith("/uploads/sfx/"):
        path = os.path.join(SFX_UPLOAD_DIR, os.path.basename(url))
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


# ==========================================
# SCOREBOARD STATE MODEL
# ==========================================
class ScoreboardState:
    def __init__(self):
        # Home
        self.home_name: str = "HEIM"
        self.home_logo: str = ""
        self.home_logo_border_mode: str = "none"   # none | solid | glow
        self.home_logo_border_width: int = 4
        self.home_logo_border_color: str = ""      # empty -> board falls back to team colour
        self.home_color: str = "#ef4444"
        self.home_text_color: str = "#ffffff"
        self.home_anthem: str = ""                  # goal-anthem audio URL
        self.home_score: int = 0
        self.home_shots: int = 0
        self.home_penalties: List[Dict[str, Any]] = []
        self.home_players: List[str] = []
        self.home_goals: List[Dict[str, Any]] = []

        # Away
        self.away_name: str = "GAST"
        self.away_logo: str = ""
        self.away_logo_border_mode: str = "none"
        self.away_logo_border_width: int = 4
        self.away_logo_border_color: str = ""
        self.away_color: str = "#00d2ff"
        self.away_text_color: str = "#ffffff"
        self.away_anthem: str = ""                  # goal-anthem audio URL
        self.away_score: int = 0
        self.away_shots: int = 0
        self.away_penalties: List[Dict[str, Any]] = []
        self.away_players: List[str] = []
        self.away_goals: List[Dict[str, Any]] = []

        # Game Clock
        self.period: str = "1"
        self.period_duration: int = 900  # 15 minutes default
        self.overtime_duration: int = 300  # 5 minutes default
        self.time_remaining: int = 900
        self.timer_running: bool = False

        # Break / Intermission Mode
        self.break_mode: bool = False
        self.break_duration: int = 300  # 5 minutes default
        self.break_time_remaining: int = 300
        self.break_timer_running: bool = False

        # Team time-outs (one 60 s time-out per team per game)
        self.timeout_duration: int = DEFAULT_TIMEOUT_DURATION
        self.timeout_active: bool = False
        self.timeout_team: str = ""
        self.timeout_time_remaining: int = 0
        self.home_timeouts_used: int = 0
        self.away_timeouts_used: int = 0

        # Penalty-expiry sound: one shared clip, played by the boards when an
        # active penalty is `penalty_sound_lead_seconds` away from running out
        # (0 = exactly at expiry). Survives a game reset.
        self.penalty_sound_url: str = ""
        self.penalty_sound_lead_seconds: int = 0

        # Shoot-out (tie after overtime) - kept separate from the regular score
        self.shootout_active: bool = False
        self.home_shootout: List[Dict[str, Any]] = []
        self.away_shootout: List[Dict[str, Any]] = []

        # Goalie on the floor - off = empty net (pulled goalie / playing a skater out)
        self.home_goalie: bool = True
        self.away_goalie: bool = True

        # Display options (shared with the board)
        self.show_shots: bool = False

    def to_dict(self) -> dict:
        return {
            "home_name": self.home_name,
            "home_logo": self.home_logo,
            "home_logo_border_mode": self.home_logo_border_mode,
            "home_logo_border_width": self.home_logo_border_width,
            "home_logo_border_color": self.home_logo_border_color,
            "home_color": self.home_color,
            "home_text_color": self.home_text_color,
            "home_anthem": self.home_anthem,
            "home_score": self.home_score,
            "home_shots": self.home_shots,
            "home_penalties": self.home_penalties,
            "home_players": self.home_players,
            "home_goals": self.home_goals,

            "away_name": self.away_name,
            "away_logo": self.away_logo,
            "away_logo_border_mode": self.away_logo_border_mode,
            "away_logo_border_width": self.away_logo_border_width,
            "away_logo_border_color": self.away_logo_border_color,
            "away_color": self.away_color,
            "away_text_color": self.away_text_color,
            "away_anthem": self.away_anthem,
            "away_score": self.away_score,
            "away_shots": self.away_shots,
            "away_penalties": self.away_penalties,
            "away_players": self.away_players,
            "away_goals": self.away_goals,

            "period": self.period,
            "period_duration": self.period_duration,
            "overtime_duration": self.overtime_duration,
            "time_remaining": self.time_remaining,
            "timer_running": self.timer_running,

            "break_mode": self.break_mode,
            "break_duration": self.break_duration,
            "break_time_remaining": self.break_time_remaining,
            "break_timer_running": self.break_timer_running,

            "timeout_duration": self.timeout_duration,
            "timeout_active": self.timeout_active,
            "timeout_team": self.timeout_team,
            "timeout_time_remaining": self.timeout_time_remaining,
            "home_timeouts_used": self.home_timeouts_used,
            "away_timeouts_used": self.away_timeouts_used,

            "penalty_sound_url": self.penalty_sound_url,
            "penalty_sound_lead_seconds": self.penalty_sound_lead_seconds,

            "shootout_active": self.shootout_active,
            "home_shootout": self.home_shootout,
            "away_shootout": self.away_shootout,

            "home_goalie": self.home_goalie,
            "away_goalie": self.away_goalie,

            "show_shots": self.show_shots,
        }

    def from_dict(self, data: Dict[str, Any]):
        for key, value in data.items():
            if key in self.to_dict():
                setattr(self, key, value)
        # Never resume a running clock automatically after a restart -
        # the timekeeper decides when play continues.
        self.timer_running = False
        self.break_timer_running = False
        self.timeout_active = False
        self.timeout_team = ""
        self.timeout_time_remaining = 0

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


def _full_clock_for_period() -> int:
    """Full clock length for the period currently selected."""
    return state.overtime_duration if state.period == "OT" else state.period_duration


def _auto_advance_period():
    """The game clock has run out: automatically line up the next third and
    reload a full clock (still stopped). Stops before overtime - whether it
    goes to OT, a shoot-out or is simply over is the timekeeper's call."""
    nxt = {"1": "2", "2": "3"}.get(state.period)
    if nxt:
        state.period = nxt
        state.time_remaining = state.period_duration


def _tick_penalties(penalties: List[Dict[str, Any]], lead: int = 0) -> bool:
    """Run down the first MAX_CONCURRENT_PENALTIES active penalties and drop
    any that have expired. Remaining penalties stay queued (stacked).

    Returns True when at least one penalty has just crossed its
    "expiry sound" mark (`lead` seconds before it runs out), so the caller
    can fire the penalty-expiry sound exactly once per penalty."""
    fired = False
    for p in penalties[:MAX_CONCURRENT_PENALTIES]:
        rem = int(p.get("remaining_seconds", 0)) - 1
        p["remaining_seconds"] = rem
        if not p.get("snd_fired") and rem <= max(0, lead):
            p["snd_fired"] = True
            fired = True
    penalties[:] = [p for p in penalties if int(p.get("remaining_seconds", 0)) > 0]
    return fired


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
            state.timeout_active = False
    elif action == "TIMER_PAUSE":
        state.timer_running = False
    elif action == "TIMER_TOGGLE":
        if state.time_remaining > 0:
            state.timer_running = not state.timer_running
            if state.timer_running:
                state.break_mode = False
                state.break_timer_running = False
                state.timeout_active = False
    elif action == "TIMER_RESET":
        state.timer_running = False
        state.time_remaining = _full_clock_for_period()
    elif action in ("TIMER_SET_DURATION", "PERIOD_DURATION_SET"):
        if "duration" in cmd:
            state.period_duration = int(cmd["duration"])
        elif "minutes" in cmd:
            state.period_duration = int(cmd["minutes"]) * 60
        state.time_remaining = state.period_duration
        state.timer_running = False
    elif action in ("OVERTIME_DURATION_SET", "OT_DURATION_SET"):
        if "duration" in cmd:
            state.overtime_duration = int(cmd["duration"])
        elif "minutes" in cmd:
            state.overtime_duration = int(cmd["minutes"]) * 60
        state.overtime_duration = max(30, min(3600, state.overtime_duration))
        # Apply straight away if we're sitting in a stopped overtime.
        if state.period == "OT" and not state.timer_running:
            state.time_remaining = state.overtime_duration
    elif action == "TIMER_ADJUST":
        seconds = int(cmd.get("seconds", 0))
        state.time_remaining = max(0, min(state.period_duration, state.time_remaining + seconds))
    elif action == "TIMER_SET_REMAINING":
        seconds = int(cmd.get("seconds", 0))
        state.time_remaining = max(0, min(state.period_duration, seconds))
        state.timer_running = False

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
            # Ending the break resets the intermission clock to its full duration.
            state.break_timer_running = False
            state.break_time_remaining = state.break_duration

    elif action in ("BREAK_TOGGLE", "BREAK_TIMER_TOGGLE"):
        state.break_mode = True
        state.timer_running = False
        state.break_timer_running = not state.break_timer_running

    elif action == "BREAK_SET_DURATION":
        duration = int(cmd.get("duration", 300))
        state.break_duration = duration
        # Only reload the pending clock when a break isn't already running,
        # so adjusting the length here never starts the break by itself.
        if not state.break_timer_running:
            state.break_time_remaining = duration

    elif action == "BREAK_END":
        state.break_mode = False
        state.break_timer_running = False
        state.break_time_remaining = state.break_duration

    # --- Score Adjustments & Goals ---
    elif action == "SCORE_ADJUST":
        team = cmd.get("team")
        delta = int(cmd.get("delta", 0))
        scorer = clean_text(cmd.get("scorer", ""), 60)

        # A registered goal stops the game clock.
        if delta > 0:
            state.timer_running = False

        if team == "home":
            if delta < 0 and state.home_goals:
                state.home_goals.pop()
            state.home_score = max(0, state.home_score + delta)
            if delta > 0:
                elapsed = state.period_duration - state.time_remaining
                cur_time_str = format_game_time(elapsed)
                state.home_goals.append({
                    "player": scorer or "Tor",
                    "time": cur_time_str,
                    "period": state.period
                })
                state.home_goals = state.home_goals[-100:]
                await manager.broadcast({
                    "type": "goal",
                    "team": "home",
                    "team_name": state.home_name,
                    "scorer": scorer,
                    "team_logo": state.home_logo,
                    "anthem": state.home_anthem,
                    "color": state.home_color,
                    "text_color": state.home_text_color,
                    "empty_net": not state.away_goalie,
                })
        elif team == "away":
            if delta < 0 and state.away_goals:
                state.away_goals.pop()
            state.away_score = max(0, state.away_score + delta)
            if delta > 0:
                elapsed = state.period_duration - state.time_remaining
                cur_time_str = format_game_time(elapsed)
                state.away_goals.append({
                    "player": scorer or "Tor",
                    "time": cur_time_str,
                    "period": state.period
                })
                state.away_goals = state.away_goals[-100:]
                await manager.broadcast({
                    "type": "goal",
                    "team": "away",
                    "team_name": state.away_name,
                    "scorer": scorer,
                    "team_logo": state.away_logo,
                    "anthem": state.away_anthem,
                    "color": state.away_color,
                    "text_color": state.away_text_color,
                    "empty_net": not state.home_goalie,
                })

    elif action == "GOAL_REMOVE":
        team = cmd.get("team")
        idx = int(cmd.get("index", 0))
        if team == "home" and 0 <= idx < len(state.home_goals):
            state.home_goals.pop(idx)
            state.home_score = max(0, state.home_score - 1)
        elif team == "away" and 0 <= idx < len(state.away_goals):
            state.away_goals.pop(idx)
            state.away_score = max(0, state.away_score - 1)

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
        prev_period = state.period
        state.period = clean_text(cmd.get("period", "1"), 4)
        # Entering overtime loads a fresh (stopped) overtime clock.
        if state.period == "OT" and prev_period != "OT":
            state.time_remaining = state.overtime_duration
            state.timer_running = False

    # --- Goalie on the floor (empty-net toggle) ---
    elif action == "GOALIE_SET":
        team = cmd.get("team")
        active = bool(cmd.get("active", True))
        if team == "home":
            state.home_goalie = active
        elif team == "away":
            state.away_goalie = active

    # --- Display options ---
    elif action == "DISPLAY_SET":
        if "show_shots" in cmd:
            state.show_shots = bool(cmd["show_shots"])

    # --- Team Time-out ---
    elif action == "TIMEOUT_START":
        team = cmd.get("team")
        if team in ("home", "away") and not state.timeout_active:
            used = state.home_timeouts_used if team == "home" else state.away_timeouts_used
            if used < MAX_TEAM_TIMEOUTS:
                state.timeout_active = True
                state.timeout_team = team
                state.timeout_time_remaining = state.timeout_duration
                state.timer_running = False
                state.break_mode = False
                state.break_timer_running = False
                if team == "home":
                    state.home_timeouts_used += 1
                else:
                    state.away_timeouts_used += 1

    elif action == "TIMEOUT_END":
        state.timeout_active = False
        state.timeout_team = ""
        state.timeout_time_remaining = 0

    elif action == "TIMEOUT_RESET_COUNT":
        state.home_timeouts_used = 0
        state.away_timeouts_used = 0

    elif action == "TIMEOUT_SET_DURATION":
        seconds = int(cmd.get("seconds", cmd.get("duration", DEFAULT_TIMEOUT_DURATION)))
        state.timeout_duration = max(5, min(600, seconds))
        # If a time-out is already running, leave its clock alone; the new
        # duration takes effect the next time a team calls a time-out.

    # --- Penalty-expiry sound ---
    elif action == "PENALTY_SOUND_SET":
        if "lead_seconds" in cmd:
            state.penalty_sound_lead_seconds = max(0, min(30, int(cmd.get("lead_seconds", 0))))

    elif action == "PENALTY_SOUND_TEST":
        if state.penalty_sound_url:
            await manager.broadcast({
                "type": "penalty_sound",
                "sound": state.penalty_sound_url,
                "lead_seconds": state.penalty_sound_lead_seconds,
                "test": True,
            })

    # --- Shoot-out ---
    elif action == "SHOOTOUT_MODE_SET":
        state.shootout_active = bool(cmd.get("active", True))

    elif action == "SHOOTOUT_ATTEMPT":
        team = cmd.get("team")
        entry = {
            "scored": bool(cmd.get("scored", False)),
            "player": clean_text(cmd.get("player", ""), 40),
        }
        if team == "home":
            state.home_shootout = (state.home_shootout + [entry])[-20:]
        elif team == "away":
            state.away_shootout = (state.away_shootout + [entry])[-20:]

    elif action == "SHOOTOUT_UNDO":
        team = cmd.get("team")
        if team == "home" and state.home_shootout:
            state.home_shootout.pop()
        elif team == "away" and state.away_shootout:
            state.away_shootout.pop()

    # --- Team Settings ---
    elif action in ("TEAM_SET", "SET_TEAM_DETAILS"):
        team = cmd.get("team")
        if team == "home":
            if "name" in cmd: state.home_name = clean_text(cmd["name"])
            if "logo" in cmd: state.home_logo = clean_text(cmd["logo"], 300)
            if "logo_border_mode" in cmd: state.home_logo_border_mode = _clean_border_mode(cmd["logo_border_mode"])
            if "logo_border_width" in cmd: state.home_logo_border_width = _clean_border_width(cmd["logo_border_width"])
            if "logo_border_color" in cmd: state.home_logo_border_color = clean_text(cmd["logo_border_color"], 40)
            if "color" in cmd: state.home_color = clean_text(cmd["color"], 40)
            if "text_color" in cmd: state.home_text_color = clean_text(cmd["text_color"], 40)
            if "anthem" in cmd: state.home_anthem = clean_text(cmd["anthem"], 300)
            if "players" in cmd: state.home_players = _clean_players(cmd["players"])
        elif team == "away":
            if "name" in cmd: state.away_name = clean_text(cmd["name"])
            if "logo" in cmd: state.away_logo = clean_text(cmd["logo"], 300)
            if "logo_border_mode" in cmd: state.away_logo_border_mode = _clean_border_mode(cmd["logo_border_mode"])
            if "logo_border_width" in cmd: state.away_logo_border_width = _clean_border_width(cmd["logo_border_width"])
            if "logo_border_color" in cmd: state.away_logo_border_color = clean_text(cmd["logo_border_color"], 40)
            if "color" in cmd: state.away_color = clean_text(cmd["color"], 40)
            if "text_color" in cmd: state.away_text_color = clean_text(cmd["text_color"], 40)
            if "anthem" in cmd: state.away_anthem = clean_text(cmd["anthem"], 300)
            if "players" in cmd: state.away_players = _clean_players(cmd["players"])
        else:
            if "home_name" in cmd: state.home_name = clean_text(cmd["home_name"])
            if "away_name" in cmd: state.away_name = clean_text(cmd["away_name"])
            if "home_color" in cmd: state.home_color = clean_text(cmd["home_color"], 40)
            if "away_color" in cmd: state.away_color = clean_text(cmd["away_color"], 40)
            if "home_text_color" in cmd: state.home_text_color = clean_text(cmd["home_text_color"], 40)
            if "away_text_color" in cmd: state.away_text_color = clean_text(cmd["away_text_color"], 40)

    # --- Penalties ---
    elif action == "PENALTY_ADD":
        team = cmd.get("team")
        player = clean_text(cmd.get("player", "00"), 40) or "00"
        seconds = max(1, min(3600, int(cmd.get("seconds", 120))))
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
        state.timeout_active = False
        state.timeout_team = ""
        state.timeout_time_remaining = 0
        state.home_timeouts_used = 0
        state.away_timeouts_used = 0
        state.shootout_active = False
        state.home_shootout = []
        state.away_shootout = []
        state.home_goalie = True
        state.away_goalie = True

    # Broadcast state to all clients (Control & Board) and persist.
    await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})
    save_game_state()


def _clean_players(players: Any) -> List[str]:
    if not isinstance(players, list):
        return []
    cleaned = [clean_text(p) for p in players]
    return [p for p in cleaned if p][:MAX_PLAYERS_PER_TEAM]


# ==========================================
# BACKGROUND TIMER LOOP
# ==========================================
async def timer_loop():
    tick = 0
    while True:
        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            break
        tick += 1
        state_changed = False

        # 1. Main Game Timer
        if state.timer_running and not state.break_mode and not state.timeout_active:
            if state.time_remaining > 0:
                state.time_remaining -= 1
                state_changed = True

                lead = int(state.penalty_sound_lead_seconds or 0)
                pen_sound = _tick_penalties(state.home_penalties, lead)
                pen_sound = _tick_penalties(state.away_penalties, lead) or pen_sound
                if pen_sound and state.penalty_sound_url:
                    await manager.broadcast({
                        "type": "penalty_sound",
                        "sound": state.penalty_sound_url,
                        "lead_seconds": lead,
                    })

                if state.time_remaining == 0:
                    state.timer_running = False
                    _auto_advance_period()
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
            else:
                state.break_timer_running = False
                state_changed = True

        # 3. Team Time-out (always runs once started, fixed length)
        if state.timeout_active:
            if state.timeout_time_remaining > 0:
                state.timeout_time_remaining -= 1
                state_changed = True
            if state.timeout_time_remaining <= 0:
                state.timeout_active = False
                state.timeout_team = ""

        if state_changed:
            await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})
            if tick % GAME_STATE_SAVE_EVERY == 0:
                save_game_state()


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_game_state()
    task = asyncio.create_task(timer_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        save_game_state()


app = FastAPI(title="Street Hockey Scoreboard Hub", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


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
    logo_border_mode: str = Form("none"),
    logo_border_width: str = Form("4"),
    logo_border_color: str = Form(""),
    players_json: str = Form("[]"),
    anthem_seconds: str = Form(""),
    remove_anthem: str = Form(""),
    logo_file: Optional[UploadFile] = File(None),
    logo: Optional[UploadFile] = File(None),
    anthem_file: Optional[UploadFile] = File(None)
):
    teams = load_saved_teams()
    target_id = sanitise_id(id or team_id)

    try:
        players = json.loads(players_json)
    except Exception:
        players = []
    players = _clean_players(players)

    logo_url = ""
    anthem_url = ""
    if target_id:
        existing = next((t for t in teams if t["id"] == target_id), None)
        if existing:
            logo_url = existing.get("logo_url", "")
            anthem_url = existing.get("anthem_url", "")
    else:
        target_id = str(uuid.uuid4())[:8]

    actual_file = logo_file or logo
    if actual_file and actual_file.filename:
        contents, ext = await read_validated_image(actual_file)
        filename = f"{target_id}{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as buffer:
            buffer.write(contents)
        logo_url = f"/uploads/{filename}"

    # --- Goal anthem (Torhymne) ---
    if str(remove_anthem).strip().lower() in ("1", "true", "yes", "on"):
        _delete_anthem_file(anthem_url)
        anthem_url = ""
    elif anthem_file and anthem_file.filename:
        try:
            client_secs = float(anthem_seconds)
        except (TypeError, ValueError):
            client_secs = 0.0
        if client_secs > MAX_ANTHEM_SECONDS + 0.5:
            raise HTTPException(status_code=400,
                                detail=f"Torhymne zu lang ({client_secs:.0f}s, max. {MAX_ANTHEM_SECONDS}s)")
        contents, ext = await read_validated_audio(anthem_file)
        _delete_anthem_file(anthem_url)  # drop the previous clip (extension may change)
        filename = f"{target_id}{ext}"
        filepath = os.path.join(ANTHEMS_UPLOAD_DIR, filename)
        with open(filepath, "wb") as buffer:
            buffer.write(contents)
        anthem_url = f"/uploads/anthems/{filename}"

    team_entry = {
        "id": target_id,
        "name": clean_text(name),
        "color": clean_text(color, 40),
        "text_color": clean_text(text_color, 40),
        "logo_url": logo_url,
        "anthem_url": anthem_url,
        "logo_border_mode": _clean_border_mode(logo_border_mode),
        "logo_border_width": _clean_border_width(logo_border_width),
        "logo_border_color": clean_text(logo_border_color, 40),
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
    team_id = sanitise_id(team_id)
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

    _delete_anthem_file(team.get("anthem_url", ""))

    teams = [t for t in teams if t["id"] != team_id]
    save_teams_db(teams)
    return {"status": "ok"}

@app.get("/api/penalty-sound")
async def get_penalty_sound():
    return {
        "url": state.penalty_sound_url,
        "lead_seconds": state.penalty_sound_lead_seconds,
    }

@app.post("/api/penalty-sound")
async def upload_penalty_sound(
    lead_seconds: str = Form(""),
    audio_seconds: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    if file and file.filename:
        try:
            client_secs = float(audio_seconds)
        except (TypeError, ValueError):
            client_secs = 0.0
        if client_secs > 20.5:  # a penalty cue should be short
            raise HTTPException(status_code=400,
                                detail=f"Strafen-Sound zu lang ({client_secs:.0f}s, max. 20s)")
        contents, ext = await read_validated_audio(file)
        _delete_sfx_file(state.penalty_sound_url)
        filename = f"penalty_sound{ext}"
        with open(os.path.join(SFX_UPLOAD_DIR, filename), "wb") as buffer:
            buffer.write(contents)
        state.penalty_sound_url = f"/uploads/sfx/{filename}"

    if str(lead_seconds).strip() != "":
        try:
            state.penalty_sound_lead_seconds = max(0, min(30, int(float(lead_seconds))))
        except (TypeError, ValueError):
            pass

    save_game_state()
    await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})
    return {"url": state.penalty_sound_url, "lead_seconds": state.penalty_sound_lead_seconds}

@app.delete("/api/penalty-sound")
async def delete_penalty_sound():
    _delete_sfx_file(state.penalty_sound_url)
    state.penalty_sound_url = ""
    save_game_state()
    await manager.broadcast({"type": "STATE_UPDATE", "state": state.to_dict()})
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

    contents, ext = await read_validated_image(actual_file)

    sponsors = load_sponsors()
    sponsor_id = str(uuid.uuid4())[:8]
    filename = f"sponsor_{sponsor_id}{ext}"
    filepath = os.path.join(SPONSORS_UPLOAD_DIR, filename)

    with open(filepath, "wb") as buffer:
        buffer.write(contents)

    url = f"/uploads/sponsors/{filename}"
    entry = {
        "id": sponsor_id,
        "name": clean_text(name) or f"Sponsor {len(sponsors)+1}",
        "url": url,
        "image_url": url
    }
    sponsors.append(entry)
    save_sponsors_db(sponsors)
    await manager.broadcast({"type": "SPONSORS_UPDATE"})
    return JSONResponse(entry)

@app.delete("/api/sponsors/{sponsor_id}")
async def delete_sponsor(sponsor_id: str):
    sponsor_id = sanitise_id(sponsor_id)
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
        await manager.broadcast({"type": "SPONSORS_UPDATE"})
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
            except WebSocketDisconnect:
                raise
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

@app.get("/board2", response_class=HTMLResponse)
async def get_board2_page():
    # Redesigned broadcast-style scoreboard (draft). Same WebSocket/state feed
    # as /board - run both side by side to compare.
    path = os.path.join(BASE_DIR, "templates", "board2.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/board3", response_class=HTMLResponse)
async def get_board3_page():
    # Like /board2 but with the top (scoreboard) and middle (scorers) panels swapped.
    path = os.path.join(BASE_DIR, "templates", "board3.html")
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
