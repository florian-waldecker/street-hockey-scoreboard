"""Shared fixtures.

Every test gets a fresh ScoreboardState and redirected data/upload paths so a
run never touches the real data/ or uploads/ directories.
"""
from unittest.mock import AsyncMock

import pytest

import main as main_module


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    """`main` with a clean state singleton and all persistence pointed at tmp."""
    data_dir = tmp_path / "data"
    uploads = tmp_path / "uploads"
    for sub in ("", "sponsors", "anthems", "sfx"):
        (uploads / sub).mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(main_module, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(main_module, "TEAMS_FILE", str(data_dir / "teams.json"))
    monkeypatch.setattr(main_module, "SPONSORS_FILE", str(data_dir / "sponsors.json"))
    monkeypatch.setattr(main_module, "GAME_STATE_FILE", str(data_dir / "game_state.json"))
    monkeypatch.setattr(main_module, "UPLOAD_DIR", str(uploads))
    monkeypatch.setattr(main_module, "SPONSORS_UPLOAD_DIR", str(uploads / "sponsors"))
    monkeypatch.setattr(main_module, "ANTHEMS_UPLOAD_DIR", str(uploads / "anthems"))
    monkeypatch.setattr(main_module, "SFX_UPLOAD_DIR", str(uploads / "sfx"))

    # Fresh game state for every test.
    monkeypatch.setattr(main_module, "state", main_module.ScoreboardState())

    yield main_module


@pytest.fixture
def sent(monkeypatch, app_module):
    """Records every message handle_command / endpoints broadcast."""
    spy = AsyncMock()
    monkeypatch.setattr(app_module.manager, "broadcast", spy)

    def messages_of_type(t):
        return [c.args[0] for c in spy.await_args_list if c.args and c.args[0].get("type") == t]

    spy.messages_of_type = messages_of_type
    return spy
