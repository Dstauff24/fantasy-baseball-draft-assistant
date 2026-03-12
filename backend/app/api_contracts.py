from __future__ import annotations

import inspect
import traceback as tb_module
from typing import Any, Callable

from app.bootstrap_engine import EngineBootstrapError
from app.debug_trace import DebugTrace
from app.recommendation_engine import recommend_for_user_packaged, recommend_for_user_packaged_dict
from app.request_builders import (
    RecommendationRequestValidationError,
    build_draft_state_from_request,
    parse_recommendation_request,
)
from app.serializers import to_dict


def _call_with_supported_kwargs(fn, draft_state, req):
    sig = inspect.signature(fn)
    kwargs = {}
    if "top_n" in sig.parameters:
        kwargs["top_n"] = req["top_n"]
    if "include_debug" in sig.parameters:
        kwargs["include_debug"] = req["include_debug"]
    return fn(draft_state, **kwargs)


def _make_error_response(
    error: str,
    exc: Exception,
    stage: str,
    trace: DebugTrace,
    include_debug: bool,
) -> dict[str, Any]:
    details = str(exc) if str(exc).strip() else repr(exc)
    trace.fail(stage, exc)

    resp: dict[str, Any] = {
        "ok": False,
        "error": error,
        "details": f"{type(exc).__name__}: {details}",
    }

    if include_debug:
        resp["debug"] = trace.to_dict()

    return resp


def get_packaged_recommendation_from_request(
    payload: dict[str, Any],
    draft_state_factory: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    include_debug = bool(payload.get("include_debug", False)) if isinstance(payload, dict) else False
    trace = DebugTrace.make(include_debug)

    try:
        trace.log("parse_request", "Parsing recommendation request")
        req = parse_recommendation_request(payload)
        trace.log(
            "parse_request",
            "Request parsed successfully",
            current_pick=req["current_pick"],
            user_slot=req["user_slot"],
            teams=req["teams"],
            drafted_count=len(req["drafted_player_ids"]),
            user_roster_count=len(req["user_roster_player_ids"]),
            top_n=req["top_n"],
        )
    except RecommendationRequestValidationError as exc:
        trace.fail("parse_request", exc, capture_tb=False)
        resp: dict[str, Any] = {
            "ok": False,
            "error": "Invalid recommendation request",
            "details": exc.details,
        }
        if include_debug:
            resp["debug"] = trace.to_dict()
        return resp

    try:
        draft_state = build_draft_state_from_request(
            req, draft_state_factory=draft_state_factory, trace=trace
        )

        # Verify pick was set correctly
        stored_pick = (
            getattr(draft_state, "current_pick_number", None) 
            or getattr(draft_state, "current_pick", None)
        )
        trace.log(
            "verify_state",
            "Draft state created",
            requested_current_pick=req["current_pick"],
            stored_current_pick=stored_pick,
            user_slot=req["user_slot"],
        )
    except EngineBootstrapError as exc:
        return _make_error_response("Failed to generate recommendation", exc, "build_draft_state", trace, include_debug)
    except Exception as exc:
        return _make_error_response("Failed to generate recommendation", exc, "build_draft_state", trace, include_debug)

    try:
        trace.log("generate_recommendation", "Calling recommendation engine")
        try:
            packaged = _call_with_supported_kwargs(recommend_for_user_packaged, draft_state, req)
            recommendation = to_dict(packaged)
        except Exception:
            packaged_dict = _call_with_supported_kwargs(recommend_for_user_packaged_dict, draft_state, req)
            recommendation = packaged_dict if isinstance(packaged_dict, dict) else to_dict(packaged_dict)

        # Verify packaged response has correct context
        if isinstance(recommendation, dict) and "draft_context" in recommendation:
            dc = recommendation["draft_context"]
            trace.log(
                "verify_packaging",
                "Recommendation packaged",
                packaged_current_pick=dc.get("current_pick"),
                packaged_roster_count=dc.get("roster_snapshot", {}).get("count", 0),
            )

        trace.log(
            "serialize_response",
            "Recommendation serialized",
            top_level_keys=list(recommendation.keys()) if isinstance(recommendation, dict) else [],
        )
    except Exception as exc:
        return _make_error_response("Failed to generate recommendation", exc, "generate_recommendation", trace, include_debug)

    resp = {"ok": True, "recommendation": recommendation}
    if include_debug:
        resp["debug"] = trace.to_dict()
    return resp