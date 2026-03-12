import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI
from fastapi.testclient import TestClient
import app.live_draft_routes as routes


app = FastAPI()
app.include_router(routes.router)
client = TestClient(app)


def test_recommendation_route_shape(monkeypatch):
    def fake_get_recommendation(payload):
        return {"ok": True, "recommendation": {"draft_context": {"current_pick": payload["current_pick"]}}}

    monkeypatch.setattr(routes, "get_recommendation_for_payload", fake_get_recommendation)

    payload = {
        "current_pick": 45,
        "user_slot": 4,
        "teams": 12,
        "drafted_player_ids": [],
        "user_roster_player_ids": [],
    }
    res = client.post("/api/recommendation", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["recommendation"]["draft_context"]["current_pick"] == 45


def test_apply_pick_route_delegates(monkeypatch):
    def fake_apply_pick_operation(payload):
        return {"ok": True, "state": {"current_pick": 46}, "echo": payload.get("picked_player_id")}

    monkeypatch.setattr(routes, "apply_pick_operation", fake_apply_pick_operation)

    payload = {
        "state": {
            "current_pick": 45,
            "user_slot": 4,
            "teams": 12,
            "drafted_player_ids": [],
            "user_roster_player_ids": [],
        },
        "picked_player_id": "x",
        "include_recommendation": False,
    }
    res = client.post("/api/apply-pick", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["state"]["current_pick"] == 46
    assert body["echo"] == "x"


def test_recommendation_after_pick_forces_recompute(monkeypatch):
    def fake_apply_pick_operation(payload):
        return {"ok": True, "forced": payload.get("include_recommendation") is True}

    monkeypatch.setattr(routes, "apply_pick_operation", fake_apply_pick_operation)

    payload = {
        "state": {
            "current_pick": 45,
            "user_slot": 4,
            "teams": 12,
            "drafted_player_ids": [],
            "user_roster_player_ids": [],
        },
        "picked_player_id": "y",
        "include_recommendation": False,  # should be overridden
    }
    res = client.post("/api/recommendation-after-pick", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["forced"] is True