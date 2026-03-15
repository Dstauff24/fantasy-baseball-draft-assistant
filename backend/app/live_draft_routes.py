from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from app.live_draft_service import (
    apply_pick_operation,
    get_recommendation_for_payload,
)
from app.players_service import load_ranked_player_catalog

router = APIRouter(prefix="/api", tags=["live-draft"])


def _bad_request(details: str) -> dict[str, Any]:
    return {"ok": False, "error": "Invalid live draft operation", "details": details}




@router.get("/players")
def get_players(include_live_context: bool = Query(False)) -> dict[str, Any]:
    """
    GET /api/players
    Returns full ranked player catalog for frontend pool + diagnostics.
    """
    try:
        return {"ok": True, "players": load_ranked_player_catalog(include_live_context=include_live_context)}
    except Exception as exc:
        return {
            "ok": False,
            "error": "Failed to load player catalog",
            "details": f"{type(exc).__name__}: {exc}",
        }

@router.post("/recommendation")
def post_recommendation(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """
    POST /api/recommendation
    Accepts: DraftStatePayload
    Returns: RecommendationResponse
    """
    if not isinstance(payload, dict):
        return _bad_request("payload must be an object")
    return get_recommendation_for_payload(payload)


@router.post("/apply-pick")
def post_apply_pick(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """
    POST /api/apply-pick
    Accepts: ApplyPickPayload { state, picked_player_id, ... }
    Returns: ApplyPickResponse
    """
    if not isinstance(payload, dict):
        return _bad_request("payload must be an object")

    # Route-level validation before delegating
    if not isinstance(payload.get("state"), dict):
        return _bad_request("state is required")
