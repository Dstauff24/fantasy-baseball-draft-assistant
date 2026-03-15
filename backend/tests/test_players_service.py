import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.live_draft_routes as routes
from app.players_service import load_ranked_player_catalog


def test_load_ranked_player_catalog_returns_rows_with_expected_global_keys():
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
        "value_vs_adp",
        "metrics_scope",
        "vorp",
        "draft_score",
        "survival_probability",
        "take_now_edge",
        "roster_fit_score",
        "team_need_pressure",
        "tier_cliff_score",
        "sp_cliff_multiplier",
        "cliff_label",
        "cliff_raw_drop",
        "path_score",
        "live_context_note",
    }
    assert expected_keys.issubset(sample.keys())
    assert sample["metrics_scope"] == "global_board"


def test_global_mode_excludes_live_context_metrics_by_default():
    players = load_ranked_player_catalog()
    assert players, "expected non-empty real player catalog"

    sample = players[0]
    assert sample.get("vorp") is None
    assert sample.get("draft_score") is None
    assert sample.get("take_now_edge") is None
    assert sample.get("live_context_note") == "excluded_in_global_mode"


def test_live_context_mode_populates_vorp_and_draft_score():
    players = load_ranked_player_catalog(include_live_context=True)
    assert players, "expected non-empty real player catalog"

    vorp_populated = [p for p in players if p.get("vorp") is not None]
    draft_score_populated = [p for p in players if p.get("draft_score") is not None]
    assert vorp_populated, "expected at least one player with populated vorp"
    assert draft_score_populated, "expected at least one player with populated draft_score"


def test_sp_players_expose_cliff_debug_fields_in_live_context_mode():
    players = load_ranked_player_catalog(include_live_context=True)
    sp_players = [p for p in players if "SP" in (p.get("positions") or [])]
    assert sp_players, "expected SP players in catalog"

    with_cliff = [p for p in sp_players if p.get("cliff_label") in {"minor", "strong", "elite"}]
    assert with_cliff, "expected at least one SP with detected cliff label"
    assert any((p.get("sp_cliff_multiplier") or 1.0) > 1.0 for p in with_cliff)


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


def test_players_route_can_include_live_context_metrics():
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    res = client.get("/api/players?include_live_context=true")
    assert res.status_code == 200
    body = res.json()
    assert body.get("ok") is True
    assert len(body.get("players", [])) > 0
    assert body["players"][0]["metrics_scope"] == "global_plus_live_context"
