from __future__ import annotations

import inspect
from typing import Any, Callable

from app.bootstrap_engine import EngineBootstrapError, load_engine_context
from app.debug_trace import DebugTrace

class RecommendationRequestValidationError(ValueError):
    def __init__(self, details: str):
        super().__init__(details)
        self.details = details


class RecommendationBuildError(RuntimeError):
    """Runtime bootstrap/build failure (not request validation)."""
    pass


def _to_int(name: str, value: Any, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise RecommendationRequestValidationError(f"{name} must be an integer")
    if min_value is not None and parsed < min_value:
        raise RecommendationRequestValidationError(f"{name} must be >= {min_value}")
    if max_value is not None and parsed > max_value:
        raise RecommendationRequestValidationError(f"{name} must be <= {max_value}")
    return parsed


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _to_str_list(name: str, value: Any, default: list[str] | None = None) -> list[str]:
    if value is None:
        return list(default or [])
    if not isinstance(value, list):
        raise RecommendationRequestValidationError(f"{name} must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RecommendationRequestValidationError(f"{name} contains an invalid player id")
        out.append(item.strip())
    return out


def parse_recommendation_request(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Frontend request contract:

    Required:
      - current_pick: int

    Optional:
      - user_slot: int = 1
      - teams: int = 12
      - drafted_player_ids: list[str] = []
      - user_roster_player_ids: list[str] = []
      - available_player_ids: list[str] | null = null
      - include_debug: bool = false
      - top_n: int = 10
      - projections_csv_path: str | null = null
    """
    if not isinstance(payload, dict):
        raise RecommendationRequestValidationError("request body must be a JSON object")

    if "current_pick" not in payload:
        raise RecommendationRequestValidationError("current_pick is required")

    teams = _to_int("teams", payload.get("teams", 12), min_value=2, max_value=30)
    user_slot = _to_int("user_slot", payload.get("user_slot", 1), min_value=1, max_value=teams)

    available_raw = payload.get("available_player_ids", None)
    available_ids = None if available_raw is None else _to_str_list("available_player_ids", available_raw)

    projections_csv_path = payload.get("projections_csv_path", None)
    if projections_csv_path is not None:
        if not isinstance(projections_csv_path, str) or not projections_csv_path.strip():
            raise RecommendationRequestValidationError("projections_csv_path must be a non-empty string or null")
        projections_csv_path = projections_csv_path.strip()

    return {
        "current_pick": _to_int("current_pick", payload.get("current_pick"), min_value=1),
        "user_slot": user_slot,
        "teams": teams,
        "drafted_player_ids": _to_str_list("drafted_player_ids", payload.get("drafted_player_ids"), default=[]),
        "user_roster_player_ids": _to_str_list("user_roster_player_ids", payload.get("user_roster_player_ids"), default=[]),
        "available_player_ids": available_ids,
        "include_debug": _to_bool(payload.get("include_debug", False), default=False),
        "top_n": _to_int("top_n", payload.get("top_n", 10), min_value=1, max_value=50),
        "projections_csv_path": projections_csv_path,
    }


def _try_call(obj: Any, method_names: list[str], *args) -> bool:
    for name in method_names:
        fn = getattr(obj, name, None)
        if callable(fn):
            try:
                fn(*args)
                return True
            except TypeError:
                continue
    return False


def _infer_available_from_pool(player_pool: Any, drafted_ids: list[str]) -> list[str]:
    """
    Extract all players from pool using all known accessor patterns.
    """
    drafted_set = set(drafted_ids)
    players: list[Any] = []

    # Try all known pool structures
    if callable(getattr(player_pool, "get_all_players", None)):
        try:
            result = player_pool.get_all_players()
            players = list(result) if result else []
        except Exception:
            pass

    if not players and isinstance(getattr(player_pool, "players", None), list):
        players = list(player_pool.players)

    if not players and isinstance(getattr(player_pool, "available_players", None), list):
        players = list(player_pool.available_players)

    if not players and isinstance(getattr(player_pool, "players_by_id", None), dict):
        players = list(player_pool.players_by_id.values())

    if not players and isinstance(getattr(player_pool, "_players", None), list):
        players = list(player_pool._players)

    if not players and isinstance(getattr(player_pool, "_players", None), dict):
        players = list(player_pool._players.values())

    # Extract IDs from discovered players
    out: list[str] = []
    for p in players:
        pid = getattr(p, "player_id", None) or getattr(p, "id", None)
        if pid and str(pid) not in drafted_set:
            out.append(str(pid))

    return out


def _build_pick_history(drafted_player_ids: list[str], teams: int) -> list[dict[str, Any]]:
    return [
        {"pick_number": i, "team_slot": _slot_for_pick(i, teams), "player_id": pid}
        for i, pid in enumerate(drafted_player_ids, start=1)
    ]


def _build_team_rosters(
    drafted_player_ids: list[str],
    user_roster_player_ids: list[str],
    user_slot: int,
    teams: int,
) -> dict[int, list[str]]:
    rosters: dict[int, list[str]] = {slot: [] for slot in range(1, teams + 1)}
    used: set[str] = set()

    for i, pid in enumerate(drafted_player_ids, start=1):
        slot = _slot_for_pick(i, teams)
        rosters[slot].append(pid)
        used.add(pid)

    for pid in user_roster_player_ids:
        if pid not in used:
            rosters[user_slot].append(pid)
            used.add(pid)

    return rosters


def _slot_for_pick(pick_number: int, teams: int) -> int:
    round_idx = (pick_number - 1) // teams
    in_round = (pick_number - 1) % teams
    return (in_round + 1) if round_idx % 2 == 0 else (teams - in_round)

def DraftState(
    league_config,
    player_pool,
    drafted_player_ids,
    drafted_player_id_set,
    available_player_ids,
    available_player_id_set,
    team_rosters,
    pick_history,
    current_pick,
    current_pick_number,
):
    raise NotImplementedError


def build_draft_state_from_request(
    req: dict[str, Any],
    draft_state_factory: Callable[[dict[str, Any]], Any] | None = None,
    trace: DebugTrace | None = None,
) -> Any:
    if draft_state_factory is not None:
        return draft_state_factory(req)

    from app.draft_state import DraftState

    ctx = load_engine_context(
        projections_csv_path=req.get("projections_csv_path"),
        trace=trace,
    )
    player_pool = ctx["player_pool"]
    league_config = ctx["league_config"]

    drafted_player_ids = list(dict.fromkeys(req["drafted_player_ids"]))
    available_player_ids = (
        list(dict.fromkeys(req["available_player_ids"]))
        if req["available_player_ids"] is not None
        else _infer_available_from_pool(player_pool, drafted_player_ids)
    )

    team_rosters = _build_team_rosters(
        drafted_player_ids=drafted_player_ids,
        user_roster_player_ids=req["user_roster_player_ids"],
        user_slot=req["user_slot"],
        teams=req["teams"],
    )
    pick_history = _build_pick_history(drafted_player_ids, req["teams"])

    if trace:
        trace.log(
            "build_draft_state",
            "Building DraftState",
            requested_current_pick=req["current_pick"],
            drafted_count=len(drafted_player_ids),
            available_count=len(available_player_ids),
            user_roster_ids=req["user_roster_player_ids"],
        )

    raw_kwargs = {
        "league_config": league_config,
        "player_pool": player_pool,
        "drafted_player_ids": drafted_player_ids,
        "drafted_player_id_set": set(drafted_player_ids),
        "available_player_ids": available_player_ids,
        "available_player_id_set": set(available_player_ids),
        "team_rosters": team_rosters,
        "pick_history": pick_history,
        "current_pick": req["current_pick"],
        "current_pick_number": req["current_pick"],
    }

    sig = inspect.signature(DraftState)
    kwargs = {k: v for k, v in raw_kwargs.items() if k in sig.parameters}

    try:
        ds = DraftState(**kwargs)
    except TypeError as exc:
        raise EngineBootstrapError(f"DraftState construction failed: {exc}") from exc

    # Attach current_pick and user_slot as instance attributes if needed
    if not hasattr(ds, "current_pick") or getattr(ds, "current_pick", None) is None:
        ds.current_pick = req["current_pick"]
    
    if not hasattr(ds, "user_slot") or getattr(ds, "user_slot", None) is None:
        ds.user_slot = req["user_slot"]

    if trace:
        trace.log(
            "build_draft_state",
            "DraftState constructed",
            stored_current_pick=getattr(ds, "current_pick", None),
            stored_user_slot=getattr(ds, "user_slot", None),
        )

    return ds