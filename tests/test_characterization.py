"""Characterization tests: they pin down how the scoreboard behaves *today*.

Written before the tech-debt refactor so any behavioural drift shows up as a
failing test. Where a test documents a known wart (e.g. overtime clamp) it says
so - the point is "unchanged", not "correct".
"""
import asyncio

import pytest


def run(coro):
    return asyncio.run(coro)


def cmd(app, action, **kw):
    run(app.handle_command({"action": action, **kw}))


# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------
class TestStateModel:
    def test_to_dict_roundtrips_through_from_dict(self, app_module):
        s = app_module.ScoreboardState()
        s.home_name = "Falcons"
        s.home_score = 3
        s.away_penalties = [{"player": "7", "remaining_seconds": 90, "initial": 120}]
        s.period = "OT"

        restored = app_module.ScoreboardState()
        restored.from_dict(s.to_dict())

        assert restored.home_name == "Falcons"
        assert restored.home_score == 3
        assert restored.away_penalties == [{"player": "7", "remaining_seconds": 90, "initial": 120}]
        assert restored.period == "OT"

    def test_from_dict_forces_clocks_stopped(self, app_module):
        s = app_module.ScoreboardState()
        payload = s.to_dict()
        payload.update(
            timer_running=True,
            break_timer_running=True,
            timeout_active=True,
            timeout_team="home",
            timeout_time_remaining=42,
        )
        s.from_dict(payload)
        assert s.timer_running is False
        assert s.break_timer_running is False
        assert s.timeout_active is False
        assert s.timeout_team == ""
        assert s.timeout_time_remaining == 0

    def test_from_dict_ignores_unknown_keys(self, app_module):
        s = app_module.ScoreboardState()
        s.from_dict({"home_score": 5, "totally_unknown": 99})
        assert s.home_score == 5
        assert not hasattr(s, "totally_unknown")

    def test_to_dict_key_set_is_stable(self, app_module):
        # The board/control frontends read these keys by name.
        keys = set(app_module.ScoreboardState().to_dict())
        for expected in (
            "home_name", "away_name", "home_score", "away_score",
            "period", "time_remaining", "timer_running",
            "home_penalties", "away_penalties", "home_goals", "away_goals",
            "break_mode", "timeout_active", "shootout_active",
            "home_goalie", "away_goalie", "show_shots",
            "penalty_sound_url", "penalty_sound_lead_seconds",
        ):
            assert expected in keys


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
class TestHelpers:
    @pytest.mark.parametrize("secs,out", [(0, "00:00"), (5, "00:05"), (65, "01:05"), (900, "15:00"), (-3, "00:00")])
    def test_format_game_time(self, app_module, secs, out):
        assert app_module.format_game_time(secs) == out

    def test_clean_text_strips_markup_and_trims(self, app_module):
        assert app_module.clean_text("  <b>Falcons</b>  ") == "bFalcons/b"
        assert app_module.clean_text("x" * 100) == "x" * 40
        assert app_module.clean_text("x" * 100, 60) == "x" * 60
        assert app_module.clean_text(None) == ""

    def test_sanitise_id_keeps_only_id_chars(self, app_module):
        assert app_module.sanitise_id("abc-123_XYZ") == "abc-123_XYZ"
        assert app_module.sanitise_id("../../etc/passwd") == "etcpasswd"
        assert app_module.sanitise_id(None) == ""

    def test_clean_players_filters_and_caps(self, app_module):
        assert app_module._clean_players(["7", "", "  ", "9"]) == ["7", "9"]
        assert len(app_module._clean_players([str(i) for i in range(100)])) == app_module.MAX_PLAYERS_PER_TEAM
        assert app_module._clean_players("not a list") == []

    def test_svg_blocklist(self, app_module):
        assert app_module._svg_is_safe(b"<svg><rect/></svg>") is True
        assert app_module._svg_is_safe(b"<svg><script>alert(1)</script></svg>") is False
        assert app_module._svg_is_safe(b'<svg onload="x()"></svg>') is False


# ---------------------------------------------------------------------------
# Penalty ticking
# ---------------------------------------------------------------------------
class TestPenalties:
    def test_only_two_penalties_run_concurrently(self, app_module):
        pens = [{"player": str(i), "remaining_seconds": 100, "initial": 100} for i in range(3)]
        app_module._tick_penalties(pens)
        assert [p["remaining_seconds"] for p in pens] == [99, 99, 100]

    def test_expired_penalties_are_dropped(self, app_module):
        pens = [{"player": "7", "remaining_seconds": 1, "initial": 120}]
        app_module._tick_penalties(pens)
        assert pens == []

    def test_lead_sound_fires_once_per_penalty(self, app_module):
        pens = [{"player": "7", "remaining_seconds": 3, "initial": 120}]
        assert app_module._tick_penalties(pens, lead=2) is True   # 3 -> 2, hits lead
        assert app_module._tick_penalties(pens, lead=2) is False  # already fired
        assert pens[0]["snd_fired"] is True

    def test_penalty_add_clamps_seconds(self, app_module):
        app = app_module
        cmd(app, "PENALTY_ADD", team="home", player="7", seconds=99999)
        assert app.state.home_penalties[0]["remaining_seconds"] == 3600
        cmd(app, "PENALTY_ADD", team="home", player="8", seconds=0)
        assert app.state.home_penalties[1]["remaining_seconds"] == 1

    def test_penalty_remove_by_index(self, app_module):
        app = app_module
        cmd(app, "PENALTY_ADD", team="away", player="7", seconds=120)
        cmd(app, "PENALTY_ADD", team="away", player="9", seconds=120)
        cmd(app, "PENALTY_REMOVE", team="away", index=0)
        assert [p["player"] for p in app.state.away_penalties] == ["9"]


# ---------------------------------------------------------------------------
# Score & goals
# ---------------------------------------------------------------------------
class TestScore:
    def test_score_adjust_adds_goal_and_stops_clock(self, app_module, sent):
        app = app_module
        app.state.timer_running = True
        cmd(app, "SCORE_ADJUST", team="home", delta=1, scorer="7 Meier")
        assert app.state.home_score == 1
        assert app.state.timer_running is False
        assert app.state.home_goals[-1]["player"] == "7 Meier"
        assert sent.messages_of_type("goal")

    def test_score_never_goes_negative(self, app_module):
        app = app_module
        cmd(app, "SCORE_ADJUST", team="away", delta=-1)
        assert app.state.away_score == 0

    def test_negative_delta_pops_last_goal(self, app_module):
        app = app_module
        cmd(app, "SCORE_ADJUST", team="home", delta=1, scorer="A")
        cmd(app, "SCORE_ADJUST", team="home", delta=1, scorer="B")
        cmd(app, "SCORE_ADJUST", team="home", delta=-1)
        assert app.state.home_score == 1
        assert [g["player"] for g in app.state.home_goals] == ["A"]

    def test_goal_remove_by_index_decrements_score(self, app_module):
        app = app_module
        cmd(app, "SCORE_ADJUST", team="away", delta=1, scorer="A")
        cmd(app, "SCORE_ADJUST", team="away", delta=1, scorer="B")
        cmd(app, "GOAL_REMOVE", team="away", index=0)
        assert app.state.away_score == 1
        assert [g["player"] for g in app.state.away_goals] == ["B"]

    def test_goal_carries_empty_net_flag(self, app_module, sent):
        app = app_module
        app.state.away_goalie = False  # home scores into an empty net
        cmd(app, "SCORE_ADJUST", team="home", delta=1)
        goal = sent.messages_of_type("goal")[-1]
        assert goal["empty_net"] is True


# ---------------------------------------------------------------------------
# Timer / period
# ---------------------------------------------------------------------------
class TestTimer:
    def test_timer_toggle_needs_time_on_the_clock(self, app_module):
        app = app_module
        app.state.time_remaining = 0
        cmd(app, "TIMER_TOGGLE")
        assert app.state.timer_running is False
        app.state.time_remaining = 10
        cmd(app, "TIMER_TOGGLE")
        assert app.state.timer_running is True

    def test_timer_reset_uses_full_clock_for_period(self, app_module):
        app = app_module
        app.state.period = "OT"
        app.state.overtime_duration = 300
        app.state.time_remaining = 12
        cmd(app, "TIMER_RESET")
        assert app.state.time_remaining == 300

    def test_period_set_to_ot_loads_overtime_clock(self, app_module):
        app = app_module
        app.state.overtime_duration = 240
        cmd(app, "PERIOD_SET", period="OT")
        assert app.state.time_remaining == 240
        assert app.state.timer_running is False

    def test_auto_advance_period_1_to_2(self, app_module):
        app = app_module
        app.state.period = "1"
        app.state.period_duration = 900
        app._auto_advance_period()
        assert app.state.period == "2"
        assert app.state.time_remaining == 900

    def test_auto_advance_stops_at_period_3(self, app_module):
        app = app_module
        app.state.period = "3"
        app._auto_advance_period()
        assert app.state.period == "3"


# ---------------------------------------------------------------------------
# Time-outs
# ---------------------------------------------------------------------------
class TestTimeout:
    def test_timeout_start_consumes_the_one_allowance(self, app_module):
        app = app_module
        cmd(app, "TIMEOUT_START", team="home")
        assert app.state.timeout_active is True
        assert app.state.home_timeouts_used == 1

        cmd(app, "TIMEOUT_END")
        cmd(app, "TIMEOUT_START", team="home")  # second one refused
        assert app.state.timeout_active is False

    def test_timeout_reset_count_reopens_allowance(self, app_module):
        app = app_module
        cmd(app, "TIMEOUT_START", team="away")
        cmd(app, "TIMEOUT_END")
        cmd(app, "TIMEOUT_RESET_COUNT")
        cmd(app, "TIMEOUT_START", team="away")
        assert app.state.timeout_active is True


# ---------------------------------------------------------------------------
# Game reset
# ---------------------------------------------------------------------------
class TestGameReset:
    def test_game_reset_clears_play_but_keeps_teams_and_sound(self, app_module):
        app = app_module
        app.state.home_name = "Falcons"
        app.state.home_color = "#123456"
        app.state.penalty_sound_url = "/uploads/sfx/penalty_sound.mp3"
        cmd(app, "SCORE_ADJUST", team="home", delta=1, scorer="A")
        cmd(app, "PENALTY_ADD", team="home", player="7", seconds=120)
        cmd(app, "GAME_RESET")

        assert app.state.home_score == 0
        assert app.state.home_goals == []
        assert app.state.home_penalties == []
        assert app.state.period == "1"
        assert app.state.home_name == "Falcons"
        assert app.state.home_color == "#123456"
        assert app.state.penalty_sound_url == "/uploads/sfx/penalty_sound.mp3"


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------
class TestHttp:
    @pytest.fixture
    def client(self, app_module):
        from fastapi.testclient import TestClient
        return TestClient(app_module.app)

    def test_index_ok(self, client):
        assert client.get("/").status_code == 200

    def test_board_and_control_pages_render(self, client):
        assert client.get("/board").status_code == 200
        assert "<!DOCTYPE html>" in client.get("/board").text or "<!doctype html>" in client.get("/board").text.lower()
        assert client.get("/control").status_code == 200

    @pytest.mark.parametrize("page,css,js", [
        ("/board", "/static/board.css", "/static/board.js"),
        ("/control", "/static/control.css", "/static/control.js"),
    ])
    def test_pages_link_their_extracted_assets(self, client, page, css, js):
        body = client.get(page).text
        assert css in body and js in body
        assert "<style>" not in body and "<script>" not in body  # nothing left inline

    @pytest.mark.parametrize("asset,ctype", [
        ("/static/board.css", "text/css"),
        ("/static/board.js", "text/javascript"),
        ("/static/control.css", "text/css"),
        ("/static/control.js", "text/javascript"),
    ])
    def test_static_assets_serve_with_a_script_safe_mime(self, client, asset, ctype):
        # nosniff is set globally, so a .js served as text/plain would not execute.
        r = client.get(asset)
        assert r.status_code == 200
        assert r.headers["content-type"].split(";")[0] == ctype

    def test_dropped_board_routes_are_gone(self, client):
        assert client.get("/board2").status_code == 404
        assert client.get("/board3").status_code == 404

    def test_team_create_list_delete_roundtrip(self, client):
        r = client.post("/api/teams", data={"name": "Falcons", "color": "#ef4444"})
        assert r.status_code == 200
        tid = r.json()["id"]
        assert any(t["id"] == tid for t in client.get("/api/teams").json())
        assert client.delete(f"/api/teams/{tid}").status_code == 200
        assert not any(t["id"] == tid for t in client.get("/api/teams").json())

    def test_security_headers_present(self, client):
        h = client.get("/").headers
        assert h["X-Content-Type-Options"] == "nosniff"
        assert h["Referrer-Policy"] == "no-referrer"
