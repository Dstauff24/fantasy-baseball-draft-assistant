from app.bootstrap_engine import resolve_projections_csv_path
from app.config import LeagueConfig, ScoringConfig
from app.draft_decision_engine import build_decision_board
from app.draft_state import DraftState
from app.loader import load_projections_csv
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


def _find_decision_by_player_name(state: DraftState, name_substring: str):
    scores, _ = build_decision_board(state, top_n=60)
    for score in scores:
        player = state.player_pool.get_player(score.player_id)
        if player and name_substring.lower() in player.name.lower():
            return score, player
    return None, None


def test_elite_sp_get_sp_cliff_debug_signals_in_early_rounds():
    state = _build_state(current_pick=4)
    skubal_score, skubal = _find_decision_by_player_name(state, "Tarik Skubal")
    assert skubal is not None, "expected Tarik Skubal in loaded projections"
    assert skubal_score is not None

    comp = skubal_score.component_scores
    assert comp.get("cliff_label") in {"strong", "elite"}
    assert float(comp.get("sp_cliff_multiplier", 1.0) or 1.0) > 1.0
    assert float(comp.get("early_round_cliff_multiplier", 1.0) or 1.0) > 1.0


def test_skenes_outranks_schwarber_in_round1_pick4_context():
    state = _build_state(current_pick=4)
    skenes_score, skenes = _find_decision_by_player_name(state, "Paul Skenes")
    schwarber_score, schwarber = _find_decision_by_player_name(state, "Kyle Schwarber")

    assert skenes is not None, "expected Paul Skenes in loaded projections"
    assert schwarber is not None, "expected Kyle Schwarber in loaded projections"
    assert skenes_score is not None and schwarber_score is not None
    assert skenes_score.draft_score > schwarber_score.draft_score
