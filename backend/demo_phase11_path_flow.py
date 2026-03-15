from __future__ import annotations

from app.bootstrap_engine import resolve_projections_csv_path
from app.config import LeagueConfig, ScoringConfig
from app.draft_state import DraftState
from app.loader import load_projections_csv
from app.opponent_model import simulate_picks_with_context
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


def main() -> None:
    state = _build_state(current_pick=4, user_slot=4)
    summary = simulate_picks_with_context(state)

    print("=== Phase 11 Opponent-Aware Path Flow Demo ===")
    print(f"Current pick: {state.get_current_pick_number()} | Next user pick: {state.get_next_user_pick()}")

    print("\nProjected team targets before next user turn:")
    for profile in summary.team_need_profiles:
        top = ", ".join(profile.target_positions[:3])
        print(f"- Team {profile.team_id}: {top} | {profile.explanation}")

    print("\nLikely gone before next pick:")
    for sp in summary.simulated_picks[:10]:
        print(f"- Pick {sp.pick_number} Team {sp.team_id}: {sp.player_name} ({sp.reason})")

    print("\nLikely available next (top ids):")
    print(summary.likely_available_next[:10])
    print("Threatened positions:", summary.threatened_positions)
    print("Preserved positions:", summary.preserved_positions)


if __name__ == "__main__":
    main()
