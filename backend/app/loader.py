import csv
import re
from typing import Optional, Tuple, Dict, List
from pathlib import Path

from app.models import Player, ProjectionLine
from app.normalization import (
    canonicalize_player_name,
    normalize_positions,
    build_player_id,
)


_diagnostics = {
    "rows_read": 0,
    "players_kept": 0,
    "duplicates_removed": 0,
    "encoding_used": "unknown",
}


def _safe_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        s = str(value).strip()
        if not s:
            return None
        # Remove commas from numbers like "1,234"
        s = s.replace(",", "")
        return float(s)
    except (ValueError, TypeError):
        return None


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace("#", "").replace(" ", "").replace("_", "").replace("/", "").replace("-", "")


def _extract_rate_and_components(value: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Parse rate stats like:
    - .285
    - .285 (171/600)
    Returns (rate, numerator, denominator)
    """
    if not value or not isinstance(value, str):
        return None, None, None
    
    value = value.strip()
    
    # Check for parentheses pattern
    match = re.match(r"^([\d.]+)\s*\((\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)\)$", value)
    if match:
        rate = _safe_float(match.group(1))
        num = _safe_float(match.group(2))
        denom = _safe_float(match.group(3))
        return rate, num, denom
    
    # Plain rate only
    rate = _safe_float(value)
    return rate, None, None


def _detect_columns(fieldnames: List[str]) -> Dict[str, str]:
    """
    Map normalized headers to actual CSV column names.
    """
    column_map = {}
    
    for original in fieldnames:
        normalized = _normalize_header(original)
        
        # Identity fields
        if normalized in ["player", "name"]:
            column_map["player"] = original
        elif normalized in ["pos", "position"]:
            column_map["pos"] = original
        elif normalized in ["adp", "avgpick"]:
            column_map["adp"] = original
        elif normalized in ["team", "mlbteam"]:
            column_map["team"] = original
        
        # Hitter projections
        elif normalized in ["gp", "gamesplayed", "g"]:
            column_map["gp"] = original
        elif normalized in ["ab", "atbats"]:
            column_map["ab"] = original
        elif normalized in ["r", "runs"]:
            column_map["r"] = original
        elif normalized in ["hr", "homeruns"]:
            column_map["hr"] = original
        elif normalized in ["rbi"]:
            column_map["rbi"] = original
        elif normalized in ["tb", "totalbases"]:
            column_map["tb"] = original
        elif normalized in ["sb", "stolenbases"]:
            column_map["sb"] = original
        elif normalized in ["avg", "battingaverage", "ba"]:
            column_map["avg"] = original
        elif normalized in ["obp"]:
            column_map["obp"] = original
        elif normalized in ["slg"]:
            column_map["slg"] = original
        elif normalized in ["walks", "walksdrawn", "bb"]:
            column_map["walks_drawn"] = original
        
        # Pitcher projections
        elif normalized in ["ip", "inningspitched"]:
            column_map["ip"] = original
        elif normalized in ["w", "wins"]:
            column_map["w"] = original
        elif normalized in ["l", "losses"]:
            column_map["l"] = original
        elif normalized in ["qs", "qualitystarts"]:
            column_map["qs"] = original
        elif normalized in ["sv", "saves"]:
            column_map["sv"] = original
        elif normalized in ["hld", "holds"]:
            column_map["hld"] = original
        elif normalized in ["k", "strikeouts", "so"]:
            column_map["k"] = original
        elif normalized in ["era"]:
            column_map["era"] = original
        elif normalized in ["whip"]:
            column_map["whip"] = original
        elif normalized in ["hitsallowed", "h"]:
            column_map["hits_allowed"] = original
        elif normalized in ["walksissued"]:
            column_map["walks_issued"] = original
        elif normalized in ["k9", "kper9", "strikeoutsper9"]:
            column_map["k_per_9"] = original
        elif normalized in ["kbb", "kperbb", "strikeouttowalkreatio"]:
            column_map["k_per_bb"] = original
    
    return column_map


def _count_filled_fields(projection: ProjectionLine) -> int:
    """Count how many projection fields are not None."""
    count = 0
    for field_name in projection.__dataclass_fields__:
        if getattr(projection, field_name) is not None:
            count += 1
    return count


def _pick_best_row(existing: Dict, new: Dict) -> Dict:
    """
    Choose better row when duplicates exist.
    Prefer: ADP present > more projections > team present > first seen
    """
    existing_adp = existing.get("adp")
    new_adp = new.get("adp")
    
    if existing_adp is not None and new_adp is None:
        return existing
    if new_adp is not None and existing_adp is None:
        return new
    
    existing_count = _count_filled_fields(existing["projection"])
    new_count = _count_filled_fields(new["projection"])
    
    if new_count > existing_count:
        return new
    if existing_count > new_count:
        return existing
    
    existing_team = existing.get("mlb_team")
    new_team = new.get("mlb_team")
    
    if existing_team and not new_team:
        return existing
    if new_team and not existing_team:
        return new
    
    return existing


def load_projections_csv(path: str) -> Tuple[Dict[str, Player], List[str]]:
    """
    Load player projections from CSV.
    Returns (players_by_id, player_ids_sorted_for_display)
    """
    global _diagnostics
    _diagnostics = {
        "rows_read": 0,
        "players_kept": 0,
        "duplicates_removed": 0,
        "encoding_used": "unknown",
    }
    
    # Try reading with UTF-8 first
    raw_rows = []
    encoding = "utf-8"
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            raw_rows = list(reader)
        _diagnostics["encoding_used"] = "utf-8"
    except UnicodeDecodeError:
        with open(path, "r", encoding="latin-1") as f:
            reader = csv.DictReader(f)
            raw_rows = list(reader)
        _diagnostics["encoding_used"] = "latin-1"
    
    _diagnostics["rows_read"] = len(raw_rows)
    
    if not raw_rows:
        return {}, []
    
    column_map = _detect_columns(list(raw_rows[0].keys()))
    
    player_data_by_id: Dict[str, Dict] = {}
    
    for row in raw_rows:
        # Extract identity
        player_name = row.get(column_map.get("player", ""), "").strip()
        if not player_name:
            continue
        
        display_name, normalized_name = canonicalize_player_name(player_name)
        pos_raw = row.get(column_map.get("pos", ""), "")
        positions = normalize_positions(pos_raw)
        player_id = build_player_id(display_name, positions)
        
        adp = _safe_float(row.get(column_map.get("adp", ""), None))
        mlb_team = row.get(column_map.get("team", ""), "").strip() or None
        
        # Extract projections
        projection = ProjectionLine()
        
        projection.gp = _safe_float(row.get(column_map.get("gp", ""), None))
        projection.ab = _safe_float(row.get(column_map.get("ab", ""), None))
        projection.r = _safe_float(row.get(column_map.get("r", ""), None))
        projection.hr = _safe_float(row.get(column_map.get("hr", ""), None))
        projection.rbi = _safe_float(row.get(column_map.get("rbi", ""), None))
        projection.tb = _safe_float(row.get(column_map.get("tb", ""), None))
        projection.sb = _safe_float(row.get(column_map.get("sb", ""), None))
        projection.walks_drawn = _safe_float(row.get(column_map.get("walks_drawn", ""), None))
        
        # Parse rate stats with components
        avg_raw = row.get(column_map.get("avg", ""), "")
        projection.avg, projection.avg_hits, projection.avg_ab = _extract_rate_and_components(avg_raw)
        
        obp_raw = row.get(column_map.get("obp", ""), "")
        projection.obp, projection.obp_times_on_base, projection.obp_pa = _extract_rate_and_components(obp_raw)
        
        slg_raw = row.get(column_map.get("slg", ""), "")
        projection.slg, projection.slg_bases, projection.slg_ab = _extract_rate_and_components(slg_raw)
        
        # Pitcher projections
        projection.ip = _safe_float(row.get(column_map.get("ip", ""), None))
        projection.w = _safe_float(row.get(column_map.get("w", ""), None))
        projection.l = _safe_float(row.get(column_map.get("l", ""), None))
        projection.qs = _safe_float(row.get(column_map.get("qs", ""), None))
        projection.sv = _safe_float(row.get(column_map.get("sv", ""), None))
        projection.hld = _safe_float(row.get(column_map.get("hld", ""), None))
        projection.k = _safe_float(row.get(column_map.get("k", ""), None))
        projection.hits_allowed = _safe_float(row.get(column_map.get("hits_allowed", ""), None))
        projection.walks_issued = _safe_float(row.get(column_map.get("walks_issued", ""), None))
        
        era_raw = row.get(column_map.get("era", ""), "")
        projection.era, projection.era_er, projection.era_ip = _extract_rate_and_components(era_raw)
        
        whip_raw = row.get(column_map.get("whip", ""), "")
        projection.whip, projection.whip_wh, projection.whip_ip = _extract_rate_and_components(whip_raw)
        
        # New pitcher fields
        projection.k_per_9 = _safe_float(row.get(column_map.get("k_per_9", ""), None))
        projection.k_per_bb = _safe_float(row.get(column_map.get("k_per_bb", ""), None))
        
        candidate = {
            "player_id": player_id,
            "name": display_name,
            "normalized_name": normalized_name,
            "adp": adp,
            "positions": positions,
            "mlb_team": mlb_team,
            "projection": projection,
        }
        
        if player_id in player_data_by_id:
            _diagnostics["duplicates_removed"] += 1
            player_data_by_id[player_id] = _pick_best_row(player_data_by_id[player_id], candidate)
        else:
            player_data_by_id[player_id] = candidate
    
    # Build Player objects
    players_by_id: Dict[str, Player] = {}
    for player_id, data in player_data_by_id.items():
        players_by_id[player_id] = Player(
            player_id=data["player_id"],
            name=data["name"],
            normalized_name=data["normalized_name"],
            adp=data["adp"],
            positions=data["positions"],
            mlb_team=data["mlb_team"],
            projection=data["projection"],
            projected_points=None,
            derived_rank=None,
        )
    
    _diagnostics["players_kept"] = len(players_by_id)
    
    # Sort for display: ADP first (ascending), then by name
    with_adp = [(pid, p) for pid, p in players_by_id.items() if p.adp is not None]
    without_adp = [(pid, p) for pid, p in players_by_id.items() if p.adp is None]
    
    with_adp.sort(key=lambda x: (x[1].adp, x[1].name))
    without_adp.sort(key=lambda x: x[1].name)
    
    player_ids_sorted_for_display = [pid for pid, _ in with_adp] + [pid for pid, _ in without_adp]
    
    return players_by_id, player_ids_sorted_for_display


def get_loader_diagnostics() -> dict:
    """Return loader diagnostics."""
    return _diagnostics.copy()