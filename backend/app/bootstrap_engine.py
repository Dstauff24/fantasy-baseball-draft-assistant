from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.debug_trace import DebugTrace


class EngineBootstrapError(RuntimeError):
    pass


CANONICAL_PROJECTIONS_CSV_PATH = Path(
    r"C:\Users\dstauffer\Desktop\Fantasy Baseball Draft Assistant\draft-assistant\fantasy-baseball-draft-assistant-backend\Data\Baseball Ranks_2026 Pre-Season.csv"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_projections_csv_path(
    explicit_path: str | None = None,
    trace: DebugTrace | None = None,
) -> Path:
    requested = explicit_path.strip() if isinstance(explicit_path, str) and explicit_path.strip() else None
    env_value = os.getenv("FBA_PROJECTIONS_CSV")
    env_path = env_value.strip() if isinstance(env_value, str) and env_value.strip() else None
    selected = Path(requested or env_path or CANONICAL_PROJECTIONS_CSV_PATH)
    exists = selected.exists() and selected.is_file()

    if trace:
        trace.log(
            "resolve_csv_path",
            "CSV path resolved",
            explicit_path=explicit_path,
            env_path=env_path,
            selected=str(selected),
            exists=exists,
        )

    if not exists:
        raise EngineBootstrapError(
            f"Could not locate projections CSV at resolved path: {selected}"
        )
    return selected.resolve()


def _load_raw_players(
    csv_path: Path,
    trace: DebugTrace | None = None,
) -> tuple[dict[str, Any], list[str]]:
    from app.loader import load_projections_csv

    result = load_projections_csv(str(csv_path))

    result_type = type(result).__name__
    first_type = second_type = first_len = second_len = None

    if isinstance(result, tuple) and len(result) == 2:
        first_type = type(result[0]).__name__
        second_type = type(result[1]).__name__
        first_len = len(result[0]) if hasattr(result[0], "__len__") else None
        second_len = len(result[1]) if hasattr(result[1], "__len__") else None

    if trace:
        trace.log(
            "load_projections",
            "Projections CSV loaded",
            return_type=result_type,
            tuple_0_type=first_type,
            tuple_0_len=first_len,
            tuple_1_type=second_type,
            tuple_1_len=second_len,
        )

    if result is None:
        raise EngineBootstrapError("load_projections_csv returned None")

    if isinstance(result, tuple) and len(result) == 2:
        first, second = result
        if isinstance(first, dict) and isinstance(second, list):
            return first, second

    if isinstance(result, dict):
        return result, list(result.keys())

    if isinstance(result, list):
        by_id: dict[str, Any] = {}
        for p in result:
            pid = getattr(p, "player_id", None) or (p.get("player_id") if isinstance(p, dict) else None)
            if pid:
                by_id[str(pid)] = p
        return by_id, list(by_id.keys())

    raise EngineBootstrapError(f"Unrecognized load_projections_csv return shape: {type(result)}")


def _normalize_ranked_output(result: Any) -> tuple[dict[str, Any], list[Any]]:
    """
    Normalize rank_players_by_points return into (valued_players_by_id, valued_players).
    Shape A: (dict[id->Player], list[id])
    Shape B: dict[id->Player]
    Shape C: list[Player]
    Shape D: (list[Player], list[id])
    """
    # Shape A
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], dict)
        and isinstance(result[1], list)
    ):
        by_id: dict[str, Any] = result[0]
        return by_id, list(by_id.values())

    # Shape B
    if isinstance(result, dict):
        return result, list(result.values())

    # Shape C
    if isinstance(result, list):
        by_id = {}
        for p in result:
            pid = getattr(p, "player_id", None)
            if pid is None and isinstance(p, dict):
                pid = p.get("player_id") or p.get("id")
            if pid is not None:
                by_id[str(pid)] = p
        return by_id, list(by_id.values())

    # Shape D
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], list):
        players = result[0]
        by_id = {}
        for p in players:
            pid = getattr(p, "player_id", None)
            if pid is not None:
                by_id[str(pid)] = p
        return by_id, list(by_id.values())

    raise EngineBootstrapError(f"Unrecognized rank_players_by_points return shape: {type(result)}")


def _value_players(
    players_by_id: dict[str, Any],
    trace: DebugTrace | None = None,
) -> tuple[dict[str, Any], list[Any]]:
    from app.config import ScoringConfig
    from app.valuation import rank_players_by_points

    scoring = ScoringConfig()

    if trace:
        trace.log(
            "rank_players",
            "Calling rank_players_by_points",
            input_type="dict",
            input_count=len(players_by_id),
        )

    valued_raw = None
    last_exc: Exception | None = None
    for attempt_args, attempt_kwargs in (
        ((players_by_id, scoring), {}),
        ((players_by_id,), {"scoring_config": scoring}),
        ((players_by_id,), {}),
        ((), {"players_by_id": players_by_id, "scoring_config": scoring}),
        ((), {"players_by_id": players_by_id}),
    ):
        try:
            valued_raw = rank_players_by_points(*attempt_args, **attempt_kwargs)
            if valued_raw is not None:
                break
        except TypeError as exc:
            last_exc = exc
            continue

    if valued_raw is None:
        raise EngineBootstrapError(
            f"rank_players_by_points returned None for all attempted signatures. Last error: {last_exc}"
        )

    valued_by_id, valued_list = _normalize_ranked_output(valued_raw)

    if trace:
        trace.log(
            "rank_players",
            "rank_players_by_points completed",
            raw_return_type=type(valued_raw).__name__,
            valued_players_by_id_count=len(valued_by_id),
            valued_players_count=len(valued_list),
        )

    return valued_by_id, valued_list


def _inspect_player_pool(pool: Any) -> dict[str, Any]:
    """
    Inspect player pool structure to debug empty-pool issues.
    """
    inspection = {
        "type": type(pool).__name__,
        "has_get_all_players": callable(getattr(pool, "get_all_players", None)),
        "has_players_attr": hasattr(pool, "players"),
        "has_available_players": hasattr(pool, "available_players"),
        "has_players_by_id": hasattr(pool, "players_by_id"),
        "all_attrs": [a for a in dir(pool) if not a.startswith("_")],
    }

    # Try all known accessors
    for attr in ["players", "available_players", "players_by_id", "_players"]:
        val = getattr(pool, attr, None)
        if val is not None:
            inspection[f"attr_{attr}_type"] = type(val).__name__
            inspection[f"attr_{attr}_len"] = len(val) if hasattr(val, "__len__") else "N/A"

    if callable(getattr(pool, "get_all_players", None)):
        try:
            result = pool.get_all_players()
            inspection["get_all_players_type"] = type(result).__name__
            inspection["get_all_players_len"] = len(result) if hasattr(result, "__len__") else "N/A"
        except Exception as exc:
            inspection["get_all_players_error"] = str(exc)

    return inspection


def _build_player_pool(
    valued_players_by_id: dict[str, Any],
    trace: DebugTrace | None = None,
) -> Any:
    from app.player_pool import build_player_pool

    valued_players = list(valued_players_by_id.values())

    if trace:
        trace.log(
            "build_player_pool",
            "Calling build_player_pool",
            input_type="dict[str, Player]",
            input_count=len(valued_players_by_id),
            sample_player_id=next(iter(valued_players_by_id.keys())) if valued_players_by_id else None,
        )

    last_exc: Exception | None = None
    pool = None

    for attempt in (
        lambda: build_player_pool(valued_players_by_id=valued_players_by_id),
        lambda: build_player_pool(valued_players_by_id),
        lambda: build_player_pool(valued_players=valued_players, valued_players_by_id=valued_players_by_id),
        lambda: build_player_pool(valued_players),
    ):
        try:
            pool = attempt()
            if pool is not None:
                break
        except TypeError as exc:
            last_exc = exc
            continue

    if pool is None:
        raise EngineBootstrapError(
            f"build_player_pool returned None. Last error: {last_exc}"
        )

    # Inspect pool structure
    inspection = _inspect_player_pool(pool)

    if trace:
        trace.log(
            "build_player_pool",
            "Player pool built - inspecting structure",
            **inspection,
        )

    return pool


def build_default_engine_context(
    projections_csv_path: str | None = None,
    trace: DebugTrace | None = None,
) -> dict[str, Any]:
    from app.config import LeagueConfig

    csv_path = resolve_projections_csv_path(projections_csv_path, trace=trace)
    players_by_id, _ordered_ids = _load_raw_players(csv_path, trace=trace)

    if not players_by_id:
        raise EngineBootstrapError(f"No players loaded from CSV: {csv_path}")

    valued_players_by_id, valued_players = _value_players(players_by_id, trace=trace)

    if not valued_players_by_id:
        raise EngineBootstrapError("Valuation produced no player IDs (valued_players_by_id is empty)")

    player_pool = _build_player_pool(valued_players_by_id, trace=trace)

    return {
        "csv_path": str(csv_path),
        "league_config": LeagueConfig(),
        "raw_players": list(players_by_id.values()),
        "valued_players": valued_players,
        "valued_players_by_id": valued_players_by_id,
        "player_pool": player_pool,
    }


def load_engine_context(
    projections_csv_path: str | None = None,
    trace: DebugTrace | None = None,
) -> dict[str, Any]:
    return build_default_engine_context(projections_csv_path=projections_csv_path, trace=trace)