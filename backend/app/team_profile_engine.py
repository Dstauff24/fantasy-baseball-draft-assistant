from dataclasses import dataclass, field

from app.draft_state import DraftState
from app.models import Player


@dataclass
class TeamProfile:
    power_score: float = 0.0
    speed_score: float = 0.0
    average_stability: float = 0.0
    sp_volume: float = 0.0
    sp_ratio_stability: float = 0.0
    sp_strikeout_score: float = 0.0
    save_potential: float = 0.0
    risk_index: float = 0.0
    notes: list[str] = field(default_factory=list)


def _safe_float(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _is_pitcher(player: Player) -> bool:
    pos = set(getattr(player, "positions", []) or [])
    return any(p in {"SP", "RP", "P"} for p in pos)


def _is_sp(player: Player) -> bool:
    pos = set(getattr(player, "positions", []) or [])
    return "SP" in pos or "P" in pos


def _is_rp(player: Player) -> bool:
    pos = set(getattr(player, "positions", []) or [])
    return "RP" in pos and "SP" not in pos and "P" not in pos


def _is_hitter(player: Player) -> bool:
    return not _is_pitcher(player)


def _player_power_component(player: Player) -> float:
    proj = getattr(player, "projection", None)
    if proj is None:
        return 0.0
    hr = _safe_float(getattr(proj, "hr", 0.0))
    tb = _safe_float(getattr(proj, "tb", 0.0))
    rbi = _safe_float(getattr(proj, "rbi", 0.0))
    return (hr * 1.2) + (tb * 0.08) + (rbi * 0.04)


def _player_speed_component(player: Player) -> float:
    proj = getattr(player, "projection", None)
    if proj is None:
        return 0.0
    sb = _safe_float(getattr(proj, "sb", 0.0))
    return sb * 1.5


def _player_avg_component(player: Player) -> float:
    proj = getattr(player, "projection", None)
    if proj is None:
        return 0.0
    avg = _safe_float(getattr(proj, "avg", 0.0))
    ab = _safe_float(getattr(proj, "ab", 0.0))
    if avg <= 0.0 or ab <= 0.0:
        return 0.0
    return max(0.0, (avg - 0.240) * ab)


def _player_sp_volume_component(player: Player) -> float:
    proj = getattr(player, "projection", None)
    if proj is None:
        return 0.0
    return _safe_float(getattr(proj, "ip", 0.0))


def _player_sp_ratio_component(player: Player) -> float:
    proj = getattr(player, "projection", None)
    if proj is None:
        return 0.0
    era = _safe_float(getattr(proj, "era", 0.0))
    whip = _safe_float(getattr(proj, "whip", 0.0))
    ip = _safe_float(getattr(proj, "ip", 0.0))
    if ip <= 0.0 or era <= 0.0 or whip <= 0.0:
        return 0.0
    era_score = max(0.0, 5.00 - era) * 1.8
    whip_score = max(0.0, 1.45 - whip) * 18.0
    return era_score + whip_score


def _player_sp_k_component(player: Player) -> float:
    proj = getattr(player, "projection", None)
    if proj is None:
        return 0.0
    return _safe_float(getattr(proj, "k", 0.0))


def _player_sv_component(player: Player) -> float:
    proj = getattr(player, "projection", None)
    if proj is None:
        return 0.0
    sv = _safe_float(getattr(proj, "sv", 0.0))
    hld = _safe_float(getattr(proj, "hld", 0.0))
    return (sv * 1.3) + (hld * 0.6)


def get_user_team_profile(draft_state: DraftState) -> TeamProfile:
    roster = draft_state.get_user_roster()
    profile = TeamProfile()

    hitter_count = 0
    sp_count = 0
    rp_count = 0

    for player in roster:
        if _is_hitter(player):
            hitter_count += 1
            profile.power_score += _player_power_component(player)
            profile.speed_score += _player_speed_component(player)
            profile.average_stability += _player_avg_component(player)

        if _is_sp(player):
            sp_count += 1
            profile.sp_volume += _player_sp_volume_component(player)
            profile.sp_ratio_stability += _player_sp_ratio_component(player)
            profile.sp_strikeout_score += _player_sp_k_component(player)

        if _is_rp(player):
            rp_count += 1
            profile.save_potential += _player_sv_component(player)

    if hitter_count == 0:
        profile.notes.append("No hitters rostered yet.")
    if sp_count == 0:
        profile.notes.append("No SP foundation established yet.")
    elif sp_count == 1:
        profile.notes.append("Pitching foundation started, but SP volume is still light.")
    if rp_count == 0:
        profile.notes.append("No meaningful saves foundation yet.")
    if profile.power_score < 55:
        profile.notes.append("Power foundation remains underbuilt.")
    if profile.speed_score < 18:
        profile.notes.append("Speed foundation remains underbuilt.")
    if hitter_count > 0 and profile.average_stability < 8:
        profile.notes.append("Batting average stability is still thin.")

    return profile


def calculate_category_balance_bonus(
    draft_state: DraftState,
    player: Player,
) -> float:
    total, _ = calculate_category_balance_bonus_with_components(draft_state, player)
    return total


def calculate_category_balance_bonus_with_components(
    draft_state: DraftState,
    player: Player,
) -> tuple[float, dict[str, float]]:
    profile = get_user_team_profile(draft_state)
    pos = set(getattr(player, "positions", []) or [])
    proj = getattr(player, "projection", None)

    components: dict[str, float] = {
        "power_need_bonus": 0.0,
        "speed_need_bonus": 0.0,
        "avg_need_bonus": 0.0,
        "sp_volume_need_bonus": 0.0,
        "sp_ratio_need_bonus": 0.0,
        "save_need_bonus": 0.0,
        "anti_overstack_penalty": 0.0,
    }

    if not _is_pitcher(player):
        hr = _safe_float(getattr(proj, "hr", 0.0)) if proj else 0.0
        sb = _safe_float(getattr(proj, "sb", 0.0)) if proj else 0.0
        avg = _safe_float(getattr(proj, "avg", 0.0)) if proj else 0.0

        if profile.power_score < 55:
            if hr >= 25:
                components["power_need_bonus"] += 1.25
            elif hr >= 18:
                components["power_need_bonus"] += 0.60

        if profile.speed_score < 18:
            if sb >= 20:
                components["speed_need_bonus"] += 1.25
            elif sb >= 12:
                components["speed_need_bonus"] += 0.60

        if profile.average_stability < 8:
            if avg >= 0.285:
                components["avg_need_bonus"] += 0.75
            elif avg >= 0.275:
                components["avg_need_bonus"] += 0.35

    if _is_sp(player):
        ip = _safe_float(getattr(proj, "ip", 0.0)) if proj else 0.0
        era = _safe_float(getattr(proj, "era", 0.0)) if proj else 0.0
        whip = _safe_float(getattr(proj, "whip", 0.0)) if proj else 0.0

        if profile.sp_volume < 360:
            if ip >= 160:
                components["sp_volume_need_bonus"] += 1.50
            elif ip >= 135:
                components["sp_volume_need_bonus"] += 0.75

        if profile.sp_ratio_stability < 12:
            if era > 0 and whip > 0 and era <= 3.50 and whip <= 1.15:
                components["sp_ratio_need_bonus"] += 1.40
            elif era > 0 and whip > 0 and era <= 3.80 and whip <= 1.22:
                components["sp_ratio_need_bonus"] += 0.70

    if _is_rp(player):
        sv = _safe_float(getattr(proj, "sv", 0.0)) if proj else 0.0
        if profile.save_potential < 20:
            if sv >= 25:
                components["save_need_bonus"] += 1.00
            elif sv >= 15:
                components["save_need_bonus"] += 0.50

    roster = draft_state.get_user_roster()
    current_pick = draft_state.get_current_pick_number()
    early_rounds = current_pick <= 75

    user_sp_count = sum(1 for p in roster if _is_sp(p))
    user_rp_count = sum(1 for p in roster if _is_rp(p))
    user_hitter_count = sum(1 for p in roster if not _is_pitcher(p))

    if early_rounds:
        if _is_sp(player) and user_sp_count >= 1 and user_hitter_count == 0:
            components["anti_overstack_penalty"] -= 1.25
        if _is_rp(player) and user_rp_count >= 1:
            components["anti_overstack_penalty"] -= 0.75
        if not _is_pitcher(player):
            dh_only = pos == {"DH"}
            if dh_only and user_hitter_count >= 1:
                components["anti_overstack_penalty"] -= 0.50

    total = round(sum(components.values()), 3)
    return total, components