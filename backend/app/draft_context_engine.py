from dataclasses import dataclass, field
from typing import Literal

from app.draft_state import DraftState


DraftPhase = Literal[
    "opening",
    "foundation",
    "build_out",
    "category_shaping",
    "endgame",
]

BuildShape = Literal[
    "balanced",
    "hitter_heavy",
    "pitcher_heavy",
    "hitter_only",
    "pitcher_only",
]

StrategyPosture = Literal[
    "best_player_available",
    "lean_hitter",
    "lean_pitcher",
    "balance_roster",
    "protect_hitter_foundation",
    "protect_pitching_foundation",
    "prepare_category_shape",
]


@dataclass
class DraftContext:
    current_pick: int
    current_round: int
    picks_until_next_user_turn: int

    draft_phase: DraftPhase
    build_shape: BuildShape
    strategy_posture: StrategyPosture

    user_hitter_count: int
    user_pitcher_count: int
    user_sp_count: int
    user_rp_count: int

    notes: list[str] = field(default_factory=list)


def get_current_round(draft_state: DraftState) -> int:
    current_pick = draft_state.get_current_pick_number()
    team_count = draft_state.league_config.team_count
    return ((current_pick - 1) // team_count) + 1


def get_picks_until_next_user_turn(draft_state: DraftState) -> int:
    current_pick = draft_state.get_current_pick_number()
    next_user_pick = draft_state.get_next_user_pick()
    if next_user_pick < current_pick:
        return 0
    return max(0, next_user_pick - current_pick)


def get_user_roster_counts(draft_state: DraftState) -> dict[str, int]:
    roster = draft_state.get_user_roster()

    hitter_count = 0
    pitcher_count = 0
    sp_count = 0
    rp_count = 0

    for p in roster:
        positions = set(getattr(p, "positions", []) or [])
        is_sp = "SP" in positions or "P" in positions
        is_rp = "RP" in positions and "SP" not in positions and "P" not in positions

        if is_sp or is_rp:
            pitcher_count += 1
        else:
            hitter_count += 1

        if is_sp:
            sp_count += 1
        if is_rp:
            rp_count += 1

    return {
        "hitters": hitter_count,
        "pitchers": pitcher_count,
        "sp": sp_count,
        "rp": rp_count,
    }


def detect_draft_phase(draft_state: DraftState) -> DraftPhase:
    current_round = get_current_round(draft_state)

    if current_round <= 3:
        return "opening"
    if current_round <= 6:
        return "foundation"
    if current_round <= 12:
        return "build_out"
    if current_round <= 18:
        return "category_shaping"
    return "endgame"


def detect_build_shape(draft_state: DraftState) -> BuildShape:
    counts = get_user_roster_counts(draft_state)
    hitters = counts["hitters"]
    pitchers = counts["pitchers"]

    if hitters == 0 and pitchers > 0:
        return "pitcher_only"
    if pitchers == 0 and hitters > 0:
        return "hitter_only"

    if (hitters - pitchers) >= 2:
        return "hitter_heavy"
    if (pitchers - hitters) >= 2:
        return "pitcher_heavy"
    return "balanced"


def detect_strategy_posture(draft_state: DraftState) -> tuple[StrategyPosture, list[str]]:
    phase = detect_draft_phase(draft_state)
    shape = detect_build_shape(draft_state)
    counts = get_user_roster_counts(draft_state)

    notes: list[str] = []

    if phase == "opening":
        if counts["sp"] >= 1 and counts["hitters"] == 0:
            notes.append("Opening SP already taken; prioritize hitter foundation.")
            return "protect_hitter_foundation", notes
        return "best_player_available", notes

    if phase == "foundation":
        if shape == "pitcher_heavy" or counts["sp"] >= 2:
            notes.append("Pitching exposure elevated; lean hitter.")
            return "lean_hitter", notes
        if shape == "hitter_heavy" and counts["pitchers"] == 0:
            notes.append("No pitching foundation yet; lean pitcher.")
            return "lean_pitcher", notes
        return "balance_roster", notes

    if phase == "build_out":
        notes.append("Build-out phase: prioritize structural roster balance.")
        return "balance_roster", notes

    if phase == "category_shaping":
        notes.append("Category shaping phase: refine profile and balance.")
        return "prepare_category_shape", notes

    notes.append("Endgame: best-player-available cleanup.")
    return "best_player_available", notes


def build_draft_context(draft_state: DraftState) -> DraftContext:
    current_pick = draft_state.get_current_pick_number()
    current_round = get_current_round(draft_state)
    picks_until_next = get_picks_until_next_user_turn(draft_state)

    counts = get_user_roster_counts(draft_state)
    draft_phase = detect_draft_phase(draft_state)
    build_shape = detect_build_shape(draft_state)
    strategy_posture, notes = detect_strategy_posture(draft_state)

    return DraftContext(
        current_pick=current_pick,
        current_round=current_round,
        picks_until_next_user_turn=picks_until_next,
        draft_phase=draft_phase,
        build_shape=build_shape,
        strategy_posture=strategy_posture,
        user_hitter_count=counts["hitters"],
        user_pitcher_count=counts["pitchers"],
        user_sp_count=counts["sp"],
        user_rp_count=counts["rp"],
        notes=notes,
    )