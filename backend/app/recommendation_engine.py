from copy import deepcopy

from operator import pos

from app.draft_state import DraftState
from app.opponent_model import simulate_picks_until_next_turn, simulate_picks_with_context
from app.models import Player, CandidateScore, RecommendationResult
from app.draft_decision_engine import (
    build_decision_board,
    build_position_window_map,
    rank_position_dropoffs,
    rank_position_dropoffs_for_buckets,
)
from app.draft_path_simulator import simulate_top_candidate_paths
from app.response_packager import package_recommendation_response
from app.serializers import to_dict
from types import SimpleNamespace


def _is_pitcher(player) -> bool:
    return any(pos in {"SP", "RP", "P"} for pos in player.positions)


def _is_hitter(player) -> bool:
    return not _is_pitcher(player)


def _position_bucket(player) -> str:
    pos = list(player.positions)

    if "SP" in pos or "P" in pos:
@@ -159,65 +159,71 @@ def recommend_pick(draft_state: DraftState, top_n: int = 10) -> RecommendationRe
            return "RP"
        for b in ("C", "1B", "2B", "3B", "SS", "OF"):
            if b in pos:
                return b
        return "UTIL"

    represented_buckets: set[str] = set()
    for cs in scored[:top_n]:
        p = draft_state.player_pool.get_player(cs.player_id)
        if p is not None:
            represented_buckets.add(_bucket_from_positions(getattr(p, "positions", [])))

    candidate_relative_ranks = rank_position_dropoffs_for_buckets(
        position_window_map,
        represented_buckets,
    )

    if not scored:
        fallback_players = draft_state.get_available_players_by_value(max(top_n, 10))
        if fallback_players:
            scored = [_fallback_candidate_score(p) for p in fallback_players[:max(top_n, 10)]]

    recommendation = scored[0] if scored else None
    alternative = scored[1] if len(scored) > 1 else None

    sim_summary = simulate_picks_with_context(draft_state)

    likely_available_next_pick = []
    for pid in (sim_summary.likely_available_next or [])[:5]:
        p = draft_state.player_pool.get_player(pid)
        if p is not None:
            likely_available_next_pick.append(p)
    if not likely_available_next_pick:
        if decision_scores:
            for d in sorted(decision_scores, key=lambda x: (-x.survival_probability, -x.draft_score)):
                p = draft_state.player_pool.get_player(d.player_id)
                if p is not None:
                    likely_available_next_pick.append(p)
                if len(likely_available_next_pick) >= 5:
                    break
        else:
            likely_available_next_pick = draft_state.get_available_players_by_value(5)

    likely_taken_before_next_pick = []
    seen = set()
    for sp in (sim_summary.simulated_picks or []):
        p = draft_state.player_pool.get_player(sp.player_id)
        if p is not None and p.player_id not in seen:
            seen.add(p.player_id)
            likely_taken_before_next_pick.append(p)

    ids = [c.player_id for c in scored]
    validation_results = {
        "recommendation_available": recommendation is not None and not draft_state.is_drafted(recommendation.player_id),
        "alternative_available": alternative is None or not draft_state.is_drafted(alternative.player_id),
        "no_duplicates_in_candidates": len(ids) == len(set(ids)),
    }

    explanation = "No available candidates."
    if decision_scores:
        top = decision_scores[0]
        p = draft_state.player_pool.get_player(top.player_id)
        nm = p.name if p is not None else top.player_id
        explanation = f"Top recommendation: {nm} ({top.explanation})."
    elif recommendation is not None:
        p = draft_state.player_pool.get_player(recommendation.player_id)
        nm = p.name if p is not None else recommendation.player_id
        explanation = f"Top recommendation: {nm} (fallback candidate ordering)."

    result = _build_recommendation_result(
        recommendation=recommendation,
@@ -246,50 +252,69 @@ def recommend_pick(draft_state: DraftState, top_n: int = 10) -> RecommendationRe

    if decision_scores:
        setattr(result, "recommendation_source", "DECISION_BOARD")
    else:
        setattr(result, "recommendation_source", "FALLBACK")

    opening_player_ids = [c.player_id for c in scored[:3] if getattr(c, "player_id", None)]
    path_depth = 3

    if opening_player_ids:
        if DEBUG_RECOMMENDATION_ENGINE:
            print("DEBUG: recommend_pick calling simulate_top_candidate_paths")
        path_results = simulate_top_candidate_paths(
            draft_state=draft_state,
            opening_player_ids=opening_player_ids,
            depth=path_depth,
        )
        if DEBUG_RECOMMENDATION_ENGINE:
            print("DEBUG: recommend_pick returned from simulate_top_candidate_paths")
        setattr(result, "path_results", path_results)
        setattr(result, "path_results_debug_reason", "")
    else:
        setattr(result, "path_results", [])
        setattr(result, "path_results_debug_reason", "No opening candidates available for path simulation.")

    setattr(result, "likely_available_next_ids", list(sim_summary.likely_available_next or []))
    setattr(result, "likely_gone_next_ids", list(sim_summary.likely_gone_next or []))
    setattr(result, "threatened_positions", list(sim_summary.threatened_positions or []))
    setattr(result, "preserved_positions", list(sim_summary.preserved_positions or []))
    setattr(result, "projected_team_targets", [
        {
            "team_id": int(profile.team_id),
            "target_positions": list(profile.target_positions),
            "position_urgency": dict(profile.position_urgency),
            "explanation": profile.explanation,
        }
        for profile in (sim_summary.team_need_profiles or [])
    ])

    if getattr(result, "path_results", None):
        best_path = result.path_results[0]
        setattr(result, "best_two_pick_path_score", float(getattr(best_path, "two_pick_path_score", 0.0) or 0.0))
        setattr(result, "best_three_pick_outlook", float(getattr(best_path, "three_pick_outlook", 0.0) or 0.0))

    return result


def recommend_for_user(draft_state: DraftState, top_n: int = 10) -> RecommendationResult:
    if DEBUG_RECOMMENDATION_ENGINE:
        print("DEBUG: recommend_for_user entered")

    current_team = draft_state.get_current_team_for_pick()
    user_slot = draft_state.league_config.user_draft_slot

    # If user is not on the clock, project forward to the user's next turn
    if current_team != user_slot:
        projected_state = deepcopy(draft_state)
        simulated = simulate_picks_until_next_turn(projected_state)

        for sp in simulated:
            try:
                projected_state.apply_pick_by_id(sp.player_id, by_user=False)
            except Exception:
                continue

        result = recommend_pick(draft_state=projected_state, top_n=top_n)
        setattr(result, "recommendation_context", "Projected recommendation for your next pick")
        setattr(result, "projected_from_pick", draft_state.get_current_pick_number())
        setattr(result, "projected_to_pick", projected_state.get_current_pick_number())
@@ -426,79 +451,85 @@ def normalize_scored_candidate(draft_state, scored_candidate):
        or getattr(scored_candidate, "tier", None)
        or (getattr(src_player, "metadata", {}) or {}).get("tier") if src_player else None
        or comp.get("tier")
    )

    # Score metrics
    draft_score = _norm_float(getattr(scored_candidate, "draft_score", getattr(scored_candidate, "score", 0.0)), 0.0)
    projected_points = _norm_float(
        getattr(src_player, "projected_points", None)
        if getattr(src_player, "projected_points", None) is not None
        else (
            getattr(scored_candidate, "projected_points", None)
            if getattr(scored_candidate, "projected_points", None) is not None
            else comp.get("projected_points", 0.0)
        ),
        0.0,
    )

    # Enriched component scores with canonical metric names
    normalized_comp = dict(comp)
    normalized_comp.update(
        {
            "projected_points_score": projected_points,
            "vorp_score": _pick_metric(scored_candidate, "vorp", "vorp"),
            "tier_cliff_score": _pick_metric(scored_candidate, "tier_cliff_score", "tier_cliff_score"),
            "cliff_label": comp.get("cliff_label", "none"),
            "cliff_raw_drop": _norm_float(comp.get("cliff_raw_drop", 0.0), 0.0),
            "sp_cliff_multiplier": _norm_float(comp.get("sp_cliff_multiplier", 1.0), 1.0),
            "survival_probability": _pick_metric(scored_candidate, "survival_probability", "survival_probability", 0.5),
            "team_need_pressure": _pick_metric(scored_candidate, "team_need_pressure", "team_need_pressure"),
            "roster_fit_score": _pick_metric(scored_candidate, "roster_fit_score", "roster_fit_score"),
            "take_now_edge": _pick_metric(scored_candidate, "take_now_edge", "take_now_edge"),
            "board_pressure_score": _pick_metric(scored_candidate, "board_pressure_score", "board_pressure_score"),
            "fall_bonus": _pick_metric(scored_candidate, "fall_bonus", "fall_bonus"),
            "reach_penalty": _pick_metric(scored_candidate, "reach_penalty", "reach_penalty"),
            "draft_score": draft_score,
            "adp": adp,
            "tier": tier,
            "team": team,
            "positions": positions,
            "player_name": player_name,
            "primary_position": primary_position,
        }
    )

    metadata_source_notes = []
    if src_player:
        metadata_source_notes.append("canonical")
    if getattr(scored_candidate, "team", None):
        metadata_source_notes.append("scored_team")
    if getattr(scored_candidate, "positions", None):
        metadata_source_notes.append("scored_positions")

    return SimpleNamespace(
        player_id=player_id,
        player_name=player_name,
        team=team,
        positions=positions,
        primary_position=primary_position,
        projected_points=projected_points,
        adp=adp,
        tier=tier,
        draft_score=draft_score,
        projected_points_score=projected_points,
        vorp_score=normalized_comp["vorp_score"],
        tier_cliff_score=normalized_comp["tier_cliff_score"],
        cliff_label=normalized_comp["cliff_label"],
        cliff_raw_drop=normalized_comp["cliff_raw_drop"],
        sp_cliff_multiplier=normalized_comp["sp_cliff_multiplier"],
        survival_probability=normalized_comp["survival_probability"],
        team_need_pressure=normalized_comp["team_need_pressure"],
        roster_fit_score=normalized_comp["roster_fit_score"],
        take_now_edge=normalized_comp["take_now_edge"],
        board_pressure_score=normalized_comp["board_pressure_score"],
        fall_bonus=normalized_comp["fall_bonus"],
        reach_penalty=normalized_comp["reach_penalty"],
        component_scores=normalized_comp,
        explanation=getattr(scored_candidate, "explanation", ""),
        metadata_source_notes=metadata_source_notes,
    )


def normalize_scored_candidates_for_packaging(draft_state, scored_candidates):
    """Normalize a list of scored candidates for packaging."""
    return [normalize_scored_candidate(draft_state, sc) for sc in (scored_candidates or [])]
