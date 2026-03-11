import re
import unicodedata
from typing import Iterable


VALID_POSITIONS = {
    "C", "1B", "2B", "3B", "SS", "OF", "UTIL", "DH", "SP", "RP"
}


def normalize_text(value: str) -> str:
    """
    Normalize text by cleaning whitespace and unicode formatting.
    """
    if value is None:
        return ""

    value = unicodedata.normalize("NFC", str(value))
    value = value.strip()
    value = re.sub(r"\s+", " ", value)
    return value


def normalize_name_for_lookup(name: str) -> str:
    """
    Normalize a player name for internal lookup.
    """
    return normalize_text(name).lower()


def normalize_positions(raw_positions) -> tuple[str, ...]:
    """
    Convert raw positions into a normalized tuple.
    Supports strings like:
    - '1B, DH'
    - 'OF/UTIL'
    """
    if raw_positions is None:
        return tuple()

    if isinstance(raw_positions, str):
        text = normalize_text(raw_positions).replace("/", ",")
        parts = [p.strip().upper() for p in text.split(",") if p.strip()]
    else:
        parts = [normalize_text(str(p)).upper() for p in raw_positions if str(p).strip()]

    cleaned = []
    for pos in parts:
        if pos in VALID_POSITIONS and pos not in cleaned:
            cleaned.append(pos)

    return tuple(cleaned)


def build_player_id(name: str, positions: tuple[str, ...]) -> str:
    """
    Build a deterministic player ID from normalized name + positions.
    """
    normalized_name = normalize_name_for_lookup(name)
    slug = normalized_name.replace(" ", "-")
    pos_part = "-".join(positions).lower() if positions else "unknown"
    return f"{slug}__{pos_part}"


def canonicalize_player_name(name: str) -> tuple[str, str]:
    """
    Return both display-friendly and normalized name forms.
    """
    display_name = normalize_text(name)
    normalized_name = normalize_name_for_lookup(display_name)
    return display_name, normalized_name