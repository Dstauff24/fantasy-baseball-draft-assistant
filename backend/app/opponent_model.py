from dataclasses import dataclass, field

from app.draft_state import DraftState, get_team_for_pick
from app.models import Player


@dataclass
class SimulatedPick:
    pick_number: int
    team_id: int
    player_id: str
    player_name: str
    adp: float | None
    derived_rank: int | None
    reason: str
    target_position: str = ""
    need_score: float = 0.0
    scarcity_influence: float = 0.0


@dataclass
class TeamNeedProfile:
    team_id: int
    target_positions: list[str] = field(default_factory=list)
    position_urgency: dict[str, float] = field(default_factory=dict)
    explanation: str = ""


@dataclass
class OpponentSimulationSummary:
    simulated_picks: list[SimulatedPick] = field(default_factory=list)
    team_need_profiles: list[TeamNeedProfile] = field(default_factory=list)
    likely_gone_next: list[str] = field(default_factory=list)
    likely_available_next: list[str] = field(default_factory=list)
    threatened_positions: list[str] = field(default_factory=list)
    preserved_positions: list[str] = field(default_factory=list)
    threatened_positions_ranked: list[str] = field(default_factory=list)
    preserved_positions_ranked: list[str] = field(default_factory=list)
    threat_score_by_position: dict[str, float] = field(default_factory=dict)


@dataclass
class AvailabilityReport:
    target_player_id: str
    target_player_name: str
    current_pick: int
    next_user_pick: int
    picks_until_next_turn: int
    estimated_survival_score: float
    likely_taken_before_next: bool
    threatened_by: list[SimulatedPick]


def _primary_bucket(player: Player) -> str:
    pos_set = set(player.positions or [])
    if "SP" in pos_set or "P" in pos_set:
        return "SP"
    if "RP" in pos_set:
        return "RP"
    for b in ("C", "2B", "3B", "SS", "1B", "OF"):
        if b in pos_set:
            return b
    return "UTIL"


def _is_pitcher(player: Player) -> bool:
    return _primary_bucket(player) in {"SP", "RP", "P"}


def _adp_pressure_score(player: Player, current_pick: int) -> float:
    if player.adp is None:
        return -6.0

    adp = player.adp
    if adp <= current_pick:
        return 32.0 + min(10.0, (current_pick - adp) * 0.5)  # strong pressure
    if adp <= current_pick + 6:
        return 25.0 - ((adp - current_pick) * 1.3)  # high pressure
    if adp <= current_pick + 12:
        return 17.0 - ((adp - (current_pick + 6)) * 1.1)  # medium pressure
    if adp <= current_pick + 24:
        return 9.0 - ((adp - (current_pick + 12)) * 0.45)  # lower pressure
    return max(-4.0, 3.0 - ((adp - (current_pick + 24)) * 0.12))  # much later


def _reach_tolerance(team_id: int, current_pick: int) -> float:
    # deterministic 4..10 pick reach tolerance
    return float(4 + ((team_id * 3 + current_pick) % 7))


def _team_position_counts(draft_state, team_id: int) -> dict[str, int]:
    counts = {"C": 0, "1B": 0, "2B": 0, "3B": 0, "SS": 0, "OF": 0, "SP": 0, "RP": 0, "UTIL": 0}
    roster_ids = draft_state.team_rosters.get(team_id, [])
    for player_id in roster_ids:
        player = draft_state.player_pool.get_player(player_id)
        if player is None:
            continue
        bucket = _primary_bucket(player)
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def _available_bucket_snapshot(draft_state) -> dict[str, list[Player]]:
    buckets = {"C": [], "1B": [], "2B": [], "3B": [], "SS": [], "OF": [], "SP": [], "RP": [], "UTIL": []}
    for p in draft_state.get_available_players_by_value():
        buckets[_primary_bucket(p)].append(p)
    for vals in buckets.values():
        vals.sort(key=lambda p: (-(float(p.projected_points or 0.0)), p.player_id))
    return buckets


def _bucket_scarcity_pressure_from_snapshot(bucket_snapshot: dict[str, list[Player]], bucket: str) -> float:
    players = bucket_snapshot.get(bucket, [])
    if not players:
        return 4.0

    top = float(players[0].projected_points or 0.0)
    baseline_idx = 9 if bucket in {"SP", "OF"} else 5
    baseline_idx = min(baseline_idx, len(players) - 1)
    baseline = float(players[baseline_idx].projected_points or 0.0)
    drop = max(0.0, top - baseline)

    scarcity = min(4.5, (drop / 18.0) + (4.0 / max(1, len(players))))
    if bucket == "SP":
        scarcity += 0.75
    return round(scarcity, 3)


def build_team_need_profile(draft_state: DraftState, team_id: int) -> TeamNeedProfile:
    counts = _team_position_counts(draft_state, team_id)
    bucket_snapshot = _available_bucket_snapshot(draft_state)
    scarcity_map = {b: _bucket_scarcity_pressure_from_snapshot(bucket_snapshot, b) for b in bucket_snapshot.keys()}
    roster_ids = list(draft_state.team_rosters.get(team_id, []))
    roster_size = len(roster_ids)

    needs: dict[str, float] = {}

    def _need(bucket: str, target: int, weight: float) -> None:
        deficit = max(0, target - counts.get(bucket, 0))
        scarcity = float(scarcity_map.get(bucket, 0.0))
        saturation = max(0.0, (counts.get(bucket, 0) - target) * 1.75)
        needs[bucket] = round((deficit * weight) + scarcity - saturation, 3)

    _need("SP", 3, 2.2)
    _need("RP", 1, 1.4)
    _need("C", 1, 2.0)
    _need("1B", 1, 1.6)
    _need("2B", 1, 1.8)
    _need("3B", 1, 1.8)
    _need("SS", 1, 2.0)
    _need("OF", 3, 1.4)

    # normalize over-filled positions and de-emphasize C after first catcher.
    if counts.get("C", 0) >= 1:
        needs["C"] = round(max(0.0, needs.get("C", 0.0) - 3.5), 3)
    if counts.get("OF", 0) >= 2 and roster_size <= 6:
        needs["OF"] = round(max(0.0, needs.get("OF", 0.0) - 1.25), 3)

    # soft tendency: if team already pitcher-heavy, temper SP urgency; hitter-heavy does opposite
    total_pitchers = counts.get("SP", 0) + counts.get("RP", 0)
    total_hitters = counts.get("C", 0) + counts.get("1B", 0) + counts.get("2B", 0) + counts.get("3B", 0) + counts.get("SS", 0) + counts.get("OF", 0)
    if total_pitchers - total_hitters >= 2:
        needs["SP"] = round(max(0.0, needs.get("SP", 0.0) - 1.25), 3)
    elif total_hitters - total_pitchers >= 2:
        needs["SP"] = round(needs.get("SP", 0.0) + 0.9, 3)

    # Team-style priors by slot create controlled differentiation without randomness.
    style = team_id % 4
    if style == 0:  # ace-first style
        needs["SP"] = round(needs.get("SP", 0.0) + 1.1, 3)
        needs["RP"] = round(needs.get("RP", 0.0) + 0.3, 3)
    elif style == 1:  # bat-heavy style
        needs["OF"] = round(needs.get("OF", 0.0) + 0.9, 3)
        needs["1B"] = round(needs.get("1B", 0.0) + 0.5, 3)
        needs["SP"] = round(max(0.0, needs.get("SP", 0.0) - 0.5), 3)
    elif style == 2:  # middle-infield style
        needs["SS"] = round(needs.get("SS", 0.0) + 0.9, 3)
        needs["2B"] = round(needs.get("2B", 0.0) + 0.7, 3)
    else:  # corner-bat style
        needs["3B"] = round(needs.get("3B", 0.0) + 0.6, 3)
        needs["1B"] = round(needs.get("1B", 0.0) + 0.6, 3)

    # Prior-pick shape adjustment to avoid one-dimensional consecutive builds.
    recent_buckets: list[str] = []
    for pid in reversed(roster_ids[-3:]):
        player = draft_state.player_pool.get_player(pid)
        if player is not None:
            recent_buckets.append(_primary_bucket(player))

    if len(recent_buckets) >= 2 and recent_buckets[0] == recent_buckets[1]:
        repeat_bucket = recent_buckets[0]
        needs[repeat_bucket] = round(max(0.0, needs.get(repeat_bucket, 0.0) - 1.2), 3)

    # Early rounds: preserve diversity by preventing universal SP/OF/C ordering.
    if roster_size <= 2:
        for bucket in ("C", "RP"):
            needs[bucket] = round(max(0.0, needs.get(bucket, 0.0) - 0.9), 3)
    elif roster_size >= 7:
        needs["RP"] = round(needs.get("RP", 0.0) + 0.7, 3)

    ordered = sorted(needs.items(), key=lambda kv: (-kv[1], kv[0]))
    top_positions = [bucket for bucket, _ in ordered[:4]]
    explanation = f"style={style}; recent={recent_buckets[:2]}; needs={ordered[:3]}"
    return TeamNeedProfile(team_id=team_id, target_positions=top_positions, position_urgency=needs, explanation=explanation)


def _need_fit_bonus(draft_state, team_profile: TeamNeedProfile, player) -> float:
    bucket = _primary_bucket(player)
    return float(team_profile.position_urgency.get(bucket, 0.0))


def _market_band_candidates(
    draft_state: DraftState, current_pick: int, max_candidates: int = 35
) -> list[Player]:
    available = draft_state.get_available_players_by_value()
    if not available:
        return []

    band: list[Player] = []
    for p in available:
        if p.adp is None:
            continue
        if current_pick - 8 <= p.adp <= current_pick + 18:
            band.append(p)

    pressure_sorted = sorted(
        available,
        key=lambda p: (
            -_adp_pressure_score(p, current_pick),
            float("inf") if p.adp is None else p.adp,
            float("inf") if p.derived_rank is None else p.derived_rank,
            p.name,
        ),
    )[:14]

    value_sorted = available[:12]

    merged: list[Player] = []
    seen: set[str] = set()

    for grp in (band, pressure_sorted, value_sorted):
        for p in grp:
            if p.player_id not in seen:
                seen.add(p.player_id)
                merged.append(p)
                if len(merged) >= max_candidates:
                    return merged

    # Ensure key buckets are represented at least once.
    for bucket in ("C", "2B", "3B", "SS", "OF", "SP", "RP"):
        best_bucket = next((p for p in available if _primary_bucket(p) == bucket), None)
        if best_bucket and best_bucket.player_id not in seen:
            seen.add(best_bucket.player_id)
            merged.append(best_bucket)
            if len(merged) >= max_candidates:
                return merged

    return merged[:max_candidates] if merged else available[:max_candidates]


def _player_market_score(
    draft_state: DraftState,
    player: Player,
    current_pick: int,
    team_profile: TeamNeedProfile,
    scarcity_map: dict[str, float],
) -> tuple[float, str]:
    adp_pressure = _adp_pressure_score(player, current_pick)

    if player.derived_rank is None:
        rank_support = 0.0
    else:
        rank_support = max(0.0, 8.0 - (player.derived_rank * 0.03))

    need_bonus = _need_fit_bonus(draft_state, team_profile, player)
    bucket = _primary_bucket(player)

    scarcity_support = float(scarcity_map.get(bucket, 0.0)) * 0.6

    reach_penalty = 0.0
    if player.adp is not None:
        reach_amt = player.adp - current_pick
        tol = _reach_tolerance(team_profile.team_id, current_pick)
        if reach_amt > tol:
            reach_penalty = (reach_amt - tol) * 0.9

    team_tiebreak = team_profile.team_id * 0.0001
    score = adp_pressure + rank_support + need_bonus + scarcity_support - reach_penalty + team_tiebreak

    if need_bonus >= 6.0 and reach_penalty > 0:
        reason = f"need_priority_reach[{bucket}]"
    elif need_bonus >= 6.0:
        reason = f"need_priority[{bucket}]"
    elif scarcity_support >= 2.2:
        reason = f"scarcity_pressure[{bucket}]"
    else:
        reason = f"market_value[{bucket}]"

    detail = f"{reason}; need={need_bonus:.2f}; scarcity={scarcity_support:.2f}; adp={adp_pressure:.2f}"
    return score, detail


def _position_threat_summary(
    draft_state: DraftState,
    simulated_picks: list[SimulatedPick],
    remaining_players: list[Player],
) -> tuple[list[str], list[str], list[str], list[str], dict[str, float]]:
    threat_scores: dict[str, float] = {}
    for idx, pick in enumerate(simulated_picks):
        player = draft_state.player_pool.get_player(pick.player_id)
        if player is None:
            continue
        bucket = _primary_bucket(player)
        urgency = max(0.0, float(getattr(pick, "need_score", 0.0) or 0.0) / 4.0)
        early_weight = max(0.55, 1.3 - (idx * 0.08))
        threat_scores[bucket] = threat_scores.get(bucket, 0.0) + (1.0 + urgency) * early_weight

    remaining_top: dict[str, list[Player]] = {}
    for p in remaining_players[:45]:
        bucket = _primary_bucket(p)
        remaining_top.setdefault(bucket, []).append(p)

    resilience_scores: dict[str, float] = {}
    for bucket, vals in remaining_top.items():
        vals.sort(key=lambda pl: float(pl.projected_points or 0.0), reverse=True)
        top_score = float(vals[0].projected_points or 0.0)
        floor_idx = min(4, len(vals) - 1)
        floor_score = float(vals[floor_idx].projected_points or 0.0)
        depth = len(vals)
        resilience_scores[bucket] = max(0.0, (depth * 0.16) + ((top_score - floor_score) * 0.04))

    all_buckets = sorted(set(list(threat_scores.keys()) + list(resilience_scores.keys())))
    combined = {
        bucket: round(threat_scores.get(bucket, 0.0) - (resilience_scores.get(bucket, 0.0) * 0.45), 3)
        for bucket in all_buckets
    }

    threatened_ranked = [
        b for b, score in sorted(combined.items(), key=lambda kv: (-kv[1], kv[0])) if score >= 0.8
    ]
    preserved_ranked = [
        b for b, score in sorted(combined.items(), key=lambda kv: (kv[1], kv[0])) if score <= 0.2
    ]

    preserved_ranked = [b for b in preserved_ranked if b not in set(threatened_ranked)]
    threatened = threatened_ranked[:4]
    preserved = preserved_ranked[:4]
    return threatened, preserved, threatened_ranked, preserved_ranked, combined


def simulate_picks_with_context(
    draft_state: DraftState,
    max_candidates_per_pick: int = 35,
    availability_window: int = 24,
) -> OpponentSimulationSummary:
    current_pick = draft_state.get_current_pick_number()
    next_user_pick = draft_state.get_next_user_pick()

    if next_user_pick is None or next_user_pick <= current_pick:
        return OpponentSimulationSummary()

    simulated_picks: list[SimulatedPick] = []
    sim_available_ids = list(draft_state.available_player_ids)
    sim_available_set = set(sim_available_ids)

    class _SimDraftView:
        def __init__(self, src: DraftState) -> None:
            self.player_pool = src.player_pool
            self.team_rosters = {team_id: list(ids) for team_id, ids in src.team_rosters.items()}

        def get_available_players_by_value(self) -> list[Player]:
            players: list[Player] = []
            for pid in sim_available_ids:
                if pid not in sim_available_set:
                    continue
                p = self.player_pool.get_player(pid)
                if p is not None:
                    players.append(p)
            return players

    sim_view = _SimDraftView(draft_state)
    team_need_by_id: dict[int, TeamNeedProfile] = {}

    for pick_number in range(current_pick, next_user_pick):
        team_id = get_team_for_pick(pick_number, draft_state.league_config.team_count)
        team_profile = build_team_need_profile(sim_view, team_id)
        team_need_by_id[team_id] = team_profile

        candidates = _market_band_candidates(sim_view, pick_number, max_candidates=max_candidates_per_pick)
        if not candidates:
            break

        bucket_snapshot = _available_bucket_snapshot(sim_view)
        scarcity_map = {b: _bucket_scarcity_pressure_from_snapshot(bucket_snapshot, b) for b in bucket_snapshot.keys()}

        scored: list[tuple[float, Player, str]] = []
        for player in candidates:
            score, reason = _player_market_score(sim_view, player, pick_number, team_profile, scarcity_map)
            scored.append((score, player, reason))

        scored.sort(
            key=lambda item: (
                -item[0],
                float("inf") if item[1].adp is None else item[1].adp,
                float("inf") if item[1].derived_rank is None else item[1].derived_rank,
                item[1].name,
                item[1].player_id,
            )
        )
        best_score, selected, reason = scored[0]

        if selected.player_id in sim_available_set:
            sim_available_set.remove(selected.player_id)
        if selected.player_id in sim_available_ids:
            sim_available_ids.remove(selected.player_id)
        sim_view.team_rosters.setdefault(team_id, []).append(selected.player_id)

        pick_bucket = _primary_bucket(selected)
        need_for_pick = float(team_profile.position_urgency.get(pick_bucket, 0.0) or 0.0)
        scarcity_for_pick = float(scarcity_map.get(pick_bucket, 0.0) or 0.0)
        simulated_picks.append(
            SimulatedPick(
                pick_number=pick_number,
                team_id=team_id,
                player_id=selected.player_id,
                player_name=selected.name,
                adp=selected.adp,
                derived_rank=selected.derived_rank,
                reason=f"{reason}; targets={team_profile.target_positions[:3]}; score={best_score:.3f}",
                target_position=pick_bucket,
                need_score=round(need_for_pick, 3),
                scarcity_influence=round(scarcity_for_pick, 3),
            )
        )

    remaining = sim_view.get_available_players_by_value()
    likely_available_next = [p.player_id for p in remaining[: min(availability_window, len(remaining))]]
    likely_gone_next = [sp.player_id for sp in simulated_picks]

    (
        threatened_positions,
        preserved_positions,
        threatened_positions_ranked,
        preserved_positions_ranked,
        threat_score_by_position,
    ) = _position_threat_summary(draft_state, simulated_picks, remaining)

    team_need_profiles = sorted(team_need_by_id.values(), key=lambda t: t.team_id)

    return OpponentSimulationSummary(
        simulated_picks=simulated_picks,
        team_need_profiles=team_need_profiles,
        likely_gone_next=likely_gone_next,
        likely_available_next=likely_available_next,
        threatened_positions=threatened_positions,
        preserved_positions=preserved_positions,
        threatened_positions_ranked=threatened_positions_ranked,
        preserved_positions_ranked=preserved_positions_ranked,
        threat_score_by_position=threat_score_by_position,
    )


def simulate_picks_until_next_turn(
    draft_state: DraftState, max_candidates_per_pick: int = 35
) -> list[SimulatedPick]:
    summary = simulate_picks_with_context(
        draft_state,
        max_candidates_per_pick=max_candidates_per_pick,
    )
    return summary.simulated_picks


def analyze_player_availability(draft_state: DraftState, target_player_id: str) -> AvailabilityReport:
    target_player = draft_state.player_pool.get_player(target_player_id)
    if target_player is None:
        raise ValueError(f"Unknown player_id: {target_player_id}")

    current_pick = draft_state.get_current_pick_number()
    next_user_pick = draft_state.get_next_user_pick()
    if next_user_pick is None:
        next_user_pick = current_pick
    picks_until_next_turn = max(0, next_user_pick - current_pick)

    summary = simulate_picks_with_context(draft_state)
    simulated = summary.simulated_picks

    taken_index = -1
    for idx, sim_pick in enumerate(simulated):
        if sim_pick.player_id == target_player_id:
            taken_index = idx
            break

    likely_taken = taken_index >= 0

    if likely_taken:
        survival_score = 0.05
        threatened_by = simulated[: taken_index + 1]
    else:
        adp = target_player.adp
        if adp is None:
            survival_score = 0.80
        elif adp <= current_pick + 3:
            survival_score = 0.10
        elif adp <= current_pick + 8:
            survival_score = 0.20
        elif adp <= next_user_pick - 4:
            survival_score = 0.35
        elif adp <= next_user_pick + 2:
            survival_score = 0.55
        elif adp <= next_user_pick + 10:
            survival_score = 0.75
        else:
            survival_score = 0.90

        pressure = _adp_pressure_score(target_player, current_pick)
        if pressure >= 24.0:
            survival_score -= 0.10

        bucket_threat = 0.0
        target_bucket = _primary_bucket(target_player)
        if target_bucket in summary.threatened_positions:
            bucket_threat += 0.08
        if target_bucket == "SP" and target_bucket in summary.threatened_positions:
            bucket_threat += 0.05
        survival_score -= bucket_threat

        survival_score = max(0.05, min(0.95, survival_score))

        threatened_by = []
        for sim_pick in simulated:
            sim_player = draft_state.player_pool.get_player(sim_pick.player_id)
            if sim_player is None:
                continue
            if _primary_bucket(sim_player) == target_bucket:
                threatened_by.append(sim_pick)

    return AvailabilityReport(
        target_player_id=target_player_id,
        target_player_name=target_player.name,
        current_pick=current_pick,
        next_user_pick=next_user_pick,
        picks_until_next_turn=picks_until_next_turn,
        estimated_survival_score=survival_score,
        likely_taken_before_next=likely_taken,
        threatened_by=threatened_by,
    )
