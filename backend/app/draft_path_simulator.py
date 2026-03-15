from dataclasses import dataclass, field
from copy import deepcopy
from statistics import mean

from app.draft_state import DraftState, get_team_for_pick
from app.opponent_model import simulate_picks_with_context
from app.draft_decision_engine import build_decision_board

DEBUG_PATH_SIM = False


@dataclass
class DraftPathResult:
    opening_player_id: str
    opening_player_name: str
    path_player_ids: list[str]
    path_player_names: list[str]
    total_path_projected_points: float
    total_path_draft_score: float
    path_roster_quality: float
    final_path_score: float
    final_roster_snapshot: list[str]
    explanation: str
    average_branch_score: float = 0.0
    branch_scores: dict[str, float] = field(default_factory=dict)
    best_branch_name: str = "best_value"
    current_pick_value: float = 0.0
    expected_next_pick_value: float = 0.0
    path_fragility: float = 0.0
    two_pick_path_score: float = 0.0
    three_pick_outlook: float = 0.0
    likely_available_next: list[str] = field(default_factory=list)
    likely_gone_next: list[str] = field(default_factory=list)
    threatened_positions: list[str] = field(default_factory=list)
    preserved_positions: list[str] = field(default_factory=list)
    projected_team_targets: list[dict] = field(default_factory=list)


def clone_draft_state(draft_state: DraftState) -> DraftState:
    return deepcopy(draft_state)


def _advance_to_next_user_pick(sim_state: DraftState):
    summary = simulate_picks_with_context(sim_state)
    simulated = summary.simulated_picks or []
    for sp in simulated:
        try:
            sim_state.apply_pick_by_id(sp.player_id, by_user=False)
        except Exception:
            continue
    return summary


def _is_user_on_clock(sim_state: DraftState) -> bool:
    if hasattr(sim_state, "get_current_team_for_pick"):
        return int(sim_state.get_current_team_for_pick()) == int(sim_state.league_config.user_draft_slot)
    current_pick = int(sim_state.get_current_pick_number())
    current_team = get_team_for_pick(current_pick, sim_state.league_config.team_count)
    return int(current_team) == int(sim_state.league_config.user_draft_slot)


def _primary_bucket(player) -> str:
    positions = list(getattr(player, "positions", []) or [])
    pos_set = set(positions)

    if "SP" in pos_set:
        return "SP"
    if "RP" in pos_set:
        return "RP"
    for b in ("C", "2B", "3B", "SS", "1B", "OF"):
        if b in pos_set:
            return b
    if pos_set == {"DH"}:
        return "UTIL"
    return "UTIL"


def _apply_pick_by_id(sim_state: DraftState, player_id: str) -> bool:
    try:
        sim_state.apply_pick_by_id(player_id, by_user=False)
        return True
    except Exception:
        return False


def _candidate_score_from_board(board_scores, player_id: str) -> float:
    for cs in (board_scores or []):
        if getattr(cs, "player_id", None) == player_id:
            return float(getattr(cs, "draft_score", 0.0) or 0.0)
    return 0.0


def _candidate_obj_from_board(board_scores, player_id: str):
    for cs in (board_scores or []):
        if getattr(cs, "player_id", None) == player_id:
            return cs
    return None


def _sp_tier_preservation_bonus(score_obj) -> tuple[float, str]:
    if score_obj is None:
        return 0.0, ""

    cliff_label = str((getattr(score_obj, "component_scores", {}) or {}).get("cliff_label", "none"))
    if cliff_label not in {"strong", "elite"}:
        return 0.0, ""

    comp = getattr(score_obj, "component_scores", {}) or {}
    bucket = str(comp.get("primary_bucket", "UTIL"))
    if bucket != "SP":
        return 0.0, ""

    cliff_score = float(getattr(score_obj, "tier_cliff_score", 0.0) or 0.0)
    survival = float(getattr(score_obj, "survival_probability", 0.0) or 0.0)
    bonus = min(2.8, (cliff_score * 0.28) + ((1.0 - survival) * 1.6))
    return bonus, f"sp_tier_preservation={cliff_label}"


def _branch_pick_key(score_obj, branch_mode: str) -> tuple:
    draft_score = float(getattr(score_obj, "draft_score", 0.0) or 0.0)
    dropoff = float(getattr(score_obj, "position_dropoff", 0.0) or 0.0)
    window_bonus = float(getattr(score_obj, "window_comparison_bonus", 0.0) or 0.0)
    deferrability = float(getattr(score_obj, "deferrability_penalty", 0.0) or 0.0)
    survival = float(getattr(score_obj, "survival_probability", 0.0) or 0.0)

    cliff_score = float(getattr(score_obj, "tier_cliff_score", 0.0) or 0.0)
    cliff_label = str((getattr(score_obj, "component_scores", {}) or {}).get("cliff_label", "none"))
    cliff_priority = 2.0 if cliff_label == "elite" else (1.0 if cliff_label == "strong" else 0.0)

    if branch_mode == "scarcity":
        return (cliff_priority, cliff_score, dropoff, window_bonus, draft_score, -deferrability)

    if branch_mode == "market_timing":
        market_score = draft_score - (1.15 * deferrability) + ((1.0 - survival) * 2.0) + (cliff_priority * 0.9)
        return (market_score, draft_score, dropoff)

    return (draft_score, dropoff, window_bonus)


def _select_candidate_by_branch(board_scores, branch_name: str) -> str | None:
    if not board_scores:
        return None

    ordered = sorted(board_scores, key=lambda cs: getattr(cs, "player_id", ""))
    ordered.sort(key=lambda cs: _branch_pick_key(cs, branch_name), reverse=True)
    return getattr(ordered[0], "player_id", None)


def _team_targets_as_dicts(summary) -> list[dict]:
    rows: list[dict] = []
    for profile in getattr(summary, "team_need_profiles", []) or []:
        rows.append(
            {
                "team_id": int(getattr(profile, "team_id", 0) or 0),
                "target_positions": list(getattr(profile, "target_positions", []) or []),
                "position_urgency": dict(getattr(profile, "position_urgency", {}) or {}),
                "explanation": str(getattr(profile, "explanation", "") or ""),
            }
        )
    return rows


def _simulate_single_branch(
    draft_state: DraftState,
    opening_player_id: str,
    depth: int,
    branch_name: str,
) -> DraftPathResult:
    sim_state = deepcopy(draft_state)
    path_ids: list[str] = []
    path_names: list[str] = []
    path_players: list = []
    total_points = 0.0
    total_draft_score = 0.0

    # Advance to user's next actual turn first
    opening_summary = simulate_picks_with_context(sim_state)
    simulated = opening_summary.simulated_picks
    for sp in simulated:
        try:
            sim_state.apply_pick_by_id(sp.player_id, by_user=False)
        except Exception:
            continue

    # opening pick now happens on user's turn
    opening_scores, _ = build_decision_board(sim_state, top_n=12)
    total_draft_score += _candidate_score_from_board(opening_scores, opening_player_id)
    opening_score_obj = _candidate_obj_from_board(opening_scores, opening_player_id)
    opening_sp_bonus, opening_sp_note = _sp_tier_preservation_bonus(opening_score_obj)
    total_draft_score += opening_sp_bonus

    if not _apply_pick_by_id(sim_state, opening_player_id):
        opening_player = draft_state.player_pool.get_player(opening_player_id)
        opening_name = opening_player.name if opening_player is not None else opening_player_id
        return DraftPathResult(
            opening_player_id=opening_player_id,
            opening_player_name=opening_name,
            path_player_ids=[],
            path_player_names=[],
            total_path_projected_points=0.0,
            total_path_draft_score=0.0,
            path_roster_quality=0.0,
            final_path_score=0.0,
            final_roster_snapshot=[],
            explanation=f"branch={branch_name} failed opening pick",
            best_branch_name=branch_name,
            average_branch_score=0.0,
            branch_scores={},
        )

    p0 = sim_state.player_pool.get_player(opening_player_id)
    path_ids.append(opening_player_id)
    path_names.append(p0.name if p0 else opening_player_id)
    if p0:
        path_players.append(p0)
        total_points += float(getattr(p0, "projected_points", 0.0) or 0.0)

    # continuation turns
    for _ in range(max(0, depth - 1)):
        loop_summary = _advance_to_next_user_pick(sim_state)

        if sim_state.get_next_user_pick() == -1:
            break

        board_scores, _ = build_decision_board(sim_state, top_n=12)
        pid = _select_candidate_by_branch(board_scores, branch_name)
        if not pid:
            break

        total_draft_score += _candidate_score_from_board(board_scores, pid)
        branch_score_obj = _candidate_obj_from_board(board_scores, pid)
        sp_branch_bonus, _ = _sp_tier_preservation_bonus(branch_score_obj)
        total_draft_score += sp_branch_bonus
        if not _apply_pick_by_id(sim_state, pid):
            break

        pp = sim_state.player_pool.get_player(pid)
        path_ids.append(pid)
        path_names.append(pp.name if pp else pid)
        if pp:
            path_players.append(pp)
            total_points += float(getattr(pp, "projected_points", 0.0) or 0.0)

    roster_quality = float(calculate_path_roster_quality(sim_state, path_players) or 0.0)
    final_score = float(total_draft_score + roster_quality)
    roster_snapshot = [rp.name for rp in sim_state.get_user_roster()]

    current_pick_value = _candidate_score_from_board(opening_scores, opening_player_id)
    next_pick_scores, _ = build_decision_board(sim_state, top_n=8)
    expected_next_pick_value = float(getattr(next_pick_scores[0], "draft_score", 0.0) or 0.0) if next_pick_scores else 0.0

    likely_gone_next = list(getattr(opening_summary, "likely_gone_next", []) or [])
    likely_available_next = list(getattr(opening_summary, "likely_available_next", []) or [])
    threatened_positions = list(getattr(opening_summary, "threatened_positions", []) or [])
    preserved_positions = list(getattr(opening_summary, "preserved_positions", []) or [])
    fragility_base = float(len(set(threatened_positions)) * 0.8)
    opening_bucket = _primary_bucket(path_players[0]) if path_players else "UTIL"
    fragility_hit = 1.6 if opening_bucket in set(threatened_positions) else 0.0
    path_fragility = round(min(10.0, fragility_base + fragility_hit), 3)

    two_pick_path_score = round(current_pick_value + expected_next_pick_value - path_fragility, 3)
    three_pick_outlook = round(final_score - path_fragility, 3)

    explanation = f"branch={branch_name}"
    if opening_sp_note:
        explanation = f"{explanation}; {opening_sp_note}"

    return DraftPathResult(
        opening_player_id=opening_player_id,
        opening_player_name=path_names[0] if path_names else opening_player_id,
        path_player_ids=path_ids,
        path_player_names=path_names,
        total_path_projected_points=round(total_points, 3),
        total_path_draft_score=round(total_draft_score, 3),
        path_roster_quality=round(roster_quality, 3),
        final_path_score=round(final_score, 3),
        final_roster_snapshot=roster_snapshot,
        explanation=explanation,
        best_branch_name=branch_name,
        average_branch_score=0.0,
        branch_scores={},
        current_pick_value=round(current_pick_value, 3),
        expected_next_pick_value=round(expected_next_pick_value, 3),
        path_fragility=path_fragility,
        two_pick_path_score=two_pick_path_score,
        three_pick_outlook=three_pick_outlook,
        likely_available_next=likely_available_next,
        likely_gone_next=likely_gone_next,
        threatened_positions=threatened_positions,
        preserved_positions=preserved_positions,
        projected_team_targets=_team_targets_as_dicts(opening_summary),
    )


def calculate_path_roster_quality(sim_state: DraftState, path_players: list) -> float:
    if not path_players:
        return 0.0

    q = 0.0
    buckets = [_primary_bucket(p) for p in path_players]
    first_three = buckets[:3]

    pitcher_count = sum(1 for b in buckets if b in {"SP", "RP"})
    sp_count = sum(1 for b in buckets if b == "SP")
    hitter_count = len(buckets) - pitcher_count

    if 1 <= pitcher_count <= 2 and 1 <= hitter_count <= 2:
        q += 2.0
    if pitcher_count >= 3:
        q -= 3.0

    non_pitcher_first3 = [b for b in first_three if b not in {"SP", "RP"}]
    dup_penalty = 0
    seen: dict[str, int] = {}
    for b in non_pitcher_first3:
        seen[b] = seen.get(b, 0) + 1
    for _, cnt in seen.items():
        if cnt > 1:
            dup_penalty += (cnt - 1)
    q -= dup_penalty * 4.0

    util_early = sum(1 for p in path_players[:3] if _primary_bucket(p) == "UTIL")
    q -= util_early * 2.0

    if len(first_three) >= 2 and first_three[0] == "SP" and first_three[1] == "SP":
        q -= 2.0
    if sp_count >= 2 and len(first_three) >= 3:
        q -= 1.5

    has_of = "OF" in buckets
    has_scarce_if = any(b in {"SS", "2B", "3B"} for b in buckets)
    has_sp = "SP" in buckets
    if has_of and has_scarce_if and has_sp:
        q += 3.0

    core_covered = sum(1 for b in {"OF", "SS", "2B", "3B", "1B", "SP"} if b in set(buckets))
    if core_covered <= 2:
        q -= 2.0

    return round(q, 3)


def simulate_path_for_opening_player(
    draft_state: DraftState,
    opening_player_id: str,
    depth: int = 3,
) -> DraftPathResult:
    if DEBUG_PATH_SIM:
        print(f"DEBUG: simulate_path_for_opening_player entered for {opening_player_id}")

    branch_names = ("best_value", "scarcity", "market_timing")
    branch_results: dict[str, DraftPathResult] = {}

    for b in branch_names:
        branch_results[b] = _simulate_single_branch(
            draft_state=draft_state,
            opening_player_id=opening_player_id,
            depth=depth,
            branch_name=b,
        )
        if DEBUG_PATH_SIM:
            print("DEBUG: path simulation complete")

    best_branch_name, best_branch_result = max(
        branch_results.items(),
        key=lambda kv: float(kv[1].final_path_score or 0.0),
    )
    avg_branch_score = mean(float(r.final_path_score or 0.0) for r in branch_results.values())
    branch_scores = {k: round(float(v.final_path_score or 0.0), 3) for k, v in branch_results.items()}

    best_branch_result.best_branch_name = best_branch_name
    best_branch_result.average_branch_score = round(avg_branch_score, 3)
    best_branch_result.branch_scores = branch_scores
    best_branch_result.explanation = f"V2 multi-branch selected={best_branch_name}; {best_branch_result.explanation}"
    return best_branch_result


def simulate_top_candidate_paths(
    draft_state: DraftState,
    opening_player_ids: list[str],
    depth: int = 3,
) -> list[DraftPathResult]:
    if DEBUG_PATH_SIM:
        print("DEBUG: simulate_top_candidate_paths entered")

    out: list[DraftPathResult] = []
    for pid in opening_player_ids:
        if DEBUG_PATH_SIM:
            print(f"DEBUG: simulating opening candidate {pid}")
        out.append(simulate_path_for_opening_player(draft_state, pid, depth=depth))

    out.sort(
        key=lambda r: (
            -float(r.final_path_score or 0.0),
            -float(r.average_branch_score or 0.0),
            -float(r.total_path_projected_points or 0.0),
            r.opening_player_id,
        )
    )
    return out
