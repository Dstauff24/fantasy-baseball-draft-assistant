from app.bootstrap_engine import resolve_projections_csv_path
from app.config import LeagueConfig, ScoringConfig
from app.draft_state import DraftState
from app.loader import load_projections_csv
from app.opponent_model import analyze_player_availability, simulate_picks_with_context
from app.player_pool import build_player_pool
from app.valuation import rank_players_by_points


def _build_state(current_pick: int = 4, user_slot: int = 4) -> DraftState:
    players_by_id, _ = load_projections_csv(str(resolve_projections_csv_path(None)))
    ranked_players_by_id, _ = rank_players_by_points(players_by_id, ScoringConfig())
    pool = build_player_pool(ranked_players_by_id)
    state = DraftState.create(LeagueConfig(), pool)
    state.current_pick = current_pick
    state.user_slot = user_slot
    return state


def test_simulate_picks_with_context_exposes_team_profiles_and_availability_lists():
    state = _build_state(current_pick=4)
    summary = simulate_picks_with_context(state)

    assert summary.simulated_picks, "expected simulated picks before next user turn"
    assert summary.team_need_profiles, "expected team need profiles"
    assert summary.likely_gone_next, "expected likely_gone_next list"
    assert isinstance(summary.likely_available_next, list)
    assert isinstance(summary.threatened_positions, list)
    assert isinstance(summary.preserved_positions, list)
    assert isinstance(summary.threatened_positions_ranked, list)
    assert isinstance(summary.preserved_positions_ranked, list)
    assert isinstance(summary.threat_score_by_position, dict)

    first_profile = summary.team_need_profiles[0]
    assert first_profile.target_positions, "expected ranked team target positions"
    assert first_profile.position_urgency, "expected urgency map"


def test_team_profiles_are_not_overly_homogeneous_after_seed_picks():
    state = _build_state(current_pick=28, user_slot=4)

    # Seed a realistic mixed opening so team profiles should diverge.
    available = state.get_available_players_by_value(36)
    for idx, player in enumerate(available[:18], start=1):
        team_id = ((idx - 1) % state.league_config.team_count) + 1
        state.team_rosters.setdefault(team_id, []).append(player.player_id)
        if player.player_id in state.available_player_ids:
            state.available_player_ids.remove(player.player_id)

    summary = simulate_picks_with_context(state)
    target_signatures = {tuple(profile.target_positions[:3]) for profile in summary.team_need_profiles}

    # At least a couple distinct target orderings should emerge.
    assert len(target_signatures) >= 2


def test_threatened_and_preserved_rankings_are_discriminating():
    state = _build_state(current_pick=4)
    summary = simulate_picks_with_context(state)

    threatened = list(summary.threatened_positions_ranked)
    preserved = list(summary.preserved_positions_ranked)

    assert threatened, "expected non-empty threatened ranking"
    assert preserved, "expected non-empty preserved ranking"
    overlap = set(threatened[:3]).intersection(set(preserved[:3]))
    assert not overlap, f"top threat/preserved overlap too broad: {overlap}"


def test_availability_report_uses_opponent_aware_threats():
    state = _build_state(current_pick=4)
    top_player_id = state.available_player_ids[0]

    report = analyze_player_availability(state, top_player_id)
    assert report.target_player_id == top_player_id
    assert 0.0 <= report.estimated_survival_score <= 1.0
    assert isinstance(report.threatened_by, list)


def test_simulation_excludes_current_user_pick_when_user_on_clock():
    state = _build_state(current_pick=4, user_slot=4)
    summary = simulate_picks_with_context(state)

    assert summary.simulated_picks, "expected simulated picks"
    assert summary.simulated_picks[0].pick_number == 5
    assert summary.simulated_picks[0].team_id != 4
    if summary.team_need_profiles:
        assert summary.team_need_profiles[0].team_id != 4
