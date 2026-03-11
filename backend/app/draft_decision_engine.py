from dataclasses import dataclass, field

from app.draft_state import DraftState, get_team_for_pick
from app.board_pressure_engine import calculate_board_pressure_score
from app.opponent_model import analyze_player_availability
from app.draft_context_engine import build_draft_context
from app.team_profile_engine import (
    get_user_team_profile,
    calculate_category_balance_bonus_with_components,
)
from app.models import Player
from app import team_profile_engine as _team_profile_engine


@dataclass
class PositionBaseline:
    position: str
    replacement_points: float
    replacement_player_id: str | None


@dataclass
class PlayerDecisionScore:
    player_id: str
    draft_score: float
    projected_points: float
    vorp: float
    tier_cliff_score: float
    survival_probability: float
    team_need_pressure: float
    roster_fit_score: float
    take_now_edge: float
    expected_fallback_player: str | None
    position_dropoff: float
    position_dropoff_rank: int
    window_comparison_bonus: float
    reach_penalty: float
    fall_bonus: float
    category_balance_bonus: float
    deferrability_penalty: float = 0.0

    board_pressure_score: float = 0.0
    next_turn_loss_risk: float = 0.0
    expected_value_loss_if_wait: float = 0.0
    run_risk_score: float = 0.0
    market_heat_score: float = 0.0
    take_now_confidence: float = 0.0
    wait_confidence: float = 0.0

    explanation: str = ""
    component_scores: dict = field(default_factory=dict)


_BUCKET_ORDER = ("C", "2B", "3B", "SS", "1B", "OF")
_BASELINE_STARTERS = {
    "C": 12,
    "1B": 12,
    "2B": 12,
    "3B": 12,
    "SS": 12,
    "OF": 36,
    "SP": 60,
    "RP": 24,
    "UTIL": 12,
}


def _is_pitcher(player: Player) -> bool:
    return any(pos in {"SP", "RP", "P"} for pos in player.positions)


def _primary_position_bucket(player) -> str:
    positions = set(player.positions)
    if "SP" in positions or "P" in positions:
        return "SP"
    if "RP" in positions:
        return "RP"
    for pos in _BUCKET_ORDER:
        if pos in positions:
            return pos
    return "UTIL"


def _position_roster_baseline_index(draft_state: DraftState, position: str) -> int:
    starters = _BASELINE_STARTERS.get(position, 12)
    return max(0, starters - 1)


def _players_in_bucket(draft_state: DraftState, bucket: str) -> list[Player]:
    players = [p for p in draft_state.get_available_players_by_value() if _primary_position_bucket(p) == bucket]
    players.sort(key=lambda p: (-(p.projected_points or 0.0), p.player_id))
    return players


def build_replacement_baselines(draft_state: DraftState) -> dict[str, PositionBaseline]:
    baselines: dict[str, PositionBaseline] = {}
    for pos in ["C", "1B", "2B", "3B", "SS", "OF", "SP", "RP", "UTIL"]:
        players = _players_in_bucket(draft_state, pos)
        if not players:
            baselines[pos] = PositionBaseline(position=pos, replacement_points=0.0, replacement_player_id=None)
            continue

        idx = _position_roster_baseline_index(draft_state, pos)
        idx = min(idx, len(players) - 1)
        repl = players[idx]
        baselines[pos] = PositionBaseline(
            position=pos,
            replacement_points=float(repl.projected_points or 0.0),
            replacement_player_id=repl.player_id,
        )
    return baselines


def calculate_player_vorp(draft_state: DraftState, player, baselines: dict[str, PositionBaseline]) -> float:
    projected = float(player.projected_points or 0.0)
    bucket = _primary_position_bucket(player)
    baseline = baselines.get(bucket)
    if baseline is None:
        return projected
    return projected - baseline.replacement_points


def detect_tier_cliff_score(draft_state: DraftState, player) -> float:
    bucket = _primary_position_bucket(player)
    players = _players_in_bucket(draft_state, bucket)
    if not players:
        return 0.0

    idx = next((i for i, p in enumerate(players) if p.player_id == player.player_id), -1)
    if idx < 0:
        return 0.0

    current_pts = float(player.projected_points or 0.0)

    # modest last-meaningful-player bump
    if idx == len(players) - 1:
        return 1.0

    next_pts = float(players[idx + 1].projected_points or 0.0)
    drop = current_pts - next_pts
    if drop >= 35:
        return 5.0
    if drop >= 20:
        return 3.0
    if drop >= 10:
        return 1.5
    return 0.0


def _team_bucket_counts(draft_state: DraftState, team_id: int) -> dict[str, int]:
    counts = {k: 0 for k in ["C", "1B", "2B", "3B", "SS", "OF", "SP", "RP", "UTIL"]}
    for pid in draft_state.team_rosters.get(team_id, []):
        p = draft_state.player_pool.get_player(pid)
        if p is None:
            continue
        b = _primary_position_bucket(p)
        counts[b] = counts.get(b, 0) + 1
    return counts


def _team_needs_bucket(team_counts: dict[str, int], bucket: str) -> bool:
    if bucket == "OF":
        return team_counts.get("OF", 0) < 2
    if bucket == "SP":
        return team_counts.get("SP", 0) < 2
    if bucket == "RP":
        return team_counts.get("RP", 0) < 1
    if bucket in {"C", "1B", "2B", "3B", "SS"}:
        return team_counts.get(bucket, 0) < 1
    return team_counts.get("UTIL", 0) < 1


def calculate_team_need_pressure_for_bucket(draft_state: DraftState, bucket: str) -> float:
    current_pick = draft_state.get_current_pick_number()
    next_user_pick = draft_state.get_next_user_pick()

    pressure = 0.0
    for pick in range(current_pick, next_user_pick):
        team_id = get_team_for_pick(pick, draft_state.league_config.team_count)
        if team_id == draft_state.league_config.user_draft_slot:
            continue
        counts = _team_bucket_counts(draft_state, team_id)
        if _team_needs_bucket(counts, bucket):
            pressure += 1.5

    if bucket in {"2B", "3B", "SS", "SP"}:
        pressure += 1.0

    return max(0.0, min(10.0, pressure))


def calculate_team_need_pressure(draft_state: DraftState, player) -> float:
    bucket = _primary_position_bucket(player)
    return calculate_team_need_pressure_for_bucket(draft_state, bucket)


def get_position_candidates_with_survival(
    draft_state: DraftState,
    position_bucket: str
) -> list[tuple[Player, float, float]]:
    players = _players_in_bucket(draft_state, position_bucket)
    rows: list[tuple[Player, float, float]] = []
    for p in players:
        surv = float(estimate_survival_probability(draft_state, p))
        pts = float(p.projected_points or 0.0)
        rows.append((p, surv, pts))

    rows.sort(key=lambda t: (-t[2], -t[1], t[0].player_id))
    return rows


def estimate_expected_position_fallback(
    draft_state: DraftState,
    position_bucket: str,
    exclude_player_id: str | None = None
) -> Player | None:
    rows = get_position_candidates_with_survival(draft_state, position_bucket)
    if not rows:
        return None

    def _filtered(min_survival: float | None) -> list[tuple[Player, float, float]]:
        out: list[tuple[Player, float, float]] = []
        for p, surv, pts in rows:
            if exclude_player_id and p.player_id == exclude_player_id:
                continue
            if min_survival is None or surv >= min_survival:
                out.append((p, surv, pts))
        return out

    preferred = _filtered(0.55)
    if preferred:
        return preferred[0][0]

    relaxed = _filtered(0.35)
    if relaxed:
        return relaxed[0][0]

    remaining = _filtered(None)
    if remaining:
        return remaining[0][0]

    return None


def build_position_window_map(
    draft_state: DraftState,
    candidate_players: list
) -> dict[str, dict]:
    by_bucket: dict[str, Player] = {}
    for p in candidate_players:
        b = _primary_position_bucket(p)
        cur = by_bucket.get(b)
        if cur is None or float(p.projected_points or 0.0) > float(cur.projected_points or 0.0):
            by_bucket[b] = p

    # Include represented buckets + debug buckets (C/2B/3B) if players exist.
    buckets_to_build = set(by_bucket.keys())
    for b in _WINDOW_DEBUG_BUCKETS:
        if _players_in_bucket(draft_state, b):
            buckets_to_build.add(b)

    window_map: dict[str, dict] = {}
    for bucket in buckets_to_build:
        # current best: candidate-pool leader if present, else overall best available in bucket
        best_player = by_bucket.get(bucket)
        if best_player is None:
            bucket_players = _players_in_bucket(draft_state, bucket)
            if not bucket_players:
                continue
            best_player = bucket_players[0]

        fallback = estimate_expected_position_fallback(
            draft_state,
            bucket,
            exclude_player_id=best_player.player_id,
        )

        best_pts = float(best_player.projected_points or 0.0)
        fallback_pts = float(fallback.projected_points or 0.0) if fallback is not None else 0.0
        dropoff = max(0.0, best_pts - fallback_pts) if fallback is not None else 0.0

        fallback_survival_probability = (
            float(estimate_survival_probability(draft_state, fallback)) if fallback is not None else 0.0
        )

        window_map[bucket] = {
            "current_best_player_id": best_player.player_id,
            "fallback_player_id": fallback.player_id if fallback is not None else None,
            "fallback_player_name": fallback.name if fallback is not None else None,
            "fallback_survival_probability": round(fallback_survival_probability, 3),
            "dropoff": round(dropoff, 3),
            "rank": 0,
        }

    ranks = rank_position_dropoffs(window_map)
    for b, r in ranks.items():
        if b in window_map:
            window_map[b]["rank"] = int(r)

    return window_map


def rank_position_dropoffs(position_window_map: dict[str, dict]) -> dict[str, int]:
    ordered = sorted(
        position_window_map.items(),
        key=lambda kv: (-(float(kv[1].get("dropoff", 0.0))), kv[0]),
    )
    return {bucket: idx + 1 for idx, (bucket, _) in enumerate(ordered)}


def calculate_window_comparison_bonus(
    player,
    position_window_map: dict[str, dict],
    dropoff_ranks: dict[str, int]
) -> float:
    bucket = _primary_position_bucket(player)
    row = position_window_map.get(bucket, {})

    dropoff = float(row.get("dropoff", 0.0) or 0.0)
    rank = int(dropoff_ranks.get(bucket, 999))

    # Existing rank-based base bonus
    base = 0.0
    if rank == 1:
        base = 4.0
    elif rank == 2:
        base = 2.0
    elif rank == 3:
        base = 1.0

    # Existing dropoff-size scaling
    if dropoff < 8.0:
        base *= 0.5
    elif dropoff < 15.0:
        base *= 0.75

    # NEW: only bucket leader gets full bonus; same-bucket non-leaders get reduced carryover
    current_best_player_id = row.get("current_best_player_id")
    is_bucket_leader = bool(current_best_player_id) and (player.player_id == current_best_player_id)
    if not is_bucket_leader:
        base *= 0.40  # default non-leader fraction (40%)

    return round(base, 3)


def rank_position_dropoffs_for_buckets(
    position_window_map: dict[str, dict],
    included_buckets: set[str],
) -> dict[str, int]:
    filtered = {b: row for b, row in position_window_map.items() if b in included_buckets}
    if not filtered:
        return {}
    ordered = sorted(
        filtered.items(),
        key=lambda kv: (-(float(kv[1].get("dropoff", 0.0))), kv[0]),
    )
    return {bucket: idx + 1 for idx, (bucket, _) in enumerate(ordered)}


def build_decision_board(
    draft_state: DraftState, top_n: int = 15
) -> tuple[list[PlayerDecisionScore], dict[str, PositionBaseline]]:
    if DEBUG_DECISION_ENGINE:
        print("DEBUG: build_decision_board entered")
    baselines = build_replacement_baselines(draft_state)
    candidate_pool = draft_state.get_available_players_by_value(50)
    draft_context = build_draft_context(draft_state)  # NEW
    if DEBUG_DECISION_ENGINE:
        print(f"DEBUG: candidate_pool size = {len(candidate_pool)}")

    if DEBUG_DECISION_ENGINE:
        print("DEBUG: build_decision_board starting scoring loop")

    # Candidate-pool bucket leaders (top projected per represented bucket)
    bucket_leaders: dict[str, Player] = {}
    for p in candidate_pool:
        b = _primary_position_bucket(p)
        cur = bucket_leaders.get(b)
        if cur is None or float(p.projected_points or 0.0) > float(cur.projected_points or 0.0):
            bucket_leaders[b] = p
    bucket_leader_map = {b: p.player_id for b, p in bucket_leaders.items()}

    position_window_map = build_position_window_map(draft_state, candidate_pool)
    represented_buckets = {_primary_position_bucket(p) for p in candidate_pool}
    candidate_dropoff_ranks = rank_position_dropoffs_for_buckets(position_window_map, represented_buckets)

    scored: list[PlayerDecisionScore] = []
    for idx, player in enumerate(candidate_pool):
        if DEBUG_DECISION_ENGINE and idx < 3:
            print(f"DEBUG: scoring candidate {player.name}")
        scored.append(
            score_draft_candidate(
                draft_state,
                player,
                baselines,
                position_window_map,
                candidate_dropoff_ranks,
                bucket_leader_map,  # NEW
                draft_context,  # NEW
            )
        )

    scored.sort(key=lambda s: (-s.draft_score, s.player_id))
    if DEBUG_DECISION_ENGINE:
        print("DEBUG: build_decision_board finished scoring")
    return scored[: max(top_n, 1)], baselines


def estimate_survival_probability(draft_state: DraftState, player) -> float:
    """
    Pass-through survival score from opponent_model (0..1).
    """
    report = analyze_player_availability(draft_state, player.player_id)
    raw = getattr(report, "estimated_survival_score", None)
    if raw is None:
        raw = getattr(report, "survival_probability", 0.5)
    return max(0.0, min(1.0, float(raw)))


def _projected_value_component(draft_state: DraftState, player) -> float:
    """
    Restores projected value separation (target ~8..22 for top candidates).
    Deterministic quantile scaling from available pool.
    """
    pts = float(player.projected_points or 0.0)
    avail = draft_state.get_available_players_by_value(180)
    values = sorted(float(p.projected_points or 0.0) for p in avail if p is not None)
    if len(values) < 8:
        return max(0.0, min(22.0, pts / 24.0))

    n = len(values)
    p20 = values[int(0.20 * (n - 1))]
    p95 = values[int(0.95 * (n - 1))]
    span = max(1e-6, p95 - p20)
    norm = max(0.0, min(1.0, (pts - p20) / span))

    # bounded contribution
    return round(6.0 + (16.0 * norm), 3)  # 6..22


def _wait_penalty_from_survival(survival_probability: float) -> float:
    """
    High survival => meaningful wait penalty.
    Low survival => near-zero wait penalty.
    """
    s = max(0.0, min(1.0, float(survival_probability)))
    if s >= 0.85:
        return 9.0
    if s >= 0.60:
        # 0.60 -> 4.0, 0.85 -> 9.0
        return 4.0 + ((s - 0.60) / 0.25) * 5.0
    return (s / 0.60) * 4.0


def calculate_roster_fit_score(draft_state: DraftState, player) -> float:
    """
    Non-flat roster-fit signal.
    """
    current_pick = draft_state.get_current_pick_number()
    user_roster = draft_state.get_user_roster()

    user_sp_count = sum(1 for p in user_roster if "SP" in p.positions)
    user_rp_count = sum(1 for p in user_roster if "RP" in p.positions and "SP" not in p.positions)

    bucket = _primary_position_bucket(player)

    if bucket in {"C", "1B", "2B", "3B", "SS", "OF", "UTIL"}:
        score = 1.8
        if current_pick <= 60 and user_sp_count >= 1:
            score += 1.2
        if bucket in {"SS", "2B", "3B"}:
            score += 2.0
        elif bucket == "OF":
            score += 0.9
        elif bucket == "UTIL" or set(getattr(player, "positions", ()) or ()) == {"DH"}:
            score -= 1.0
        return score

    if bucket == "SP":
        score = -1.5
        if current_pick <= 36 and user_sp_count >= 1:
            score -= 2.5
        if current_pick <= 60 and user_sp_count >= 2:
            score -= 3.0
        return score

    if bucket == "RP":
        score = -0.8
        if current_pick <= 75:
            score -= 1.0
        if user_rp_count >= 2:
            score -= 0.8
        return score

    return 0.0

def calculate_deferrability_penalty(
    draft_state: DraftState,
    player,
    is_positional_leader: bool | None = None,
) -> float:
    """
    Bounded market-timing penalty (tie-breaker, not dominant).
    Target range: 0.0 .. 5.5
    """
    survival = float(estimate_survival_probability(draft_state, player) or 0.0)
    if survival < 0.35:
        return 0.0

    next_user_pick = float(_safe_next_user_pick(draft_state))
    adp = float(getattr(player, "adp", 0.0) or 0.0)
    adp_after_next = max(0.0, adp - next_user_pick) if adp > 0.0 else 0.0

    # 0.35..0.60 -> 0.5..1.5
    if survival < 0.60:
        t = (survival - 0.35) / 0.25
        penalty = 0.5 + (1.0 * t)

    # 0.60..0.80 -> 1.5..3.0
    elif survival < 0.80:
        t = (survival - 0.60) / 0.20
        penalty = 1.5 + (1.5 * t)

    # >0.80 -> base 3.0..4.5, small ADP-after-next increment
    else:
        t = min(1.0, (survival - 0.80) / 0.20)
        penalty = 3.0 + (1.5 * t)  # 3.0..4.5

        if adp_after_next > 0.0:
            penalty += min(0.75, adp_after_next * 0.06)  # modest timing increment
            if adp_after_next >= 8.0:
                penalty += 0.20
                if is_positional_leader is False:
                    penalty += 0.15

    return round(min(5.5, max(0.0, penalty)), 3)


def _safe_next_user_pick(draft_state: DraftState) -> int:
    if hasattr(draft_state, "get_next_user_pick"):
        return int(draft_state.get_next_user_pick())
    if hasattr(draft_state, "get_next_user_pick_number"):
        return int(draft_state.get_next_user_pick_number())
    return int(draft_state.get_current_pick_number())


def _safe_points(player) -> float:
    if player is None:
        return 0.0
    pts = getattr(player, "projected_points", None)
    if pts is None:
        return 0.0
    try:
        return float(pts)
    except (TypeError, ValueError):
        return 0.0

def calculate_category_balance_bonus(draft_state, player):
    raise NotImplementedError


def score_draft_candidate(
    draft_state: DraftState,
    player: Player,
    baselines: dict[str, PositionBaseline],
    position_window_map: dict[str, dict],
    dropoff_ranks: dict[str, int],
    bucket_leader_map: dict[str, str] | None = None,
    draft_context=None,
) -> PlayerDecisionScore:
    projected_points = float(player.projected_points or 0.0)
    value_score = _projected_value_component(draft_state, player)

    # Core identity
    primary_bucket = _primary_position_bucket(player)

    # Availability / survival
    availability_report = analyze_player_availability(draft_state, player.player_id)
    survival_probability = float(
        getattr(availability_report, "estimated_survival_score", 0.5) or 0.5
    )
    survival_probability = max(0.0, min(1.0, survival_probability))
    wait_penalty = _wait_penalty_from_survival(survival_probability)

    # Value / VORP / needs
    vorp = calculate_player_vorp(draft_state, player, baselines)
    vorp_bonus = _bounded_vorp_bonus(vorp)

    tier_cliff_score = float(detect_tier_cliff_score(draft_state, player) or 0.0)
    team_need_pressure = float(calculate_team_need_pressure(draft_state, player) or 0.0)
    roster_fit_score = float(calculate_roster_fit_score(draft_state, player) or 0.0)

    # Window map / fallback / dropoff
    wm = position_window_map.get(primary_bucket, {}) or {}

    position_dropoff = float(wm.get("dropoff", 0.0) or 0.0)
    position_dropoff_rank = int(dropoff_ranks.get(primary_bucket, wm.get("rank", 999)))

    fallback_id = wm.get("fallback_player_id")
    fallback_name_from_map = wm.get("fallback_player_name")

    expected_fallback_name = None
    if fallback_name_from_map:
        expected_fallback_name = str(fallback_name_from_map)
    elif fallback_id:
        fp = draft_state.player_pool.get_player(fallback_id)
        expected_fallback_name = fp.name if fp is not None else str(fallback_id)

    fallback_points = 0.0
    if fallback_id:
        fp2 = draft_state.player_pool.get_player(fallback_id)
        fallback_points = _safe_points(fp2)

    player_points = _safe_points(player)
    take_now_edge = max(0.0, player_points - fallback_points)
    if take_now_edge <= 0.0:
        take_now_edge = position_dropoff

    take_now_bonus = float(_bounded_take_now_bonus(take_now_edge) or 0.0)
    window_comparison_bonus = float(
        calculate_window_comparison_bonus(player, position_window_map, dropoff_ranks) or 0.0
    )

    # Bucket leader / fallback flags
    leader_id = (bucket_leader_map or {}).get(primary_bucket) or wm.get("current_best_player_id")
    is_bucket_leader = bool(leader_id) and (player.player_id == leader_id)

    fallback_player_id_for_bucket = wm.get("fallback_player_id")
    is_bucket_fallback_player = bool(fallback_player_id_for_bucket) and (
        player.player_id == fallback_player_id_for_bucket
    )

    # Deferrability
    deferrability_penalty = float(
        calculate_deferrability_penalty(
            draft_state,
            player,
            is_positional_leader=is_bucket_leader,
        ) or 0.0
    )

    # Suppression logic
    take_now_mult = 1.0
    window_mult = 1.0

    if is_bucket_fallback_player:
        take_now_mult *= 0.35
        window_mult *= 0.25
        if survival_probability >= 0.75:
            deferrability_penalty += 1.25

    suppress_non_leader = False
    if not is_bucket_leader and leader_id:
        leader_player = draft_state.player_pool.get_player(leader_id)
        leader_pts = float(getattr(leader_player, "projected_points", 0.0) or 0.0) if leader_player else 0.0
        leader_surv = estimate_survival_probability(draft_state, leader_player) if leader_player else 0.0
        leader_wait = _wait_penalty_from_survival(leader_surv)

        if leader_pts > projected_points and leader_wait <= (wait_penalty + 1.0):
            suppress_non_leader = True

        if suppress_non_leader and leader_player is not None:
            p_adp = float(getattr(player, "adp", 0.0) or 0.0)
            l_adp = float(getattr(leader_player, "adp", 0.0) or 0.0)
            if p_adp > 0.0 and l_adp > 0.0 and p_adp <= (l_adp - 10.0):
                suppress_non_leader = False

    if suppress_non_leader:
        take_now_mult *= 0.75
        window_mult *= 0.50

    take_now_bonus *= take_now_mult
    window_comparison_bonus *= window_mult

    # Reach / fall / SP build
    reach_penalty = float(calculate_reach_penalty(draft_state, player) or 0.0)
    fall_bonus = float(calculate_fall_bonus(draft_state, player) or 0.0)
    sp_build_penalty = float(_decision_engine_sp_build_penalty(draft_state, player) or 0.0)

    raw_roster_fit_score = float(roster_fit_score or 0.0)
    applied_sp_build_penalty = 0.0
    applied_early_sp_penalty = 0.0

    if primary_bucket == "SP":
        applied_sp_build_penalty = float(sp_build_penalty or 0.0)

        current_pick = int(draft_state.get_current_pick_number())
        user_roster = draft_state.get_user_roster()
        user_sp_count = sum(1 for rp in user_roster if "SP" in rp.positions)

        if current_pick <= 36 and user_sp_count >= 1:
            applied_early_sp_penalty -= 2.5
        if current_pick <= 60 and user_sp_count >= 2:
            applied_early_sp_penalty -= 3.0

    displayed_roster_fit_score = raw_roster_fit_score - applied_early_sp_penalty

    # Phase 2: category profile (supports old/new team_profile_engine API)
    if hasattr(_team_profile_engine, "calculate_category_balance_bonus"):
        category_balance_bonus = float(
            _team_profile_engine.calculate_category_balance_bonus(draft_state, player) or 0.0
        )
    elif hasattr(_team_profile_engine, "calculate_category_balance_bonus_with_components"):
        _cat_bonus, _ = _team_profile_engine.calculate_category_balance_bonus_with_components(
            draft_state, player
        )
        category_balance_bonus = float(_cat_bonus or 0.0)
    else:
        category_balance_bonus = 0.0

    # Phase 3: board pressure
    board_pressure = calculate_board_pressure_score(draft_state, player, survival_probability)
    board_pressure_score = float(board_pressure.board_pressure_score or 0.0)
    next_turn_loss_risk = float(board_pressure.next_turn_loss_risk or 0.0)
    expected_value_loss_if_wait = float(board_pressure.expected_value_loss_if_wait or 0.0)
    run_risk_score = float(board_pressure.run_risk_score or 0.0)
    market_heat_score = float(board_pressure.market_heat_score or 0.0)
    take_now_confidence = float(board_pressure.take_now_confidence or 0.0)
    wait_confidence = float(board_pressure.wait_confidence or 0.0)

    # Final draft score
    draft_score = (
        value_score
        + vorp_bonus
        + take_now_bonus
        + window_comparison_bonus
        - wait_penalty
        + (raw_roster_fit_score * 1.9)
        + (tier_cliff_score * 1.1)
        + (team_need_pressure * 0.9)
        + (fall_bonus * 0.6)
        - (reach_penalty * 0.8)
        - abs(sp_build_penalty)
        - deferrability_penalty
        + category_balance_bonus
        + board_pressure_score
    )

    reasons: list[str] = []
    if position_dropoff_rank == 1 and position_dropoff >= 8.0:
        reasons.append("strongest position dropoff")
    if take_now_bonus >= 3.0:
        reasons.append("take-now edge")
    if raw_roster_fit_score >= 1.5:
        reasons.append("roster fit")
    if vorp_bonus >= 6.0:
        reasons.append("strong VORP")
    if category_balance_bonus >= 1.0:
        reasons.append("category balance")

    if is_bucket_fallback_player and suppress_non_leader:
        if ("take-now edge" in reasons) and not (take_now_edge >= 8.0 or survival_probability <= 0.35):
            reasons = [r for r in reasons if r != "take-now edge"]

    reasons = reasons[:3]

    sp_penalty_active = (applied_sp_build_penalty < 0.0) or (applied_early_sp_penalty < 0.0)
    if sp_penalty_active:
        explanation = f"{', '.join(reasons[:2])}, but SP build penalty" if reasons else "SP build penalty"
    else:
        explanation = ", ".join(reasons) if reasons else "balanced draft equity"

    reported_sp_penalty = -abs(float(applied_sp_build_penalty or 0.0)) if applied_sp_build_penalty != 0.0 else 0.0
    reported_early_sp_penalty = -abs(float(applied_early_sp_penalty or 0.0)) if applied_early_sp_penalty != 0.0 else 0.0

    replacement_window_value = float(take_now_edge if take_now_edge > 0.0 else 0.0)

    component_scores = {
        "projected_points": round(projected_points, 3),
        "value_score": round(value_score, 3),

        "vorp": round(vorp, 3),
        "vorp_bonus": round(vorp_bonus, 3),

        "survival_probability": round(survival_probability, 3),
        "survival_score": round(survival_probability, 3),
        "waitability_penalty": round(-wait_penalty, 3),

        "team_need_pressure": round(team_need_pressure, 3),
        "urgency_bonus": round(team_need_pressure, 3),

        "roster_fit_score": round(displayed_roster_fit_score, 3),
        "raw_roster_fit_score": round(raw_roster_fit_score, 3),
        "roster_bonus": round(raw_roster_fit_score * 1.9, 3),

        "replacement_window_value": round(replacement_window_value, 3),
        "take_now_edge": round(take_now_edge, 3),
        "take_now_bonus": round(take_now_bonus, 3),
        "repl": round(replacement_window_value, 3),

        "position_dropoff": round(position_dropoff, 3),
        "position_dropoff_rank": float(position_dropoff_rank),
        "expected_fallback_player": expected_fallback_name,

        "sp_build_penalty": round(reported_sp_penalty, 3),
        "early_sp_penalty": round(reported_early_sp_penalty, 3),

        "category_balance_bonus": round(category_balance_bonus, 3),

        "board_pressure_score": round(board_pressure_score, 3),
        "next_turn_loss_risk": round(next_turn_loss_risk, 3),
        "expected_value_loss_if_wait": round(expected_value_loss_if_wait, 3),
        "run_risk_score": round(run_risk_score, 3),
        "market_heat_score": round(market_heat_score, 3),
        "take_now_confidence": round(take_now_confidence, 3),
        "wait_confidence": round(wait_confidence, 3),

        "window_comparison_bonus": round(window_comparison_bonus, 3),
        "reach_penalty": round(reach_penalty, 3),
        "fall_bonus": round(fall_bonus, 3),
        "deferrability_penalty": round(deferrability_penalty, 3),

        "is_bucket_leader": bool(is_bucket_leader),
        "is_bucket_fallback_player": bool(is_bucket_fallback_player),
    }

    return PlayerDecisionScore(
        player_id=player.player_id,
        draft_score=round(draft_score, 3),
        projected_points=round(projected_points, 3),
        vorp=round(vorp, 3),
        tier_cliff_score=round(tier_cliff_score, 3),
        survival_probability=round(survival_probability, 3),
        team_need_pressure=round(team_need_pressure, 3),
        roster_fit_score=round(roster_fit_score, 3),
        take_now_edge=round(take_now_edge, 3),
        expected_fallback_player=expected_fallback_name,
        position_dropoff=round(position_dropoff, 3),
        position_dropoff_rank=position_dropoff_rank,
        window_comparison_bonus=round(window_comparison_bonus, 3),
        reach_penalty=round(reach_penalty, 3),
        fall_bonus=round(fall_bonus, 3),
        category_balance_bonus=round(category_balance_bonus, 3),
        deferrability_penalty=round(deferrability_penalty, 3),
        board_pressure_score=round(board_pressure_score, 3),
        next_turn_loss_risk=round(next_turn_loss_risk, 3),
        expected_value_loss_if_wait=round(expected_value_loss_if_wait, 3),
        run_risk_score=round(run_risk_score, 3),
        market_heat_score=round(market_heat_score, 3),
        take_now_confidence=round(take_now_confidence, 3),
        wait_confidence=round(wait_confidence, 3),
        explanation=explanation,
        component_scores=component_scores,
    )

def calculate_reach_penalty(draft_state: DraftState, player) -> float:
    """
    Deterministic ADP reach penalty:
    penalize taking a player materially before ADP.
    """
    adp = float(getattr(player, "adp", 9999) or 9999)
    current_pick = float(draft_state.get_current_pick_number())
    reach = current_pick - adp  # negative => drafting early/reach
    if reach >= 0:
        return 0.0
    # cap to keep modifier light
    return min(6.0, max(0.0, (-reach) / 8.0))


def calculate_fall_bonus(draft_state: DraftState, player) -> float:
    """
    Deterministic ADP fall bonus:
    reward when a player falls past ADP.
    """
    adp = float(getattr(player, "adp", 9999) or 9999)
    current_pick = float(draft_state.get_current_pick_number())
    fall = current_pick - adp  # positive => falling
    if fall <= 0:
        return 0.0
    # cap to keep modifier light
    return min(6.0, fall / 10.0)


def _decision_engine_sp_build_penalty(draft_state: DraftState, player) -> float:
    """
    Early SP build control.
    """
    if _primary_position_bucket(player) != "SP":
        return 0.0

    current_pick = draft_state.get_current_pick_number()
    user_roster = draft_state.get_user_roster()
    user_sp_count = sum(1 for p in user_roster if "SP" in p.positions)

    penalty = 0.0
    if current_pick <= 36 and user_sp_count >= 1:
        penalty -= 6.0
    if current_pick <= 60 and user_sp_count >= 2:
        penalty -= 8.0
    return penalty


def _bounded_vorp_bonus(vorp: float) -> float:
    """
    Deterministic bounded VORP bonus used by score_draft_candidate.
    """
    v = float(vorp or 0.0)
    if v <= 0.0:
        return 0.0
    return min(18.0, v * 0.12)


def _bounded_take_now_bonus(take_now_edge: float) -> float:
    """
    Deterministic bounded take-now bonus used by score_draft_candidate.
    """
    t = float(take_now_edge or 0.0)
    if t <= 0.0:
        return 0.0
    return min(3.0, t)


def estimate_take_now_edge(
    draft_state: DraftState,
    player,
    baselines: dict[str, PositionBaseline],
) -> float:
    dropoff = float(calculate_position_dropoff(draft_state, player, baselines) or 0.0)
    edge = max(0.0, dropoff)

    # Keep Step 19/21 SP dampening
    if _primary_position_bucket(player) == "SP":
        edge *= 0.85

    return edge

def calculate_position_dropoff(
    draft_state: DraftState,
    player,
    baselines: dict[str, PositionBaseline],
) -> float:
    """
    Position dropoff signal for take-now edge:
    compares this player's projected points to the next-best available player
    in the same primary bucket. Falls back to replacement baseline.
    """
    bucket = _primary_position_bucket(player)
    players = _players_in_bucket(draft_state, bucket)
    if not players:
        return 0.0

    current_pts = float(player.projected_points or 0.0)
    idx = next((i for i, p in enumerate(players) if p.player_id == player.player_id), -1)

    # If player not found in sorted bucket list, use baseline gap.
    if idx < 0:
        baseline = baselines.get(bucket)
        repl_pts = float(baseline.replacement_points) if baseline is not None else 0.0
        return max(0.0, current_pts - repl_pts)

    # Next available at same position
    if idx + 1 < len(players):
        next_pts = float(players[idx + 1].projected_points or 0.0)
        return max(0.0, current_pts - next_pts)

    # Last player in bucket -> compare to replacement baseline
    baseline = baselines.get(bucket)
    repl_pts = float(baseline.replacement_points) if baseline is not None else 0.0
    return max(0.0, current_pts - repl_pts)

_WINDOW_DEBUG_BUCKETS = {"C", "2B", "3B"}

DEBUG_DECISION_ENGINE = False