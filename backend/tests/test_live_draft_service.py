from app import live_draft_service as svc


def _base_payload():
    return {
        "current_pick": 45,
        "user_slot": 4,
        "teams": 12,
        "drafted_player_ids": ["a", "b"],
        "user_roster_player_ids": ["u1"],
        "available_player_ids": ["x", "y", "z"],
        "include_debug": True,
        "top_n": 10,
    }


def test_apply_pick_updates_drafted_and_available_and_advances_pick():
    payload = _base_payload()
    res = svc.apply_pick_to_payload(payload, picked_player_id="y", advance_pick=True)

    assert res["ok"] is True
    state = res["state"]
    assert "y" in state["drafted_player_ids"]
    assert "y" not in state["available_player_ids"]
    assert state["current_pick"] == 46


def test_apply_pick_updates_user_roster_when_requested():
    payload = _base_payload()
    res = svc.apply_pick_to_payload(
        payload,
        picked_player_id="new_user_pick",
        apply_to_user_roster=True,
        advance_pick=False,
    )

    assert res["ok"] is True
    state = res["state"]
    assert "new_user_pick" in state["user_roster_player_ids"]
    assert state["current_pick"] == 45


def test_duplicate_pick_is_safe_noop_for_drafted_list():
    payload = _base_payload()
    res = svc.apply_pick_to_payload(payload, picked_player_id="a", advance_pick=False)

    assert res["ok"] is True
    state = res["state"]
    assert state["drafted_player_ids"].count("a") == 1
    assert res["live_draft_debug"]["duplicate_pick"] is True


def test_invalid_pick_returns_clean_error():
    payload = _base_payload()
    res = svc.apply_pick_to_payload(payload, picked_player_id="")

    assert res["ok"] is False
    assert res["error"] == "Invalid live draft operation"
    assert "picked_player_id is required" in res["details"]


def test_recompute_after_pick_returns_state_and_recommendation(monkeypatch):
    payload = _base_payload()

    def fake_get_packaged(_payload):
        return {
            "ok": True,
            "recommendation": {
                "draft_context": {"current_pick": _payload["current_pick"]},
                "headline_recommendation": {"player_id": "p1"},
            },
        }

    monkeypatch.setattr(svc.api_contracts, "get_packaged_recommendation_from_request", fake_get_packaged)

    res = svc.recompute_after_pick(
        payload=payload,
        picked_player_id="z",
        apply_to_user_roster=False,
        advance_pick=True,
    )

    assert res["ok"] is True
    assert "state" in res
    assert "recommendation" in res
    assert res["state"]["current_pick"] == 46
    assert res["recommendation"]["draft_context"]["current_pick"] == 46