"""
Verify that documented example payloads remain aligned with actual route behavior.
Monkeypatches service layer to isolate route/contract concerns only.
"""
import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI
from fastapi.testclient import TestClient
import app.live_draft_routes as routes


_app = FastAPI()
_app.include_router(routes.router)
client = TestClient(_app)


BASE_STATE = {
    "current_pick": 45,
    "user_slot": 4,
    "teams": 12,
    "drafted_player_ids": ["shohei-ohtani__dh-sp", "aaron-judge__of"],
    "user_roster_player_ids": ["paul-skenes__sp", "austin-riley__3b"],
    "available_player_ids": None,
    "top_n": 10,
    "include_debug": False,
}

APPLY_PICK_PAYLOAD = {
    "state": BASE_STATE,
    "picked_player_id": "julio-rodriguez__of",
    "picked_by_slot": 5,
    "apply_to_user_roster": False,
    "advance_pick": True,
    "include_recommendation": False,
}


def _fake_recommendation(payload):
    return {
        "ok": True,
        "recommendation": {
            "draft_context": {"current_pick": payload.get("current_pick")},
            "headline_recommendation": {"player_id": "x"},
        },
    }


def _fake_apply_pick(payload):
    return {
        "ok": True,
        "state": {**BASE_STATE, "current_pick": 46},
        "recommendation": {"headline_recommendation": {"player_id": "x"}},
    }


def test_recommendation_route_accepts_documented_payload(monkeypatch):
    monkeypatch.setattr(routes, "get_recommendation_for_payload", _fake_recommendation)
    res = client.post("/api/recommendation", json=BASE_STATE)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "recommendation" in body


def test_apply_pick_route_accepts_documented_payload(monkeypatch):
    monkeypatch.setattr(routes, "apply_pick_operation", _fake_apply_pick)
    res = client.post("/api/apply-pick", json=APPLY_PICK_PAYLOAD)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "state" in body


def test_recommendation_after_pick_accepts_documented_payload(monkeypatch):
    monkeypatch.setattr(routes, "apply_pick_operation", _fake_apply_pick)
    payload = {**APPLY_PICK_PAYLOAD, "include_recommendation": False}
    res = client.post("/api/recommendation-after-pick", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True


def test_missing_state_returns_error(monkeypatch):
    monkeypatch.setattr(routes, "apply_pick_operation", _fake_apply_pick)
    res = client.post("/api/apply-pick", json={"picked_player_id": "x"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "error" in body


def test_missing_picked_player_id_returns_error(monkeypatch):
    monkeypatch.setattr(routes, "apply_pick_operation", _fake_apply_pick)
    res = client.post("/api/apply-pick", json={"state": BASE_STATE})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "error" in body