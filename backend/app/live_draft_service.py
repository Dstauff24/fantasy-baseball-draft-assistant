from __future__ import annotations

from copy import deepcopy
from typing import Any

from app import api_contracts
from app.request_builders import parse_recommendation_request, RecommendationRequestValidationError


def _error(details: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "Invalid live draft operation",
        "details": details,
    }


def normalize_live_draft_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize frontend payload into the Phase 5 request contract shape.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    out = deepcopy(payload)
    out.setdefault("drafted_player_ids", [])
    out.setdefault("user_roster_player_ids", [])
    out.setdefault("available_player_ids", None)
    out.setdefault("include_debug", False)
    out.setdefault("top_n", 10)

    if "current_pick" in out and int(out["current_pick"]) < 1:
        raise ValueError("current_pick must be >= 1")

    return out


def get_recommendation_for_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Stateless recommendation call using existing Phase 5 contract.
    """
    try:
        normalized = normalize_live_draft_payload(payload)
    except Exception as exc:
        return _error(str(exc) or repr(exc))

    return api_contracts.get_packaged_recommendation_from_request(normalized)


def apply_pick_to_payload(
    payload: dict[str, Any],
    picked_player_id: str,
    picked_by_slot: int | None = None,
    apply_to_user_roster: bool = False,
    advance_pick: bool = True,
) -> dict[str, Any]:
    """
    Apply one board update to a stateless payload.
    """
    try:
        state = normalize_live_draft_payload(payload)
    except Exception as exc:
        return _error(str(exc) or repr(exc))

    if not isinstance(picked_player_id, str) or not picked_player_id.strip():
        return _error("picked_player_id is required")

    picked_player_id = picked_player_id.strip()

    drafted = list(state.get("drafted_player_ids") or [])
    user_roster = list(state.get("user_roster_player_ids") or [])
    available = state.get("available_player_ids", None)

    before_pick = int(state.get("current_pick", 1))

    # safe no-op for duplicate pick
    duplicate = picked_player_id in drafted
    if not duplicate:
        drafted.append(picked_player_id)

    if isinstance(available, list):
        available = [pid for pid in available if pid != picked_player_id]

    if apply_to_user_roster and picked_player_id not in user_roster:
        user_roster.append(picked_player_id)

    current_pick = before_pick + 1 if advance_pick else before_pick
    if current_pick < 1:
        return _error("current_pick must be >= 1")

    state["drafted_player_ids"] = drafted
    state["user_roster_player_ids"] = user_roster
    state["available_player_ids"] = available
    state["current_pick"] = current_pick

    # optional future/debug metadata; ignored by Phase 5 parser if unused
    if picked_by_slot is not None:
        state["_last_picked_by_slot"] = picked_by_slot

    result: dict[str, Any] = {"ok": True, "state": state}
    if state.get("include_debug"):
        result["live_draft_debug"] = {
            "picked_player_id": picked_player_id,
            "picked_by_slot": picked_by_slot,
            "duplicate_pick": duplicate,
            "current_pick_before": before_pick,
            "current_pick_after": current_pick,
            "drafted_count_after": len(drafted),
        }
    return result


def recompute_after_pick(
    payload: dict[str, Any],
    picked_player_id: str,
    picked_by_slot: int | None = None,
    apply_to_user_roster: bool = False,
    advance_pick: bool = True,
) -> dict[str, Any]:
    """
    Apply pick + recompute recommendation in one call.
    """
    applied = apply_pick_to_payload(
        payload=payload,
        picked_player_id=picked_player_id,
        picked_by_slot=picked_by_slot,
        apply_to_user_roster=apply_to_user_roster,
        advance_pick=advance_pick,
    )
    if not applied.get("ok"):
        return applied

    state = applied["state"]

    # Validate resulting state against existing request validator
    try:
        parse_recommendation_request(state)
    except RecommendationRequestValidationError as exc:
        return _error(exc.details)
    except Exception as exc:
        return _error(str(exc) or repr(exc))

    rec = get_recommendation_for_payload(state)
    if not rec.get("ok"):
        out = {"ok": False, "state": state, "error": rec.get("error"), "details": rec.get("details")}
        if state.get("include_debug") and rec.get("debug"):
            out["debug"] = rec["debug"]
        if applied.get("live_draft_debug"):
            out["live_draft_debug"] = applied["live_draft_debug"]
        return out

    out = {
        "ok": True,
        "state": state,
        "recommendation": rec.get("recommendation"),
    }

    if state.get("include_debug"):
        if rec.get("debug"):
            out["debug"] = rec["debug"]
        if applied.get("live_draft_debug"):
            out["live_draft_debug"] = applied["live_draft_debug"]

    return out


def apply_pick_operation(operation_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Frontend-friendly operation wrapper:
    {
      "state": {...},
      "picked_player_id": "...",
      "picked_by_slot": 5,
      "apply_to_user_roster": false,
      "advance_pick": true,
      "include_recommendation": true
    }
    """
    if not isinstance(operation_payload, dict):
        return _error("operation payload must be an object")

    state = operation_payload.get("state")
    if not isinstance(state, dict):
        return _error("state is required")

    picked_player_id = operation_payload.get("picked_player_id")
    if not isinstance(picked_player_id, str) or not picked_player_id.strip():
        return _error("picked_player_id is required")

    picked_by_slot = operation_payload.get("picked_by_slot")
    apply_to_user_roster = bool(operation_payload.get("apply_to_user_roster", False))
    advance_pick = bool(operation_payload.get("advance_pick", True))
    include_recommendation = bool(operation_payload.get("include_recommendation", False))

    if include_recommendation:
        return recompute_after_pick(
            payload=state,
            picked_player_id=picked_player_id,
            picked_by_slot=picked_by_slot,
            apply_to_user_roster=apply_to_user_roster,
            advance_pick=advance_pick,
        )

    return apply_pick_to_payload(
        payload=state,
        picked_player_id=picked_player_id,
        picked_by_slot=picked_by_slot,
        apply_to_user_roster=apply_to_user_roster,
        advance_pick=advance_pick,
    )