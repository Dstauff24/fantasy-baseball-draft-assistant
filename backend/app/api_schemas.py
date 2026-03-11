"""
Lightweight TypedDict schema definitions for the Fantasy Baseball Draft Assistant API.

These are used for documentation, frontend contract reference, and optional
static type checking. They do not enforce validation at runtime.

Use these as the source of truth when describing request/response shapes
to frontend consumers (React, Lovable, etc.).
"""
from __future__ import annotations

from typing import Any
from typing import TypedDict


# ==================================================
# REQUEST SCHEMAS
# ==================================================


class DraftStatePayload(TypedDict, total=False):
    """
    Base draft state payload. Sent with every recommendation request.

    Required fields:
        current_pick        -- current overall pick number in the draft (1-indexed)
        user_slot           -- the user's draft slot (1 to teams, inclusive)
        teams               -- total number of teams in the league

    Optional fields:
        drafted_player_ids      -- ordered list of all drafted player IDs so far
        user_roster_player_ids  -- player IDs currently on the user's roster
        available_player_ids    -- explicit board of available player IDs (null = infer from pool)
        top_n                   -- max number of candidates to return (default: 10)
        include_debug           -- if true, include internal debug trace in response
        projections_csv_path    -- local/dev path to projections CSV (not used in production)
    """

    # Required
    current_pick: int
    user_slot: int
    teams: int

    # Optional
    drafted_player_ids: list[str]
    user_roster_player_ids: list[str]
    available_player_ids: list[str] | None
    top_n: int
    include_debug: bool
    projections_csv_path: str


class ApplyPickPayload(TypedDict, total=False):
    """
    Payload for apply-pick operations.

    Required fields:
        state               -- current DraftStatePayload
        picked_player_id    -- player ID of the player just drafted

    Optional fields:
        picked_by_slot          -- draft slot that made the pick (for future tracking)
        apply_to_user_roster    -- if true, add picked player to user's roster (default: false)
        advance_pick            -- if true, increment current_pick by 1 (default: true)
        include_recommendation  -- if true, recompute and return recommendation (default: false)
    """

    # Required
    state: DraftStatePayload
    picked_player_id: str

    # Optional
    picked_by_slot: int
    apply_to_user_roster: bool
    advance_pick: bool
    include_recommendation: bool


# ==================================================
# RESPONSE SCHEMAS
# ==================================================


class RosterSnapshot(TypedDict):
    count: int
    players: list[str]
    positions: list[str]


class DraftContextSummarySchema(TypedDict):
    current_pick: int
    next_user_pick: int | None
    teams_until_next_pick: int
    roster_snapshot: RosterSnapshot
    positional_pressure: dict[str, Any]
    likely_run_positions: list[str]


class PlayerCardSchema(TypedDict, total=False):
    player_id: str
    player_name: str
    team: str
    positions: list[str]
    draft_score: float
    survival_probability: float
    board_pressure_score: float
    reasoning: list[str]


class RecommendationPayload(TypedDict, total=False):
    headline_recommendation: PlayerCardSchema
    alternate_recommendations: list[PlayerCardSchema]
    value_falls: list[PlayerCardSchema]
    wait_on_it_candidates: list[PlayerCardSchema]
    risk_flags: list[dict[str, Any]]
    strategic_explanation: list[str]
    draft_context: DraftContextSummarySchema
    raw_debug: dict[str, Any]


class RecommendationResponse(TypedDict):
    """Response from POST /api/recommendation."""
    ok: bool
    recommendation: RecommendationPayload


class ApplyPickResponse(TypedDict):
    """Response from POST /api/apply-pick (without recompute)."""
    ok: bool
    state: DraftStatePayload


class RecommendationAfterPickResponse(TypedDict):
    """Response from POST /api/recommendation-after-pick."""
    ok: bool
    state: DraftStatePayload
    recommendation: RecommendationPayload


class ErrorResponse(TypedDict, total=False):
    """Returned when any operation fails."""
    ok: bool          # always False
    error: str        # short error category
    details: str      # human-readable details
    debug: dict[str, Any]  # present only if include_debug=true