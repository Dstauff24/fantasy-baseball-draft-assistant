from dataclasses import dataclass
from typing import Optional

from app.models import Player


_HITTER_POS = {"C", "1B", "2B", "3B", "SS", "OF", "LF", "CF", "RF", "DH", "UTIL"}
_PITCHER_POS = {"SP", "RP", "P"}


@dataclass
class PlayerPool:
    players_by_id: dict[str, Player]
    ids_by_value: list[str]
    ids_by_adp: list[str]

    def get_player(self, player_id: str) -> Optional[Player]:
        return self.players_by_id.get(player_id)

    def get_top_by_value(self, n: int = 20) -> list[Player]:
        ids = self.ids_by_value[: max(0, n)]
        return [self.players_by_id[pid] for pid in ids if pid in self.players_by_id]

    def get_top_by_adp(self, n: int = 20) -> list[Player]:
        ids = self.ids_by_adp[: max(0, n)]
        return [self.players_by_id[pid] for pid in ids if pid in self.players_by_id]

    def search_by_name(self, query: str, limit: int = 10) -> list[Player]:
        q = (query or "").strip().lower()
        if not q or limit <= 0:
            return []

        candidates: list[tuple[int, float, str, Player]] = []
        for p in self.players_by_id.values():
            name = (p.name or "").lower()
            normalized = (p.normalized_name or "").lower()

            in_name = q in name
            in_normalized = q in normalized
            if not (in_name or in_normalized):
                continue

            starts = name.startswith(q) or normalized.startswith(q)
            match_bucket = 0 if starts else 1
            adp_key = p.adp if p.adp is not None else float("inf")
            candidates.append((match_bucket, adp_key, p.name or "", p))

        candidates.sort(key=lambda x: (x[0], x[1], x[2]))
        return [row[3] for row in candidates[:limit]]

    def get_two_way_players(self) -> list[Player]:
        two_way: list[Player] = []
        for p in self.players_by_id.values():
            if self._is_two_way(p):
                two_way.append(p)

        two_way.sort(
            key=lambda p: (
                p.derived_rank if p.derived_rank is not None else 10**9,
                p.adp if p.adp is not None else float("inf"),
                p.name or "",
            )
        )
        return two_way

    @staticmethod
    def _is_two_way(player: Player) -> bool:
        positions = {pos.upper() for pos in (player.positions or [])}
        has_pitcher_pos = any(pos in _PITCHER_POS for pos in positions)
        has_hitter_pos = any(pos in _HITTER_POS for pos in positions)

        proj = player.projection
        has_pitching_projection = (getattr(proj, "ip", None) or 0) > 0
        has_hitting_projection = (getattr(proj, "ab", None) or 0) > 0

        return (has_pitcher_pos and has_hitter_pos) or (
            has_pitching_projection and has_hitting_projection
        )


def build_player_pool(valued_players_by_id: dict[str, Player]) -> PlayerPool:
    ids_by_value = sorted(
        valued_players_by_id.keys(),
        key=lambda pid: (
            valued_players_by_id[pid].derived_rank
            if valued_players_by_id[pid].derived_rank is not None
            else 10**9,
            valued_players_by_id[pid].name or "",
        ),
    )

    ids_by_adp = sorted(
        valued_players_by_id.keys(),
        key=lambda pid: (
            valued_players_by_id[pid].adp if valued_players_by_id[pid].adp is not None else float("inf"),
            valued_players_by_id[pid].name or "",
        ),
    )

    return PlayerPool(
        players_by_id=valued_players_by_id,
        ids_by_value=ids_by_value,
        ids_by_adp=ids_by_adp,
    )