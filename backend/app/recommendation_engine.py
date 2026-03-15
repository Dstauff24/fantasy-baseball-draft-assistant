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
        return "SP"
    if "RP" in pos:
        return "RP"

    for hitter_pos in ["C", "1B", "2B", "3B", "SS", "OF"]:
        if hitter_pos in pos:
            return hitter_pos

    if "DH" in pos:
        return "UTIL"
    return "UTIL"


def _decision_to_candidate_score(decision) -> CandidateScore:
    comp = getattr(decision, "component_scores", {}) or {}

    comp["expected_fallback_player"] = getattr(
        decision, "expected_fallback_player", comp.get("expected_fallback_player")
    )
    comp["position_dropoff"] = float(
        getattr(decision, "position_dropoff", comp.get("position_dropoff", 0.0))
    )
    comp["position_dropoff_rank"] = float(
        getattr(decision, "position_dropoff_rank", comp.get("position_dropoff_rank", 0.0))
    )
    comp["window_comparison_bonus"] = float(
        getattr(decision, "window_comparison_bonus", comp.get("window_comparison_bonus", 0.0))
    )
    comp["board_pressure_score"] = float(
        getattr(decision, "board_pressure_score", comp.get("board_pressure_score", 0.0))
    )
    comp["next_turn_loss_risk"] = float(
        getattr(decision, "next_turn_loss_risk", comp.get("next_turn_loss_risk", 0.0))
    )
    comp["expected_value_loss_if_wait"] = float(
        getattr(decision, "expected_value_loss_if_wait", comp.get("expected_value_loss_if_wait", 0.0))
    )
    comp["run_risk_score"] = float(
        getattr(decision, "run_risk_score", comp.get("run_risk_score", 0.0))
    )
    comp["market_heat_score"] = float(
        getattr(decision, "market_heat_score", comp.get("market_heat_score", 0.0))
    )
    comp["take_now_confidence"] = float(
        getattr(decision, "take_now_confidence", comp.get("take_now_confidence", 0.0))
    )
    comp["wait_confidence"] = float(
        getattr(decision, "wait_confidence", comp.get("wait_confidence", 0.0))
    )

    cs = CandidateScore(
        player_id=decision.player_id,
        score=float(decision.draft_score),
        internal_score=float(decision.draft_score),
        component_scores=comp,
        explanation=getattr(decision, "explanation", "draft equity"),
    )
    setattr(cs, "expected_fallback_player", comp.get("expected_fallback_player"))
    setattr(cs, "position_dropoff", comp.get("position_dropoff", 0.0))
    setattr(cs, "position_dropoff_rank", int(float(comp.get("position_dropoff_rank", 0.0))))
    setattr(cs, "window_comparison_bonus", comp.get("window_comparison_bonus", 0.0))
    setattr(cs, "board_pressure_score", comp.get("board_pressure_score", 0.0))
    setattr(cs, "next_turn_loss_risk", comp.get("next_turn_loss_risk", 0.0))
    setattr(cs, "expected_value_loss_if_wait", comp.get("expected_value_loss_if_wait", 0.0))
    setattr(cs, "run_risk_score", comp.get("run_risk_score", 0.0))
    setattr(cs, "market_heat_score", comp.get("market_heat_score", 0.0))
    setattr(cs, "take_now_confidence", comp.get("take_now_confidence", 0.0))
    setattr(cs, "wait_confidence", comp.get("wait_confidence", 0.0))
    return cs


def _fallback_candidate_score(player: Player) -> CandidateScore:
    projected_points = float(getattr(player, "projected_points", 0.0) or 0.0)
    comp = {
        "projected_points": projected_points,
        "fallback_mode": True,
    }
    return CandidateScore(
        player_id=player.player_id,
        score=projected_points,
        internal_score=projected_points,
        component_scores=comp,
        explanation="fallback candidate ordering by projected points",
    )


def _build_recommendation_result(
    recommendation,
    alternative,
    candidate_scores,
    likely_available_next_pick,
    likely_taken_before_next_pick,
    validation_results,
    explanation,
):
    return RecommendationResult(
        recommendation=recommendation,
        alternative=alternative,
        candidate_scores=candidate_scores,
        likely_available_next_pick=likely_available_next_pick,
        likely_taken_before_next_pick=likely_taken_before_next_pick,
        validation_results=validation_results,
        explanation=explanation,
    )


DEBUG_RECOMMENDATION_ENGINE = False


def recommend_pick(draft_state: DraftState, top_n: int = 10) -> RecommendationResult:
    if DEBUG_RECOMMENDATION_ENGINE:
        print("DEBUG: recommend_pick entered")
    decision_scores, baselines = build_decision_board(draft_state, top_n=max(top_n, 30))
    if DEBUG_RECOMMENDATION_ENGINE:
        print("DEBUG: recommend_pick returned from build_decision_board")

    scored = [_decision_to_candidate_score(d) for d in decision_scores]

    candidate_pool_for_windows = draft_state.get_available_players_by_value(30)
    position_window_map = build_position_window_map(draft_state, candidate_pool_for_windows)
    dropoff_ranks = rank_position_dropoffs(position_window_map)

    def _bucket_from_positions(positions) -> str:
        pos = set(positions or [])
        if "SP" in pos or "P" in pos:
            return "SP"
        if "RP" in pos:
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
        alternative=alternative,
        candidate_scores=scored[:top_n],
        likely_available_next_pick=likely_available_next_pick,
        likely_taken_before_next_pick=likely_taken_before_next_pick,
        validation_results=validation_results,
        explanation=explanation,
    )

    setattr(result, "top_candidates", scored[:top_n])
    setattr(result, "decision_scores", decision_scores)
    setattr(result, "position_baselines", baselines)
    setattr(result, "position_window_map", position_window_map)
    setattr(result, "position_dropoff_ranks", dropoff_ranks)
    setattr(result, "candidate_relative_window_buckets", sorted(represented_buckets))
    setattr(result, "candidate_relative_window_ranks", candidate_relative_ranks)
    setattr(result, "generated_from_pick", draft_state.get_current_pick_number())
    setattr(result, "generated_from_team", draft_state.get_current_team_for_pick())

    team_on_clock = draft_state.get_current_team_for_pick()
    user_slot = draft_state.league_config.user_draft_slot
    context = "On the clock now" if team_on_clock == user_slot else "Projected recommendation for your next pick"
    setattr(result, "recommendation_context", context)

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
    else:
        result = recommend_pick(draft_state=draft_state, top_n=top_n)
        setattr(result, "recommendation_context", "On the clock now")

    if DEBUG_RECOMMENDATION_ENGINE:
        print("DEBUG: recommend_for_user returned from recommend_pick")
    return result


def recommend_for_user_packaged(draft_state, top_n: int = 10, include_debug: bool = False):
    """
    Phase 4 packaged response entry point.
    Keeps legacy recommend_for_user(...) unchanged for backward compatibility.
    """
    legacy_result = recommend_for_user(draft_state, top_n=top_n)

    raw_scored_players = (
        getattr(legacy_result, "top_candidates", None)
        or getattr(legacy_result, "candidate_scores", None)
        or []
    )
    scored_players = normalize_scored_candidates_for_packaging(draft_state, raw_scored_players)

    team_context = {
        "user_profile": getattr(legacy_result, "user_profile", None),
    }

    packaged = package_recommendation_response(
        scored_players=scored_players,
        draft_state=draft_state,
        team_context=team_context,
        opponent_model=None,
        include_debug=include_debug,
    )
    return packaged


def recommend_for_user_packaged_dict(draft_state, top_n: int = 10, include_debug: bool = False) -> dict:
    """JSON-friendly wrapper for API/Frontend use."""
    return to_dict(recommend_for_user_packaged(draft_state, top_n=top_n, include_debug=include_debug))


def _norm_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _candidate_comp(sc):
    return getattr(sc, "component_scores", {}) or {}


def _pick_metric(sc, comp_key: str, attr_key: str | None = None, default: float = 0.0) -> float:
    comp = _candidate_comp(sc)
    if comp_key in comp:
        return _norm_float(comp.get(comp_key), default)
    if attr_key:
        return _norm_float(getattr(sc, attr_key, default), default)
    return default


def normalize_scored_candidate(draft_state, scored_candidate):
    """
    Phase 4.2 hardened normalization:
    Enriches scored candidates with canonical Player metadata and stable metric names for packaging.
    
    Metadata priority chain:
    1. Canonical player from draft_state.player_pool (team, positions, adp, tier)
    2. Scored candidate object attributes (fallback if pool lookup fails)
    3. component_scores dict (last resort)
    4. "N/A" / None only after all sources exhausted
    """
    comp = _candidate_comp(scored_candidate)
    player_id = str(getattr(scored_candidate, "player_id", "unknown"))

    # Fetch canonical player from pool
    pool = getattr(draft_state, "player_pool", None)
    src_player = None
    if pool is not None and hasattr(pool, "get_player"):
        try:
            src_player = pool.get_player(player_id)
        except Exception:
            src_player = None

    # Build canonical metadata from source player, fallback to scored attributes, then comp
    player_name = (
        getattr(src_player, "name", None)
        or getattr(scored_candidate, "player_name", None)
        or comp.get("player_name")
        or player_id
    )

    team = (
        getattr(src_player, "mlb_team", None)
        or getattr(scored_candidate, "team", None)
        or comp.get("team")
        or "N/A"
    )

    # Preserve true eligible positions from canonical source
    positions_from_src = list(getattr(src_player, "positions", None) or []) if src_player else []
    positions_from_scored = list(getattr(scored_candidate, "positions", None) or []) if scored_candidate else []
    positions_from_comp = list(comp.get("positions", []) or [])

    # Use source positions as authoritative if available; otherwise scored; otherwise comp
    if positions_from_src:
        positions = positions_from_src
    elif positions_from_scored:
        positions = positions_from_scored
    else:
        positions = positions_from_comp or []

    primary_position = positions[0] if positions else "UTIL"

    # Preserve ADP from canonical source
    adp_raw = (
        getattr(src_player, "adp", None)
        if getattr(src_player, "adp", None) is not None
        else (
            getattr(scored_candidate, "adp", None)
            if getattr(scored_candidate, "adp", None) is not None
            else comp.get("adp", None)
        )
    )
    adp = _norm_float(adp_raw, None) if adp_raw is not None else None

    # Preserve tier from canonical source
    tier = (
        getattr(src_player, "tier", None)
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
