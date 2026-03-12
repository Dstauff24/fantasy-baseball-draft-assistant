from collections import Counter
from typing import Any

from app.explanation_builder import (
    build_bucket_specific_explanation,
    build_player_tags,
    build_roster_fit_text,
    build_value_summary_text,
)
from app.response_models import (
    DraftContextSummary,
    PackagedRecommendationResponse,
    RecommendationCard,
    RecommendationMetric,
    RiskFlag,
)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _comp(sp: Any) -> dict:
    return getattr(sp, "component_scores", {}) or {}


def _metric(sp: Any, comp_key: str, attr_key: str | None = None, default: float = 0.0) -> float:
    c = _comp(sp)
    if comp_key in c:
        return _safe_float(c.get(comp_key), default)
    if attr_key:
        return _safe_float(getattr(sp, attr_key, default), default)
    return default


def _impact(v: float) -> str:
    av = abs(v)
    if av >= 6:
        return "high"
    if av >= 2:
        return "medium"
    return "low"


def _normalize_tier(raw_tier: Any) -> str | None:
    """
    Distinguish real tier labels from numeric signals.
    
    Rules:
    - If raw_tier is a string like "Tier 1" or "Elite", return it
    - If raw_tier is numeric or numeric-looking, return None
    - Otherwise return None
    """
    if raw_tier is None:
        return None
    tier_str = str(raw_tier).strip()
    if tier_str.lower().startswith("tier"):
        return tier_str
    if tier_str in ["elite", "tier1", "tier2", "tier3", "tier4", "tier5"]:
        return tier_str
    try:
        float(tier_str)
        return None
    except ValueError:
        return tier_str if len(tier_str) > 0 else None


def build_recommendation_metric(label: str, value: float, fmt: str = "{:.2f}") -> RecommendationMetric:
    return RecommendationMetric(
        label=label,
        value=float(value),
        display_value=fmt.format(value),
        impact=_impact(value),
    )


def build_recommendation_card(
    scored_player: Any,
    recommendation_rank: int,
    bucket_type: str = "headline",
    draft_state=None,
    team_context=None,
) -> RecommendationCard:
    """Build a packaged recommendation card with bucket-aware explanation."""
    c = _comp(scored_player)

    player_id = str(getattr(scored_player, "player_id", "unknown"))
    player_name = str(getattr(scored_player, "player_name", c.get("player_name", player_id)))
    team = str(getattr(scored_player, "team", c.get("team", "N/A")))
    positions = list(getattr(scored_player, "positions", c.get("positions", [])) or [])
    if not positions:
        primary = getattr(scored_player, "primary_position", c.get("primary_position", "UTIL"))
        positions = [str(primary)]

    draft_score = _safe_float(getattr(scored_player, "draft_score", getattr(scored_player, "score", 0.0)))
    projected_points = _safe_float(
        getattr(
            scored_player,
            "projected_points",
            c.get("projected_points_score", c.get("projected_points", 0.0)),
        ),
        0.0,
    )

    adp_raw = getattr(scored_player, "adp", c.get("adp", None))
    adp = _safe_float(adp_raw, None) if adp_raw is not None else None

    raw_tier = getattr(scored_player, "tier", c.get("tier", None))
    tier = _normalize_tier(raw_tier)

    key_metrics = [
        build_recommendation_metric("draft_score", draft_score),
        build_recommendation_metric(
            "projected_points_score",
            _safe_float(c.get("projected_points_score", projected_points)),
            "{:.1f}",
        ),
        build_recommendation_metric("vorp_score", _safe_float(c.get("vorp_score", c.get("vorp", 0.0)))),
        build_recommendation_metric("tier_cliff_score", _safe_float(c.get("tier_cliff_score", 0.0))),
        build_recommendation_metric(
            "survival_probability",
            _safe_float(c.get("survival_probability", 0.5)),
            "{:.2f}",
        ),
        build_recommendation_metric("team_need_pressure", _safe_float(c.get("team_need_pressure", 0.0))),
        build_recommendation_metric("roster_fit_score", _safe_float(c.get("roster_fit_score", 0.0))),
        build_recommendation_metric("take_now_edge", _safe_float(c.get("take_now_edge", 0.0))),
    ]

    why_now = build_bucket_specific_explanation(
        scored_player,
        bucket_type=bucket_type,
        explanation_style="why_now",
        draft_state=draft_state,
        team_context=team_context,
    )
    why_not_wait = build_bucket_specific_explanation(
        scored_player,
        bucket_type=bucket_type,
        explanation_style="why_not_wait",
        draft_state=draft_state,
        team_context=team_context,
    )

    return RecommendationCard(
        player_id=player_id,
        player_name=player_name,
        team=team,
        positions=positions,
        recommendation_rank=int(recommendation_rank),
        draft_score=round(draft_score, 3),
        projected_points=round(projected_points, 3),
        adp=adp,
        tier=tier,
        why_now=why_now,
        why_not_wait=why_not_wait,
        key_metrics=key_metrics,
        tags=build_player_tags(scored_player),
    )


def _urgency_rank(p: Any) -> float:
    """Score for urgency-ranked candidates (headline + alternates)."""
    draft_score = _safe_float(getattr(p, "draft_score", getattr(p, "score", 0.0)))
    take_now = _metric(p, "take_now_edge", "take_now_edge", 0.0)
    tier_cliff = _metric(p, "tier_cliff_score", "tier_cliff_score", 0.0)
    survival = _metric(p, "survival_probability", "survival_probability", 0.5)
    survival_penalty = (1.0 - survival) * 2.0
    return draft_score + (take_now * 0.3) + (tier_cliff * 0.25) - survival_penalty


def _value_rank(p: Any) -> float:
    """Score for value-ranked candidates (value_falls)."""
    fall = _metric(p, "fall_bonus", "fall_bonus", 0.0)
    vorp = _metric(p, "vorp_score", "vorp_score", 0.0)
    draft_score = _safe_float(getattr(p, "draft_score", getattr(p, "score", 0.0)))
    return (fall * 3.0) + (vorp * 0.5) + (draft_score * 0.2)


def _wait_rank(p: Any) -> float:
    """Score for wait-on-it candidates."""
    survival = _metric(p, "survival_probability", "survival_probability", 0.5)
    board = _metric(p, "board_pressure_score", "board_pressure_score", 0.0)
    draft_score = _safe_float(getattr(p, "draft_score", getattr(p, "score", 0.0)))
    return (survival * 5.0) - (board * 0.5) + (draft_score * 0.1)


def _is_wait_qualified(p: Any) -> bool:
    """
    Phase 4 final polish: wait-on-it qualification thresholds.
    
    A candidate qualifies for wait-on-it if:
    - survival_probability >= 0.75 (strong likelihood of availability)
    - board_pressure_score <= 4.5 (modest market attention)
    - draft_score >= 25.0 (minimum acceptable quality floor)
    """
    survival = _metric(p, "survival_probability", "survival_probability", 0.5)
    board = _metric(p, "board_pressure_score", "board_pressure_score", 0.0)
    draft_score = _safe_float(getattr(p, "draft_score", getattr(p, "score", 0.0)))
    
    return survival >= 0.75 and board <= 4.5 and draft_score >= 25.0


def split_recommendation_buckets(scored_players: list[Any], draft_state=None) -> dict[str, list[Any]]:
    """
    Phase 4 final polish: reserved bucket allocation with guaranteed wait-on-it.
    
    Strategy:
    1. Headline = top 1 overall
    2. Alternates = top 1-2 urgency plays (reserves qualified wait candidates first)
    3. Wait-on-it = best qualified wait candidate(s) from reserve pool
    4. Value falls = best value profiles from remaining pool
    5. Optional second wait = fill if another strong wait candidate qualifies
    """
    ordered = sorted(
        scored_players,
        key=lambda x: _safe_float(getattr(x, "draft_score", getattr(x, "score", 0.0)), 0.0),
        reverse=True,
    )
    if not ordered:
        return {"headline": [], "alternates": [], "value_falls": [], "wait_on_it": []}

    headline = [ordered[0]]
    used_ids = {getattr(ordered[0], "player_id", None)}

    def _pid(p: Any):
        return getattr(p, "player_id", None)

    remaining = [p for p in ordered[1:] if _pid(p) not in used_ids]

    # Pre-scan: identify wait-qualified candidates and reserve best one
    wait_qualified = [p for p in remaining if _is_wait_qualified(p)]
    wait_qualified_sorted = sorted(wait_qualified, key=_wait_rank, reverse=True)
    reserved_wait_primary = wait_qualified_sorted[0] if wait_qualified_sorted else None
    reserved_wait_secondary = wait_qualified_sorted[1] if len(wait_qualified_sorted) > 1 else None

    # Stage 1: Pick alternates from urgency-ranked remaining (excluding reserved waits)
    urgency_pool = [p for p in remaining if _pid(p) not in {_pid(reserved_wait_primary), _pid(reserved_wait_secondary)}]
    urgency_ranked = sorted(urgency_pool, key=_urgency_rank, reverse=True)
    alternates = urgency_ranked[:2]
    for p in alternates:
        used_ids.add(_pid(p))

    remaining2 = [p for p in remaining if _pid(p) not in used_ids]

    # Stage 2: Assign reserved wait primary
    wait_on_it = []
    if reserved_wait_primary and _pid(reserved_wait_primary) not in used_ids:
        wait_on_it.append(reserved_wait_primary)
        used_ids.add(_pid(reserved_wait_primary))

    remaining3 = [p for p in remaining2 if _pid(p) not in used_ids]

    # Stage 3: Pick value candidates from remaining
    value_candidates = sorted(remaining3, key=_value_rank, reverse=True)
    value_falls = [
        p for p in value_candidates
        if _metric(p, "fall_bonus", "fall_bonus", 0.0) >= 0.4 or _metric(p, "vorp_score", default=0.0) >= 5.0
    ][:2]
    for p in value_falls:
        used_ids.add(_pid(p))

    remaining4 = [p for p in remaining3 if _pid(p) not in used_ids]

    # Stage 4: Optionally add reserved wait secondary if not already used
    if reserved_wait_secondary and _pid(reserved_wait_secondary) not in used_ids:
        wait_on_it.append(reserved_wait_secondary)
        used_ids.add(_pid(reserved_wait_secondary))

    return {
        "headline": headline,
        "alternates": alternates,
        "value_falls": value_falls,
        "wait_on_it": wait_on_it,
    }


def build_risk_flags(scored_players: list[Any], draft_state, team_context) -> list[RiskFlag]:
    """Build risk flags from top candidates."""
    flags: list[RiskFlag] = []
    for sp in scored_players[:6]:
        player_name = getattr(sp, "player_name", getattr(sp, "player_id", "Player"))
        survival = _metric(sp, "survival_probability", "survival_probability", 0.5)
        tier_cliff = _metric(sp, "tier_cliff_score", "tier_cliff_score")
        fit = _metric(sp, "roster_fit_score", "roster_fit_score")
        reach = _metric(sp, "reach_penalty", "reach_penalty")

        if survival <= 0.25:
            flags.append(
                RiskFlag(
                    "availability",
                    "high",
                    f"{player_name} may be gone",
                    "Low survival probability before your next pick.",
                )
            )
        if tier_cliff >= 3.0:
            flags.append(
                RiskFlag(
                    "tier_drop",
                    "medium",
                    f"{player_name} sits above a cliff",
                    "Fallback options at this position drop quickly.",
                )
            )
        if fit <= -0.5:
            flags.append(
                RiskFlag(
                    "roster_fit",
                    "low",
                    f"{player_name} has weaker fit",
                    "Comparable options may align better with current roster needs.",
                )
            )
        if reach >= 2.0:
            flags.append(
                RiskFlag(
                    "adp_reach",
                    "medium",
                    f"{player_name} is a reach",
                    "ADP cost appears ahead of market expectation.",
                )
            )

    return flags[:6]


def build_draft_context_summary(draft_state, team_context, opponent_model=None) -> DraftContextSummary:
    """Build draft context snapshot."""
    current_pick = int(getattr(draft_state, "get_current_pick_number", lambda: 0)() or 0)
    next_user_pick = getattr(draft_state, "get_next_user_pick", lambda: None)()
    next_user_pick = int(next_user_pick) if next_user_pick is not None else None

    # Intervening picks before the user is back on the clock.
    teams_until_next_pick = max(0, ((next_user_pick or current_pick) - current_pick - 1))

    roster = getattr(draft_state, "get_user_roster", lambda: [])() or []
    roster_snapshot = {
        "count": len(roster),
        "players": [getattr(p, "name", getattr(p, "player_id", "unknown")) for p in roster],
        "positions": ["/".join(getattr(p, "positions", []) or []) for p in roster],
    }

    pos_counter = Counter()
    for p in roster:
        for pos in getattr(p, "positions", []) or []:
            pos_counter[pos] += 1

    positional_pressure = {
        "counts": dict(pos_counter),
        "team_need_pressure": team_context.get("team_need_pressure", {}) if isinstance(team_context, dict) else {},
    }

    likely_run_positions = []
    if isinstance(opponent_model, dict):
        likely_run_positions = list(opponent_model.get("likely_run_positions", []) or [])
    if not likely_run_positions:
        likely_run_positions = [pos for pos, _ in pos_counter.most_common(3)]

    return DraftContextSummary(
        current_pick=current_pick,
        next_user_pick=next_user_pick,
        teams_until_next_pick=teams_until_next_pick,
        roster_snapshot=roster_snapshot,
        positional_pressure=positional_pressure,
        likely_run_positions=likely_run_positions,
    )


def build_strategic_explanation(top_pick: Any, draft_state, team_context, opponent_model=None) -> list[str]:
    """Build strategic explanation lines."""
    lines = [
        build_bucket_specific_explanation(top_pick, "headline", "why_now", draft_state, team_context),
        build_bucket_specific_explanation(top_pick, "headline", "why_not_wait", draft_state, team_context),
        build_value_summary_text(top_pick),
        build_roster_fit_text(top_pick, team_context=team_context),
    ]
    return [ln for ln in lines if ln]


def package_recommendation_response(
    scored_players: list[Any],
    draft_state,
    team_context,
    opponent_model=None,
    include_debug: bool = False,
) -> PackagedRecommendationResponse:
    """Package scored candidates into frontend-ready response."""
    buckets = split_recommendation_buckets(scored_players, draft_state=draft_state)
    headline_sp = buckets["headline"][0] if buckets["headline"] else None
    if headline_sp is None:
        raise ValueError("No scored players available to package.")

    headline = build_recommendation_card(headline_sp, 1, "headline", draft_state, team_context)
    alternates = [
        build_recommendation_card(sp, i + 2, "alternate", draft_state, team_context)
        for i, sp in enumerate(buckets["alternates"])
    ]
    value_falls = [
        build_recommendation_card(sp, i + 1, "value_fall", draft_state, team_context)
        for i, sp in enumerate(buckets["value_falls"])
    ]
    wait_on_it = [
        build_recommendation_card(sp, i + 1, "wait_on_it", draft_state, team_context)
        for i, sp in enumerate(buckets["wait_on_it"])
    ]

    risk_flags = build_risk_flags(scored_players, draft_state, team_context)
    draft_context = build_draft_context_summary(draft_state, team_context, opponent_model=opponent_model)
    strategic_explanation = build_strategic_explanation(
        headline_sp,
        draft_state,
        team_context,
        opponent_model=opponent_model,
    )

    raw_debug: dict[str, Any] = {}
    if include_debug:
        raw_debug = {
            "top_candidate_scores": [
                {
                    "player_id": getattr(sp, "player_id", "unknown"),
                    "player_name": getattr(sp, "player_name", getattr(sp, "player_id", "unknown")),
                    "team": getattr(sp, "team", "N/A"),
                    "positions": list(getattr(sp, "positions", []) or []),
                    "draft_score": _safe_float(getattr(sp, "draft_score", getattr(sp, "score", 0.0))),
                    "survival_probability": _metric(sp, "survival_probability", "survival_probability", 0.5),
                    "board_pressure_score": _metric(sp, "board_pressure_score", "board_pressure_score", 0.0),
                    "urgency_rank": _urgency_rank(sp),
                    "value_rank": _value_rank(sp),
                    "wait_rank": _wait_rank(sp),
                    "is_wait_qualified": _is_wait_qualified(sp),
                    "metadata_source_notes": getattr(sp, "metadata_source_notes", []),
                }
                for sp in sorted(
                    scored_players,
                    key=lambda x: _safe_float(getattr(x, "draft_score", getattr(x, "score", 0.0))),
                    reverse=True,
                )[:10]
            ],
            "bucket_sizes": {k: len(v) for k, v in buckets.items()},
        }

    return PackagedRecommendationResponse(
        headline_recommendation=headline,
        alternate_recommendations=alternates,
        value_falls=value_falls,
        wait_on_it_candidates=wait_on_it,
        risk_flags=risk_flags,
        strategic_explanation=strategic_explanation,
        draft_context=draft_context,
        raw_debug=raw_debug,
    )


def get_user_team_profile(draft_state: Any) -> dict[str, Any]:
    """
    Extract user team roster snapshot.
    Resolves player_id strings to Player objects via player_pool.
    """
    user_slot = getattr(draft_state, "user_slot", 1)
    team_rosters = getattr(draft_state, "team_rosters", {})
    player_pool = getattr(draft_state, "player_pool", None)

    # Get the list of player_id strings for user's slot
    user_roster_ids = team_rosters.get(user_slot, [])

    players = []
    positions = []

    # Resolve each player_id string to actual Player object
    for player_id in user_roster_ids:
        if not isinstance(player_id, str):
            continue

        player = None

        # Try direct lookup in players_by_id
        if player_pool and hasattr(player_pool, "players_by_id"):
            player = player_pool.players_by_id.get(player_id)

        # Fallback: try get_player() method
        if not player and player_pool and callable(getattr(player_pool, "get_player", None)):
            player = player_pool.get_player(player_id)

        if player:
            player_name = getattr(player, "name", "Unknown")
            player_positions = getattr(player, "positions", ())
            players.append(player_name)
            if isinstance(player_positions, (list, tuple)):
                positions.extend(player_positions)

    return {
        "slot": user_slot,
        "count": len(players),
        "players": players,
        "positions": list(dict.fromkeys(positions)),  # deduplicated
    }


def get_draft_context(draft_state: Any) -> dict[str, Any]:
    """
    Extract draft context with current_pick from DraftState.
    """
    current_pick = getattr(draft_state, "current_pick", 1)
    user_slot = getattr(draft_state, "user_slot", 1)
    teams = len(getattr(draft_state, "team_rosters", {})) or 1

    # Compute next user pick (snake draft logic)
    picks_per_round = teams
    current_round = (current_pick - 1) // picks_per_round
    in_round_slot = (current_pick - 1) % picks_per_round

    # Standard snake: odd rounds reverse
    is_reverse_round = current_round % 2 == 1
    if is_reverse_round:
        next_slot = teams - in_round_slot
    else:
        next_slot = in_round_slot + 1

    teams_until_next_pick = (next_slot - user_slot) % teams
    next_user_pick = current_pick + teams_until_next_pick + 1

    return {
        "current_pick": current_pick,
        "user_slot": user_slot,
        "teams": teams,
        "teams_until_next_pick": teams_until_next_pick,
        "next_user_pick": next_user_pick,
    }