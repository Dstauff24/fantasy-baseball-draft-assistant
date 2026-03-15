from __future__ import annotations

from typing import Any

from app.bootstrap_engine import resolve_projections_csv_path
from app.config import LeagueConfig, ScoringConfig
from app.draft_context_engine import build_draft_context
from app.draft_decision_engine import (
    build_position_window_map,
    build_replacement_baselines,
    rank_position_dropoffs_for_buckets,
    score_draft_candidate,
)
from app.draft_state import DraftState
from app.loader import load_projections_csv
from app.player_pool import build_player_pool
from app.valuation import rank_players_by_points


LIVE_CONTEXT_NOTE = "default_draft_context_approximation"


def _normalize_ranked_output(result: Any) -> tuple[dict[str, Any], list[str]]:
    """
    Normalize rank_players_by_points return shape into (players_by_id, ids_by_rank).
    Canonical expected shape in this repo is: (dict[str, Player], list[str]).
    """
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], dict)
        and isinstance(result[1], list)
    ):
        return result[0], [str(pid) for pid in result[1]]

    if isinstance(result, dict):
        players_by_id = result
        ids = sorted(
            players_by_id.keys(),
            key=lambda pid: (
                players_by_id[pid].derived_rank
                if getattr(players_by_id[pid], "derived_rank", None) is not None
                else 10**9,
                getattr(players_by_id[pid], "name", ""),
            ),
        )
        return players_by_id, [str(pid) for pid in ids]

    if isinstance(result, list):
        players_by_id: dict[str, Any] = {}
        for p in result:
            pid = getattr(p, "player_id", None)
            if pid:
                players_by_id[str(pid)] = p
        ids = sorted(
            players_by_id.keys(),
            key=lambda pid: (
                players_by_id[pid].derived_rank
                if getattr(players_by_id[pid], "derived_rank", None) is not None
                else 10**9,
                getattr(players_by_id[pid], "name", ""),
            ),
        )
        return players_by_id, [str(pid) for pid in ids]

    raise ValueError(f"Unsupported rank_players_by_points return shape: {type(result)}")


def _build_full_catalog_decision_scores(ranked_players_by_id: dict[str, Any]) -> dict[str, Any]:
    """
    Compute live-context decision metrics (draft_score, survival, pressure, etc.)
    using a default DraftState snapshot. These are useful for diagnostics but
    should not be interpreted as global value metrics.
    """
    player_pool = build_player_pool(ranked_players_by_id)
    draft_state = DraftState.create(LeagueConfig(), player_pool)

    # Establish default context for scoring signals.
    draft_state.current_pick = 1
    draft_state.current_pick_number = 1
    draft_state.user_slot = draft_state.league_config.user_draft_slot

    candidate_pool = draft_state.get_available_players_by_value()
    baselines = build_replacement_baselines(draft_state)
    draft_context = build_draft_context(draft_state)

    position_window_map = build_position_window_map(draft_state, candidate_pool)
    bucket_leader_map = {
        bucket: row.get("current_best_player_id")
        for bucket, row in position_window_map.items()
        if isinstance(row, dict) and row.get("current_best_player_id")
    }
    represented_buckets = set(position_window_map.keys())
    dropoff_ranks = rank_position_dropoffs_for_buckets(position_window_map, represented_buckets)

    decision_scores_by_id: dict[str, Any] = {}
    for player in candidate_pool:
        score = score_draft_candidate(
            draft_state=draft_state,
            player=player,
            baselines=baselines,
            position_window_map=position_window_map,
            dropoff_ranks=dropoff_ranks,
            bucket_leader_map=bucket_leader_map,
            draft_context=draft_context,
        )
        decision_scores_by_id[player.player_id] = score

    return decision_scores_by_id


def _value_vs_adp(engine_rank: int, adp_rank: int | None) -> float | None:
    if adp_rank is None:
        return None
    return round(float(adp_rank - engine_rank), 2)


def load_ranked_player_catalog(
    projections_csv_path: str | None = None,
    include_live_context: bool = False,
) -> list[dict[str, Any]]:
    """
    Canonical full real-player catalog loader for diagnostics/front-end pool.

    Pipeline (reused from existing architecture):
    resolve_projections_csv_path -> load_projections_csv -> rank_players_by_points.

    By default, this returns global-board metrics only.
    Set include_live_context=True to include default-context decision metrics.
    """
    csv_path = resolve_projections_csv_path(projections_csv_path)

    loaded = load_projections_csv(str(csv_path))
    if not (isinstance(loaded, tuple) and len(loaded) == 2):
        raise ValueError(f"Unsupported load_projections_csv return shape: {type(loaded)}")

    players_by_id, _ids_by_adp = loaded
    if not isinstance(players_by_id, dict):
        raise ValueError("load_projections_csv first return value must be dict[str, Player]")

    ranked_raw = rank_players_by_points(players_by_id, ScoringConfig())
    ranked_players_by_id, ids_by_rank = _normalize_ranked_output(ranked_raw)

    decision_scores_by_id: dict[str, Any] = {}
    if include_live_context:
        decision_scores_by_id = _build_full_catalog_decision_scores(ranked_players_by_id)

    adp_sorted_ids = sorted(
        ranked_players_by_id.keys(),
        key=lambda pid: (
            ranked_players_by_id[pid].adp
            if getattr(ranked_players_by_id[pid], "adp", None) is not None
            else float("inf"),
            getattr(ranked_players_by_id[pid], "name", ""),
        ),
    )
    adp_rank_by_id = {pid: idx for idx, pid in enumerate(adp_sorted_ids, start=1)}

    catalog: list[dict[str, Any]] = []
    for engine_rank, pid in enumerate(ids_by_rank, start=1):
        player = ranked_players_by_id.get(pid)
        if player is None:
            continue

        adp_rank = adp_rank_by_id.get(pid)
        row = {
            # Global board metrics
            "player_id": player.player_id,
            "player_name": player.name,
            "team": player.mlb_team,
            "positions": list(player.positions or []),
            "adp": player.adp,
            "adp_rank": adp_rank,
            "projected_points": player.projected_points,
            "engine_rank": engine_rank,
            "derived_rank": getattr(player, "derived_rank", None),
            "value_vs_adp": _value_vs_adp(engine_rank, adp_rank),
            "metrics_scope": "global_board",
            # Cliff metadata remains useful on global board
            "cliff_label": None,
            "cliff_raw_drop": None,
        }

        if include_live_context:
            decision = decision_scores_by_id.get(pid)
            decision_components = getattr(decision, "component_scores", {}) if decision is not None else {}
            row.update(
                {
                    "metrics_scope": "global_plus_live_context",
                    "live_context_note": LIVE_CONTEXT_NOTE,
                    # Live-context metrics
                    "vorp": float(getattr(decision, "vorp", 0.0)) if decision is not None else None,
                    "draft_score": float(getattr(decision, "draft_score", 0.0)) if decision is not None else None,
                    "survival_probability": float(getattr(decision, "survival_probability", 0.0)) if decision is not None else None,
                    "take_now_edge": float(getattr(decision, "take_now_edge", 0.0)) if decision is not None else None,
                    "roster_fit_score": float(getattr(decision, "roster_fit_score", 0.0)) if decision is not None else None,
                    "team_need_pressure": float(getattr(decision, "team_need_pressure", 0.0)) if decision is not None else None,
                    "tier_cliff_score": float(getattr(decision, "tier_cliff_score", 0.0)) if decision is not None else None,
                    "sp_cliff_multiplier": decision_components.get("sp_cliff_multiplier") if decision is not None else None,
                    "path_score": None,
                    # useful cliff debug retained
                    "cliff_label": decision_components.get("cliff_label") if decision is not None else None,
                    "cliff_raw_drop": decision_components.get("cliff_raw_drop") if decision is not None else None,
                }
            )
        else:
            row.update(
                {
                    # Keep keys for compatibility, but intentionally null in global mode.
                    "vorp": None,
                    "draft_score": None,
                    "survival_probability": None,
                    "take_now_edge": None,
                    "roster_fit_score": None,
                    "team_need_pressure": None,
                    "tier_cliff_score": None,
                    "sp_cliff_multiplier": None,
                    "path_score": None,
                    "live_context_note": "excluded_in_global_mode",
                }
            )

        catalog.append(row)

    return catalog
