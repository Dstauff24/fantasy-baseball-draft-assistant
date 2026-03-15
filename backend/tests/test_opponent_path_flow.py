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

    first_profile = summary.team_need_profiles[0]
    assert first_profile.target_positions, "expected ranked team target positions"
    assert first_profile.position_urgency, "expected urgency map"


def test_availability_report_uses_opponent_aware_threats():
    state = _build_state(current_pick=4)
    top_player_id = state.available_player_ids[0]

    report = analyze_player_availability(state, top_player_id)
    assert report.target_player_id == top_player_id
    assert 0.0 <= report.estimated_survival_score <= 1.0
    assert isinstance(report.threatened_by, list)
