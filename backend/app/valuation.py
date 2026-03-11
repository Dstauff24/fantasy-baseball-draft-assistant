from dataclasses import replace
from typing import Dict, List, Tuple

from app.models import Player
from app.config import ScoringConfig


def _num(value) -> float:
    """Convert value to float, return 0.0 if None or invalid."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _num_optional(value):
    """Convert value to float, return None if None or invalid."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp value between low and high."""
    return max(low, min(high, value))


def _safe_non_negative(value: float) -> float:
    """Floor negative values to zero."""
    return max(0.0, value)


def _get_strict_override(proj, attr_names: List[str]) -> Tuple[float | None, str | None]:
    """
    Return first explicit numeric override value for strict, role-safe fields.
    Only fields in attr_names are considered.
    """
    for attr in attr_names:
        if not hasattr(proj, attr):
            continue
        raw = getattr(proj, attr)
        if raw is None:
            continue
        value = _num_optional(raw)
        if value is None:
            continue
        return value, attr
    return None, None


def _positions_set(player: Player) -> set[str]:
    return {p.upper() for p in (player.positions or [])}


def is_pitcher(player: Player) -> bool:
    """
    Pitcher if:
    - positions include SP/RP/P, or
    - projection.ip is meaningfully present
    """
    pos = _positions_set(player)
    if any(p in pos for p in {"SP", "RP", "P"}):
        return True
    return _num(getattr(player.projection, "ip", None)) >= 1.0


def is_hitter(player: Player) -> bool:
    """
    Hitter if:
    - positions include hitter positions, or
    - projection.ab is meaningfully present
    """
    pos = _positions_set(player)
    hitter_pos = {"C", "1B", "2B", "3B", "SS", "OF", "LF", "CF", "RF", "DH", "UTIL"}
    if any(p in pos for p in hitter_pos):
        return True
    return _num(getattr(player.projection, "ab", None)) >= 1.0


def get_player_scoring_role(player: Player) -> str:
    """Debug helper: hitter, pitcher, both, or none."""
    h = is_hitter(player)
    p = is_pitcher(player)
    if h and p:
        return "both"
    if h:
        return "hitter"
    if p:
        return "pitcher"
    return "none"


def derive_hitter_stats(player: Player) -> Dict[str, float]:
    """
    Derive hitter scoring categories from projection data.

    Source-first logic (strict role-safe fields only):
    - Use strict hitter override fields when explicitly present.
    - Otherwise derive missing categories.
    """
    proj = player.projection

    # Direct scoring categories from hitter projection surface
    R = _num(getattr(proj, "r", None))
    TB = _num(getattr(proj, "tb", None))
    RBI = _num(getattr(proj, "rbi", None))
    SB = _num(getattr(proj, "sb", None))

    # Strict hitter-only overrides (no generic k/bb)
    source_BB, source_BB_field = _get_strict_override(
        proj, ["walks_drawn", "hitter_bb", "batting_walks"]
    )
    source_K, source_K_field = _get_strict_override(
        proj, ["hitter_k", "batting_strikeouts"]
    )
    source_CYC, source_CYC_field = _get_strict_override(
        proj, ["cyc", "cycle", "cycles"]
    )

    # Inputs for derivation
    AVG = _num(getattr(proj, "avg", None))
    AB = _num(getattr(proj, "ab", None))
    OBP = _num(getattr(proj, "obp", None))
    SLG = _num(getattr(proj, "slg", None))
    HR = _num(getattr(proj, "hr", None))

    # Internal helpers
    H = AVG * AB if AB > 0 else 0.0

    BB_base = 0.0
    if AB > 0 and 0.0 < OBP < 1.0:
        denominator = 1.0 - OBP
        if denominator != 0:
            BB_base = ((OBP * AB) - H) / denominator
    BB_base = _safe_non_negative(BB_base)

    # Pre-regression BB estimate
    BB_pre = _safe_non_negative(BB_base * 1.18)

    # Internal PA estimate for derived BB/K
    PA_est = AB + BB_pre

    HR_rate = HR / AB if AB > 0 else 0.0
    SB_rate = SB / AB if AB > 0 else 0.0
    ISO_proxy = SLG - AVG
    Walk_skill = OBP - AVG
    Contact_skill = AVG - 0.240
    Speed_skill = SB / AB if AB > 0 else 0.0

    # Raw rates
    BB_rate = (BB_pre / PA_est) if PA_est > 0 else 0.0
    K_rate_raw = (
        0.15
        + 0.85 * HR_rate
        + 0.16 * ISO_proxy
        - 0.08 * Walk_skill
        - 0.55 * Contact_skill
        - 0.35 * Speed_skill
    )
    K_rate_raw = _clamp(K_rate_raw, 0.10, 0.36)

    # Archetype classification
    if HR_rate >= 0.055:
        archetype = "POWER"
    elif SB_rate >= 0.030:
        archetype = "SPEED"
    elif Contact_skill >= 0.030:
        archetype = "CONTACT"
    else:
        archetype = "BALANCED"

    # Archetype regression for derived BB/K
    if archetype == "POWER":
        BB_rate_reg = 0.92 * BB_rate + 0.08 * 0.100
        K_rate_reg = 0.92 * K_rate_raw + 0.08 * 0.260
    elif archetype == "SPEED":
        BB_rate_reg = 0.92 * BB_rate + 0.08 * 0.070
        K_rate_reg = 0.92 * K_rate_raw + 0.08 * 0.180
    elif archetype == "CONTACT":
        BB_rate_reg = 0.92 * BB_rate + 0.08 * 0.080
        K_rate_reg = 0.92 * K_rate_raw + 0.08 * 0.150
    else:  # BALANCED
        BB_rate_reg = 0.95 * BB_rate + 0.05 * 0.086
        K_rate_reg = 0.95 * K_rate_raw + 0.05 * 0.220

    BB_rate_reg = _clamp(BB_rate_reg, 0.02, 0.25)
    K_rate_reg = _clamp(K_rate_reg, 0.10, 0.36)

    BB_derived = _safe_non_negative(BB_rate_reg * PA_est)
    K_derived = _safe_non_negative(K_rate_reg * PA_est)
    CYC_derived = 0.0

    # Strict source-first override
    BB = _safe_non_negative(source_BB) if source_BB is not None else BB_derived
    K = _safe_non_negative(source_K) if source_K is not None else K_derived
    CYC = _safe_non_negative(source_CYC) if source_CYC is not None else CYC_derived

    return {
        "R": R,
        "TB": TB,
        "RBI": RBI,
        "BB": BB,
        "K": K,
        "SB": SB,
        "CYC": CYC,
        # Intermediate / debug
        "H": H,
        "BB_base": BB_base,
        "BB_pre": BB_pre,
        "BB_derived": BB_derived,
        "K_derived": K_derived,
        "PA_est": PA_est,
        "HR_rate": HR_rate,
        "SB_rate": SB_rate,
        "ISO_proxy": ISO_proxy,
        "Walk_skill": Walk_skill,
        "Contact_skill": Contact_skill,
        "Speed_skill": Speed_skill,
        "BB_rate_pre": BB_rate,
        "BB_rate_reg": BB_rate_reg,
        "K_rate_raw": K_rate_raw,
        "K_rate_reg": K_rate_reg,
        "K_rate": K_rate_reg,  # compatibility with existing debug prints
        "Archetype": archetype,
        "BB_source": f"source:{source_BB_field}" if source_BB is not None else "derived",
        "K_source": f"source:{source_K_field}" if source_K is not None else "derived",
        "CYC_source": f"source:{source_CYC_field}" if source_CYC is not None else "derived",
    }


def derive_pitcher_stats(player: Player) -> Dict[str, float]:
    """
    Derive pitcher scoring categories from projection data.

    Source-first logic (strict role-safe fields only):
    - Use strict pitcher override fields when explicitly present.
    - Otherwise derive missing categories.

    BB derivation priority when strict BB source is absent:
      1) BB/9
      2) K/BB
      3) fallback heuristic (+ archetype refinement layer)
    """
    proj = player.projection

    # Direct pitcher stats
    IP = _num(getattr(proj, "ip", None))
    W = _num(getattr(proj, "w", None))
    L = _num(getattr(proj, "l", None))
    SV = _num(getattr(proj, "sv", None))
    HLD = _num(getattr(proj, "hld", None))
    K = _num(getattr(proj, "k", None))
    QS = _num(getattr(proj, "qs", None))

    # Ratio inputs
    ERA = _num(getattr(proj, "era", None))
    WHIP = _num(getattr(proj, "whip", None))

    # Strict pitcher-only overrides
    source_H, source_H_field = _get_strict_override(proj, ["hits_allowed", "pitcher_h"])
    source_ER, source_ER_field = _get_strict_override(proj, ["earned_runs", "pitcher_er", "era_er"])
    source_BB, source_BB_field = _get_strict_override(proj, ["walks_issued", "pitcher_bb"])
    source_PKO, source_PKO_field = _get_strict_override(proj, ["pko", "pickoffs", "pick_offs"])
    source_NH, source_NH_field = _get_strict_override(proj, ["nh", "no_hitters"])
    source_PG, source_PG_field = _get_strict_override(proj, ["pg", "perfect_games"])

    # Ratio helper inputs
    BB_per_9, BB_per_9_field = _get_strict_override(proj, ["bb_per_9", "bb9", "bb_9", "bb_per9"])
    K_per_BB, K_per_BB_field = _get_strict_override(proj, ["k_per_bb", "kbb", "k_bb", "k_to_bb"])
    K_per_9, K_per_9_field = _get_strict_override(proj, ["k_per_9", "k9", "k_9", "k_per9"])

    ER_derived = _safe_non_negative((ERA * IP) / 9.0 if IP > 0 else 0.0)
    K_per_IP = K / IP if IP > 0 else 0.0
    is_reliever = (SV > 0) or (HLD > 0) or (IP < 80)

    # NEW: Pitcher archetype classification (debug + fallback refinement only)
    if K_per_IP >= 1.05:
        pitcher_archetype = "POWER"
    elif WHIP <= 1.12 and ERA <= 3.70:
        pitcher_archetype = "COMMAND"
    elif K_per_IP <= 0.78:
        pitcher_archetype = "CONTACT"
    elif WHIP >= 1.30 or ERA >= 4.40:
        pitcher_archetype = "WILD"
    else:
        pitcher_archetype = "BALANCED"

    # BB with strict source-first and hierarchy fallback
    BB_fallback_base_per_ip = 0.0
    BB_fallback_adj_per_ip = 0.0

    if source_BB is not None:
        BB = _safe_non_negative(source_BB)
        BB_per_IP = BB / IP if IP > 0 else 0.0
        BB_source = f"source:{source_BB_field}"
    else:
        if IP > 0 and BB_per_9 is not None and BB_per_9 >= 0:
            BB = _safe_non_negative((BB_per_9 * IP) / 9.0)
            BB_per_IP = BB / IP if IP > 0 else 0.0
            BB_source = f"bb_per_9:{BB_per_9_field}"
        elif K_per_BB is not None and K_per_BB > 0 and K >= 0:
            BB = _safe_non_negative(K / K_per_BB)
            BB_per_IP = BB / IP if IP > 0 else 0.0
            BB_source = f"k_per_bb:{K_per_BB_field}"
        else:
            # Base fallback (unchanged starter/reliever structure)
            if is_reliever:
                BB_fallback_base_per_ip = 0.38 - 0.09 * K_per_IP + 0.02 * (ERA - 4.0)
            else:
                BB_fallback_base_per_ip = 0.36 - 0.11 * K_per_IP + 0.02 * (ERA - 4.0)

            # NEW: archetype refinement layer (ONLY fallback branch)
            archetype_delta = {
                "POWER": -0.015,
                "COMMAND": -0.020,
                "CONTACT": +0.015,
                "WILD": +0.030,
                "BALANCED": 0.0,
            }
            BB_fallback_adj_per_ip = archetype_delta.get(pitcher_archetype, 0.0)

            bb_per_ip_est = BB_fallback_base_per_ip + BB_fallback_adj_per_ip
            BB_per_IP = _clamp(bb_per_ip_est, 0.20, 0.42)
            BB = _safe_non_negative(IP * BB_per_IP)
            BB_source = f"fallback_heuristic:{pitcher_archetype.lower()}"

    # H from strict source else derive from WHIP identity
    H_derived = _safe_non_negative((WHIP * IP) - BB if IP > 0 else 0.0)
    if source_H is not None:
        H = _safe_non_negative(source_H)
        H_source = f"source:{source_H_field}"
    else:
        H = H_derived
        H_source = "derived_whip_minus_bb"

    # ER from strict source else derive
    if source_ER is not None:
        ER = _safe_non_negative(source_ER)
        ER_source = f"source:{source_ER_field}"
    else:
        ER = ER_derived
        ER_source = "derived_era_ip"

    # Bonuses strict source else derived
    PKO_derived = IP * 0.005
    NH_derived = 0.0
    PG_derived = 0.0

    if source_PKO is not None:
        PKO = _safe_non_negative(source_PKO)
        PKO_source = f"source:{source_PKO_field}"
    else:
        PKO = PKO_derived
        PKO_source = "derived"

    if source_NH is not None:
        NH = _safe_non_negative(source_NH)
        NH_source = f"source:{source_NH_field}"
    else:
        NH = NH_derived
        NH_source = "derived"

    if source_PG is not None:
        PG = _safe_non_negative(source_PG)
        PG_source = f"source:{source_PG_field}"
    else:
        PG = PG_derived
        PG_source = "derived"

    return {
        "IP": IP,
        "H": H,
        "ER": ER,
        "BB": BB,
        "K": K,
        "PKO": PKO,
        "NH": NH,
        "PG": PG,
        "W": W,
        "L": L,
        "SV": SV,
        "HD": HLD,
        # Intermediate / debug
        "QS": QS,
        "is_reliever": is_reliever,
        "Pitcher_archetype": pitcher_archetype,
        "K_per_IP": K_per_IP,
        "BB_per_IP": BB_per_IP,
        "BB_source": BB_source,
        "BB_fallback_base_per_ip": BB_fallback_base_per_ip,
        "BB_fallback_adj_per_ip": BB_fallback_adj_per_ip,
        "H_source": H_source,
        "ER_source": ER_source,
        "PKO_source": PKO_source,
        "NH_source": NH_source,
        "PG_source": PG_source,
        "K_per_9_input": K_per_9 if K_per_9 is not None else 0.0,
        "K_per_9_input_field": K_per_9_field or "",
        "K_per_BB_input": K_per_BB if K_per_BB is not None else 0.0,
        "K_per_BB_input_field": K_per_BB_field or "",
        "BB_per_9_input": BB_per_9 if BB_per_9 is not None else 0.0,
        "BB_per_9_input_field": BB_per_9_field or "",
    }


def calculate_hitter_points(player: Player, scoring: ScoringConfig) -> float:
    """Calculate fantasy points for hitter contribution."""
    derived = derive_hitter_stats(player)

    points = 0.0
    points += derived["R"] * scoring.runs
    points += derived["TB"] * scoring.total_bases
    points += derived["RBI"] * scoring.rbi
    points += derived["BB"] * scoring.walks
    points += derived["K"] * scoring.strikeouts_hitters
    points += derived["SB"] * scoring.stolen_bases
    points += derived["CYC"] * scoring.cycle_bonus
    return points


def calculate_pitcher_points(player: Player, scoring: ScoringConfig) -> float:
    """Calculate fantasy points for pitcher contribution."""
    derived = derive_pitcher_stats(player)

    points = 0.0
    points += derived["IP"] * scoring.innings_pitched
    points += derived["H"] * scoring.hits_allowed
    points += derived["ER"] * scoring.earned_runs
    points += derived["BB"] * scoring.walks_issued
    points += derived["K"] * scoring.strikeouts_pitchers
    points += derived["W"] * scoring.wins
    points += derived["L"] * scoring.losses
    points += derived["SV"] * scoring.saves
    points += derived["HD"] * scoring.holds
    points += derived["PKO"] * scoring.pickoff_bonus
    points += derived["NH"] * scoring.no_hitter_bonus
    points += derived["PG"] * scoring.perfect_game_bonus
    return points


def calculate_player_points(player: Player, scoring: ScoringConfig) -> float:
    """
    Role-safe total fantasy points.
    - hitter-only players: hitter points
    - pitcher-only players: pitcher points
    - two-way players: both
    """
    hitter_flag = is_hitter(player)
    pitcher_flag = is_pitcher(player)

    points = 0.0
    if hitter_flag:
        points += calculate_hitter_points(player, scoring)
    if pitcher_flag:
        points += calculate_pitcher_points(player, scoring)
    return points


def rank_players_by_points(
    players_by_id: Dict[str, Player],
    scoring: ScoringConfig
) -> Tuple[Dict[str, Player], List[str]]:
    """
    Calculate projected points and assign derived ranks to all players.
    Returns (updated_players_by_id, sorted_player_ids_by_value)
    """
    player_points: List[Tuple[str, Player, float]] = []

    for pid, player in players_by_id.items():
        points = calculate_player_points(player, scoring)
        player_points.append((pid, player, points))

    # Sort by points desc, then ADP asc, then name asc
    player_points.sort(
        key=lambda x: (
            -x[2],
            x[1].adp if x[1].adp is not None else 999999.0,
            x[1].name,
        )
    )

    updated_players: Dict[str, Player] = {}
    sorted_ids: List[str] = []

    for rank_idx, (pid, player, points) in enumerate(player_points, start=1):
        updated_player = replace(
            player,
            projected_points=points,
            derived_rank=rank_idx,
        )
        updated_players[pid] = updated_player
        sorted_ids.append(pid)

    return updated_players, sorted_ids