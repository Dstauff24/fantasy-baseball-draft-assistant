from dataclasses import dataclass

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


def _team_needs_pitching(draft_state: DraftState, team_id: int) -> bool:
    roster_ids = draft_state.team_rosters.get(team_id, [])
    pitcher_count = 0
    for player_id in roster_ids:
        player = draft_state.player_pool.get_player(player_id)
        if player is not None and _is_pitcher(player):
            pitcher_count += 1
    return pitcher_count < 2


def _team_needs_hitting(draft_state: DraftState, team_id: int) -> bool:
    roster_ids = draft_state.team_rosters.get(team_id, [])
    hitter_count = 0
    for player_id in roster_ids:
        player = draft_state.player_pool.get_player(player_id)
        if player is not None and not _is_pitcher(player):
            hitter_count += 1
    return hitter_count < 3


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


def _need_fit_bonus(draft_state, team_id: int, player) -> float:
    counts = _team_position_counts(draft_state, team_id)
    bucket = _primary_bucket(player)

    if bucket == "SP":
        if counts["SP"] < 2:
            return 5.0
        if counts["SP"] < 3:
            return 2.0
        return 0.0

    if bucket == "RP":
        return 2.0 if counts["RP"] < 1 else 0.0

    if bucket == "C":
        return 5.0 if counts["C"] < 1 else 0.0
    if bucket == "SS":
        return 4.5 if counts["SS"] < 1 else 0.0
    if bucket == "2B":
        return 4.0 if counts["2B"] < 1 else 0.0
    if bucket == "3B":
        return 4.0 if counts["3B"] < 1 else 0.0
    if bucket == "1B":
        return 3.0 if counts["1B"] < 1 else 0.0
    if bucket == "OF":
        if counts["OF"] < 2:
            return 2.5
        if counts["OF"] < 3:
            return 1.0
        return 0.0

    return 0.0


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


def _player_market_score(draft_state: DraftState, player: Player, current_pick: int, team_id: int) -> float:
    adp_pressure = _adp_pressure_score(player, current_pick)

    if player.derived_rank is None:
        rank_support = 0.0
    else:
        rank_support = max(0.0, 8.0 - (player.derived_rank * 0.03))  # modest

    need_bonus = _need_fit_bonus(draft_state, team_id, player)

    scarcity = 0.0
    if not _is_pitcher(player) and any(pos in {"C", "2B", "3B", "SS"} for pos in player.positions):
        scarcity = 1.0

    reach_penalty = 0.0
    if player.adp is not None:
        reach_amt = player.adp - current_pick
        tol = _reach_tolerance(team_id, current_pick)
        if reach_amt > tol:
            reach_penalty = (reach_amt - tol) * 0.9  # moderate out-of-band penalty

    team_tiebreak = team_id * 0.0001
    return adp_pressure + rank_support + need_bonus + scarcity - reach_penalty + team_tiebreak


def simulate_picks_until_next_turn(
    draft_state: DraftState, max_candidates_per_pick: int = 35
) -> list[SimulatedPick]:
    current_pick = draft_state.get_current_pick_number()
    next_user_pick = draft_state.get_next_user_pick()

    if next_user_pick <= current_pick:
        return []

    simulated_picks: list[SimulatedPick] = []
    sim_available_ids = list(draft_state.available_player_ids)
    sim_available_set = set(sim_available_ids)

    # lightweight sim view for roster-need updates
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

    for pick_number in range(current_pick, next_user_pick):
        team_id = get_team_for_pick(pick_number, draft_state.league_config.team_count)

        candidates = _market_band_candidates(sim_view, pick_number, max_candidates=max_candidates_per_pick)
        if not candidates:
            break

        scored: list[tuple[float, Player, str]] = []
        for player in candidates:
            score = _player_market_score(sim_view, player, pick_number, team_id)

            need_bonus = _need_fit_bonus(sim_view, team_id, player)
            reach_penalty = 0.0
            if player.adp is not None:
                reach_amt = player.adp - pick_number
                tol = _reach_tolerance(team_id, pick_number)
                if reach_amt > tol:
                    reach_penalty = (reach_amt - tol) * 0.9

            if need_bonus >= 4.0 and reach_penalty > 0:
                reason = "reach_for_need"
            elif need_bonus >= 4.0:
                reason = "adp_pressure+need"
            else:
                reason = "market_value"

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

        sim_available_set.remove(selected.player_id)
        sim_available_ids.remove(selected.player_id)
        sim_view.team_rosters.setdefault(team_id, []).append(selected.player_id)

        simulated_picks.append(
            SimulatedPick(
                pick_number=pick_number,
                team_id=team_id,
                player_id=selected.player_id,
                player_name=selected.name,
                adp=selected.adp,
                derived_rank=selected.derived_rank,
                reason=f"{reason}; score={best_score:.3f}",
            )
        )

    return simulated_picks


def analyze_player_availability(draft_state: DraftState, target_player_id: str) -> AvailabilityReport:
    target_player = draft_state.player_pool.get_player(target_player_id)
    if target_player is None:
        raise ValueError(f"Unknown player_id: {target_player_id}")

    current_pick = draft_state.get_current_pick_number()
    next_user_pick = draft_state.get_next_user_pick()
    picks_until_next_turn = max(0, next_user_pick - current_pick)

    simulated = simulate_picks_until_next_turn(draft_state)

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

        survival_score = max(0.05, min(0.95, survival_score))

        target_bucket = _primary_bucket(target_player)
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