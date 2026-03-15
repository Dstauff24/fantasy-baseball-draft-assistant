import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.live_draft_routes as routes
from app.players_service import load_ranked_player_catalog


def test_load_ranked_player_catalog_returns_rows_with_expected_keys():
    players = load_ranked_player_catalog()
    assert players, "expected non-empty real player catalog"

    sample = players[0]
    expected_keys = {
        "player_id",
        "player_name",
        "team",
        "positions",
        "adp",
        "adp_rank",
        "projected_points",
        "engine_rank",
        "derived_rank",
        "vorp",
        "draft_score",
        "survival_probability",
        "take_now_edge",
        "roster_fit_score",
        "team_need_pressure",
        "tier_cliff_score",
        "path_score",
    }
    assert expected_keys.issubset(sample.keys())


def test_load_ranked_player_catalog_populates_vorp_and_draft_score():
    players = load_ranked_player_catalog()
    assert players, "expected non-empty real player catalog"

    vorp_populated = [p for p in players if p.get("vorp") is not None]
    draft_score_populated = [p for p in players if p.get("draft_score") is not None]

    assert vorp_populated, "expected at least one player with populated vorp"
    assert draft_score_populated, "expected at least one player with populated draft_score"


def test_players_route_returns_ok_true_and_players_list():
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    res = client.get("/api/players")
    assert res.status_code == 200
    body = res.json()
    assert body.get("ok") is True
    assert isinstance(body.get("players"), list)
    assert len(body["players"]) > 0
