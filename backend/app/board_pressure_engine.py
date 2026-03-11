from dataclasses import dataclass

from app.draft_state import DraftState


@dataclass
class BoardPressureScore:
    board_pressure_score: float = 0.0
    next_turn_loss_risk: float = 0.0
    expected_value_loss_if_wait: float = 0.0
    run_risk_score: float = 0.0
    market_heat_score: float = 0.0
    take_now_confidence: float = 0.0
    wait_confidence: float = 0.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def calculate_board_pressure_score(
    draft_state: DraftState,
    player,
    survival_probability: float,
) -> BoardPressureScore:
    current_pick = int(draft_state.get_current_pick_number())
    next_user_pick = int(draft_state.get_next_user_pick())
    picks_until_next = max(0, next_user_pick - current_pick)

    adp = _safe_float(getattr(player, "adp", None), 0.0)
    projected_points = _safe_float(getattr(player, "projected_points", None), 0.0)
    survival = _clamp(_safe_float(survival_probability, 0.5), 0.0, 1.0)

    # Higher when player is unlikely to survive.
    next_turn_loss_risk = _clamp((1.0 - survival) * 10.0, 0.0, 10.0)

    # ADP pressure: positive when market expects earlier than your next pick.
    adp_pressure = 0.0
    if adp > 0.0:
        adp_gap_to_next = next_user_pick - adp
        if adp_gap_to_next >= 0:
            adp_pressure = _clamp(2.0 + (adp_gap_to_next / 6.0), 0.0, 5.0)

    # Short window before your next turn increases risk.
    window_pressure = _clamp((max(0, 18 - picks_until_next) / 18.0) * 4.0, 0.0, 4.0)

    run_risk_score = _clamp((next_turn_loss_risk * 0.65) + (window_pressure * 0.85), 0.0, 10.0)
    market_heat_score = _clamp((adp_pressure * 1.15) + (window_pressure * 0.55), 0.0, 10.0)

    board_pressure_score = _clamp(
        (next_turn_loss_risk * 0.5) + (run_risk_score * 0.3) + (market_heat_score * 0.2),
        0.0,
        10.0,
    )

    expected_value_loss_if_wait = max(0.0, projected_points * (next_turn_loss_risk / 10.0) * 0.06)

    take_now_confidence = _clamp(
        0.5 + (board_pressure_score / 20.0) + (next_turn_loss_risk / 25.0),
        0.0,
        1.0,
    )
    wait_confidence = _clamp(1.0 - take_now_confidence, 0.0, 1.0)

    return BoardPressureScore(
        board_pressure_score=round(board_pressure_score, 3),
        next_turn_loss_risk=round(next_turn_loss_risk, 3),
        expected_value_loss_if_wait=round(expected_value_loss_if_wait, 3),
        run_risk_score=round(run_risk_score, 3),
        market_heat_score=round(market_heat_score, 3),
        take_now_confidence=round(take_now_confidence, 3),
        wait_confidence=round(wait_confidence, 3),
    )