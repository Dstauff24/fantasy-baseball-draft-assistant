from typing import Any


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _comp(sp: Any) -> dict:
    return getattr(sp, "component_scores", {}) or {}


def _metric(sp: Any, key: str, fallback_attr: str | None = None, default: float = 0.0) -> float:
    c = _comp(sp)
    if key in c:
        return _safe_float(c.get(key), default)
    if fallback_attr:
        return _safe_float(getattr(sp, fallback_attr, default), default)
    return default


def _picks_until_next(draft_state) -> int | None:
    if draft_state is None:
        return None
    try:
        cur = int(draft_state.get_current_pick_number())
        nxt = int(draft_state.get_next_user_pick())
        return max(0, nxt - cur)
    except Exception:
        return None


def build_why_now_text(scored_player: Any, draft_state=None, team_context=None) -> str:
    """Generic why-now explanation (for backward compatibility)."""
    tier = _metric(scored_player, "tier_cliff_score", "tier_cliff_score")
    survival = _metric(scored_player, "survival_probability", "survival_probability", 0.5)
    edge = _metric(scored_player, "take_now_edge", "take_now_edge")
    fit = _metric(scored_player, "roster_fit_score", "roster_fit_score")
    need = _metric(scored_player, "team_need_pressure", "team_need_pressure")
    pos = getattr(scored_player, "primary_position", None) or (getattr(scored_player, "positions", []) or ["this position"])[0]
    picks_left = _picks_until_next(draft_state)

    if survival <= 0.35 and tier >= 2.5:
        if picks_left is not None:
            return f"He likely will not make it back in {picks_left} picks, and the next tier at {pos} drops off enough to justify taking him now."
        return f"He likely will not make it back, and the next tier at {pos} falls off enough to justify taking him now."
    if fit >= 1.5 and need >= 1.0:
        return f"This is a roster-fit pick at {pos} with immediate category/need support."
    if edge >= 8.0:
        return "The immediate take-now edge over fallback options is strong."
    if tier >= 2.5:
        return f"The {pos} tier cliff is meaningful, so timing matters more than usual."
    return "Balanced recommendation with enough score support to prioritize now."


def build_wait_risk_text(scored_player: Any, draft_state=None, team_context=None) -> str:
    """Generic wait-risk explanation (for backward compatibility)."""
    survival = _metric(scored_player, "survival_probability", "survival_probability", 0.5)
    board = _metric(scored_player, "board_pressure_score", "board_pressure_score")
    loss_if_wait = _metric(scored_player, "expected_value_loss_if_wait", default=0.0)
    reach = _metric(scored_player, "reach_penalty", "reach_penalty")
    adp = _safe_float(getattr(scored_player, "adp", _comp(scored_player).get("adp", 0.0)), 0.0)

    picks_left = _picks_until_next(draft_state)
    if survival >= 0.75 and board < 4.0:
        return "He is a strong value target, but survival odds suggest you can likely wait one turn."
    if survival <= 0.35:
        if picks_left is not None:
            return f"High risk he is gone before your next turn in {picks_left} picks."
        return "High risk he is gone before your next turn."
    if reach >= 1.5 and adp > 0:
        return "This is a mild reach by ADP, but roster/tier signals may still justify the timing."
    if loss_if_wait >= 2.0:
        return "Waiting likely gives up meaningful expected value."
    return "Moderate wait risk; viable now, but not mandatory."


def build_value_summary_text(scored_player: Any) -> str:
    """Value summary across all buckets."""
    points = _metric(scored_player, "projected_points", "projected_points_score")
    vorp = _metric(scored_player, "vorp", "vorp_score")
    draft_score = _safe_float(getattr(scored_player, "draft_score", getattr(scored_player, "score", 0.0)), 0.0)
    return f"Draft score {draft_score:.2f}, projected points {points:.1f}, VORP {vorp:.2f}."


def build_roster_fit_text(scored_player: Any, team_context=None) -> str:
    """Roster fit explanation across all buckets."""
    fit = _metric(scored_player, "roster_fit_score", "roster_fit_score")
    need = _metric(scored_player, "team_need_pressure", "team_need_pressure")
    if fit >= 1.5 or need >= 1.0:
        return "Strong roster-context fit."
    if fit <= -0.5:
        return "Limited roster fit relative to alternatives."
    return "Neutral roster fit."


def build_player_tags(scored_player: Any) -> list[str]:
    """Build UI-friendly player tags."""
    tags: list[str] = []
    survival = _metric(scored_player, "survival_probability", "survival_probability", 0.5)
    tier = _metric(scored_player, "tier_cliff_score", "tier_cliff_score")
    fit = _metric(scored_player, "roster_fit_score", "roster_fit_score")
    fall_bonus = _metric(scored_player, "fall_bonus", "fall_bonus")
    board = _metric(scored_player, "board_pressure_score", "board_pressure_score")
    need = _metric(scored_player, "team_need_pressure", "team_need_pressure")

    if tier >= 2.5:
        tags.append("Tier Cliff")
    if survival <= 0.35 or board >= 6.5:
        tags.append("Likely Gone Soon")
    if fall_bonus >= 1.0:
        tags.append("Best Value")
    if fit >= 1.5:
        tags.append("Roster Fit")
    if survival >= 0.75 and board < 4.0:
        tags.append("Safe To Wait")
    if need >= 1.0:
        tags.append("Positional Need")

    return tags[:4]


def build_bucket_specific_explanation(
    scored_player: Any,
    bucket_type: str = "headline",
    explanation_style: str = "why_now",
    draft_state=None,
    team_context=None,
) -> str:
    """
    Phase 4.3 bucket-aware explanation builder.
    
    Produces differentiated copy based on bucket assignment and explanation style.
    """
    survival = _metric(scored_player, "survival_probability", "survival_probability", 0.5)
    tier_cliff = _metric(scored_player, "tier_cliff_score", "tier_cliff_score")
    board = _metric(scored_player, "board_pressure_score", "board_pressure_score")
    fall = _metric(scored_player, "fall_bonus", "fall_bonus")
    fit = _metric(scored_player, "roster_fit_score", "roster_fit_score")
    need = _metric(scored_player, "team_need_pressure", "team_need_pressure")
    edge = _metric(scored_player, "take_now_edge", "take_now_edge")
    vorp = _metric(scored_player, "vorp_score", "vorp_score")
    adp = _safe_float(getattr(scored_player, "adp", _comp(scored_player).get("adp", 0.0)), 0.0)
    pos = getattr(scored_player, "primary_position", None) or (getattr(scored_player, "positions", []) or ["this position"])[0]
    picks_left = _picks_until_next(draft_state)

    # Headline recommendation explanations
    if bucket_type == "headline":
        if explanation_style == "why_now":
            if survival <= 0.35 and tier_cliff >= 2.5:
                if picks_left:
                    return f"He likely will not survive the next {picks_left} picks, and the {pos} tier drops off sharply. Take him now."
                return f"He likely will not survive your wait, and the {pos} tier drops off sharply. Take him now."
            if fit >= 1.5 and need >= 1.0:
                return f"Best available option that addresses your roster need at {pos}. Strike now while available."
            if edge >= 8.0:
                return "Immediate value edge over all fallbacks is compelling. This is the take."
            if tier_cliff >= 2.5:
                return f"Significant {pos} tier cliff just below him. Timing justifies the pick now."
            return "Best overall available option by draft score. Recommend taking him now."
        else:  # why_not_wait
            if survival <= 0.35:
                return f"Risk is too high to wait; likely gone before your next turn."
            if board >= 6.5:
                return "Board heat is rising; market is running on him."
            return "Waiting creates moderate shortage risk with better alternatives off the board."

    # Alternate recommendation explanations
    elif bucket_type == "alternate":
        if explanation_style == "why_now":
            if edge >= 7.0:
                return f"Second-strongest urgency play at {pos}. If you want to attack the position now, he is your call."
            if fit >= 1.5:
                return f"Solid roster fit alternative and credible secondary urgency target."
            return "Strongest non-headline alternative if you want to secure the position now."
        else:  # why_not_wait
            if survival >= 0.65:
                return "Reasonable survival odds; you can likely circle back if needed."
            if board < 5.0:
                return "Board pressure is manageable; you have some breathing room."
            return "Minor wait risk, but viable fallback if you table him one turn."

    # Value fall recommendation explanations
    elif bucket_type == "value_fall":
        if explanation_style == "why_now":
            if fall >= 1.2:
                return f"One of the best remaining value profiles. Strong discount relative to early-round comps."
            if vorp >= 7.0 and adp > 0:
                return f"High VORP output at an ADP cost below where he grades. Elite value target."
            if fall >= 0.8:
                return "Solid value play relative to falling ADP. Worth considering if you have roster space."
            return f"Credible value option; grade and metrics support interest."
        else:  # why_not_wait
            if survival >= 0.78:
                return "Strong survival odds; you can likely get him at a better spot later."
            return "Value is durable; waiting does not sacrifice much."

    # Wait-on-it recommendation explanations
    elif bucket_type == "wait_on_it":
        if explanation_style == "why_now":
            if fit >= 1.2:
                return f"Grades well and fits your roster; if you take him now, solid construction."
            return "Acceptable pick if you want to be proactive, but survival odds favor waiting."
        else:  # why_not_wait
            if survival >= 0.80:
                return f"Survival odds are strong; very likely to be available at your next turn."
            if board < 3.5:
                return "Board is calm on him; minimal pressure to take early."
            if picks_left and picks_left >= 8:
                return f"With {picks_left} picks between now and your turn, he should survive at a reasonable cost."
            return "You have good odds of still getting him later; wait is a reasonable play."

    return "No specific bucket explanation available."