from copy import deepcopy
from dataclasses import dataclass

from app.models import Player, PickRecord
from app.config import LeagueConfig
from app.player_pool import PlayerPool


def get_team_for_pick(pick_number: int, team_count: int) -> int:
    if pick_number < 1:
        raise ValueError("pick_number must be >= 1")
    if team_count < 1:
        raise ValueError("team_count must be >= 1")

    zero_based_pick = pick_number - 1
    round_index = zero_based_pick // team_count
    index_in_round = zero_based_pick % team_count

    # Even round_index (0,2,4...) goes 1 -> team_count
    if round_index % 2 == 0:
        return index_in_round + 1

    # Odd round_index (1,3,5...) goes team_count -> 1
    return team_count - index_in_round


@dataclass
class DraftState:
    league_config: LeagueConfig
    player_pool: PlayerPool
    drafted_player_ids: list[str]
    drafted_player_id_set: set[str]
    available_player_ids: list[str]
    available_player_id_set: set[str]
    team_rosters: dict[int, list[str]]
    pick_history: list[PickRecord]

    @classmethod
    def create(cls, league_config: LeagueConfig, player_pool: PlayerPool) -> "DraftState":
        available_ids = list(player_pool.ids_by_value)
        team_rosters = {team_id: [] for team_id in range(1, league_config.team_count + 1)}

        return cls(
            league_config=league_config,
            player_pool=player_pool,
            drafted_player_ids=[],
            drafted_player_id_set=set(),
            available_player_ids=available_ids,
            available_player_id_set=set(available_ids),
            team_rosters=team_rosters,
            pick_history=[],
        )

    def get_current_pick_number(self) -> int:
        current_pick = getattr(self, "current_pick", None)
        if current_pick is None:
            current_pick = getattr(self, "current_pick_number", None)
        return int(current_pick or 1)

    def get_current_team_for_pick(self) -> int:
        return get_team_for_pick(self.get_current_pick_number(), self.league_config.team_count)

    def get_next_user_pick(self) -> int | None:
        """
        Return the next future pick number for the user in a snake draft.
        If the user is currently on the clock, return the user's next turn,
        not the current pick.
        """
        current_pick = self.get_current_pick_number()
        user_slot = getattr(self, "user_slot", None)
        if user_slot is None:
            user_slot = getattr(getattr(self, "league_config", None), "user_draft_slot", None)

        team_count = len(getattr(self, "team_rosters", {}) or {})
        if not team_count:
            team_count = getattr(getattr(self, "league_config", None), "team_count", 0)

        if not user_slot or not team_count:
            return None

        def slot_for_pick(pick_number: int) -> int:
            round_index = (pick_number - 1) // team_count
            pick_in_round = ((pick_number - 1) % team_count) + 1
            if round_index % 2 == 0:
                return pick_in_round
            return team_count - pick_in_round + 1

        pick = current_pick + 1
        limit = current_pick + (team_count * 2) + 1
        while pick <= limit:
            if slot_for_pick(pick) == user_slot:
                return pick
            pick += 1

        return None

    def is_drafted(self, player_id: str) -> bool:
        return player_id in self.drafted_player_id_set

    def get_available_players_by_value(self, n: int | None = None) -> list[Player]:
        ids = self.available_player_ids if n is None else self.available_player_ids[:n]
        players: list[Player] = []
        for player_id in ids:
            player = self.player_pool.get_player(player_id)
            if player is not None:
                players.append(player)
        return players

    def get_available_players_by_adp(self, n: int | None = None) -> list[Player]:
        players: list[Player] = []
        for player_id in self.available_player_ids:
            player = self.player_pool.get_player(player_id)
            if player is not None:
                players.append(player)

        players.sort(key=lambda p: (float("inf") if p.adp is None else p.adp, p.name))
        return players if n is None else players[:n]

    def get_user_roster(self) -> list[Player]:
        """
        Return the user's roster as a list of Player objects.
        Resolves player_id strings to Player objects via player_pool.
        """
        user_slot = getattr(self, "user_slot", 1)
        team_rosters = getattr(self, "team_rosters", {})
        player_pool = getattr(self, "player_pool", None)

        user_roster_ids = team_rosters.get(user_slot, [])
        roster = []

        for player_id in user_roster_ids:
            if not isinstance(player_id, str):
                continue

            player = None

            # Try players_by_id dict
            if player_pool and hasattr(player_pool, "players_by_id"):
                player = player_pool.players_by_id.get(player_id)

            # Try get_player method
            if not player and player_pool and callable(getattr(player_pool, "get_player", None)):
                player = player_pool.get_player(player_id)

            if player:
                roster.append(player)

        return roster

    def get_team_roster(self, team_id: int) -> list[Player]:
        roster_ids = self.team_rosters.get(team_id, [])
        players: list[Player] = []
        for player_id in roster_ids:
            player = self.player_pool.get_player(player_id)
            if player is not None:
                players.append(player)
        return players

    def apply_pick_by_id(self, player_id: str, by_user: bool = False) -> Player:
        pick_number = self.get_current_pick_number()
        team_id = get_team_for_pick(pick_number, self.league_config.team_count)

        if by_user and team_id != self.league_config.user_draft_slot:
            raise ValueError(
                f"Not user's turn. Current team {team_id}, user slot {self.league_config.user_draft_slot}."
            )

        player = self.player_pool.get_player(player_id)
        if player is None:
            raise ValueError(f"Unknown player_id: {player_id}")

        if self.is_drafted(player_id):
            raise ValueError(f"Player already drafted: {player.name}")

        if player_id not in self.available_player_id_set:
            raise ValueError(f"Player not available: {player.name}")

        self.available_player_id_set.remove(player_id)
        self.available_player_ids.remove(player_id)

        self.drafted_player_id_set.add(player_id)
        self.drafted_player_ids.append(player_id)

        self.team_rosters[team_id].append(player_id)

        self.pick_history.append(
            PickRecord(
                pick_number=pick_number,
                team_id=team_id,
                player_id=player_id,
                by_user=by_user,
            )
        )

        return player

    def apply_pick_by_name(self, player_name: str, by_user: bool = False) -> Player:
        normalized = player_name.strip().lower()

        # Prefer exact match among available players first.
        for player_id in self.available_player_ids:
            player = self.player_pool.get_player(player_id)
            if player is None:
                continue
            if player.name.strip().lower() == normalized:
                return self.apply_pick_by_id(player.player_id, by_user=by_user)

        # Fallback to fuzzy search.
        matches = self.player_pool.search_by_name(player_name, limit=10)
        if not matches:
            raise ValueError(f"No player found matching: {player_name}")

        available_matches = [p for p in matches if not self.is_drafted(p.player_id)]
        if not available_matches:
            raise ValueError(f"No available player found matching: {player_name}")

        return self.apply_pick_by_id(available_matches[0].player_id, by_user=by_user)

    def apply_pick_by_player(self, player: Player, by_user: bool = False) -> Player:
        return self.apply_pick_by_id(player.player_id, by_user=by_user)

    def undo_last_pick(self) -> Player | None:
        if not self.pick_history:
            return None

        last_pick = self.pick_history.pop()
        player_id = last_pick.player_id
        team_id = last_pick.team_id

        self.drafted_player_id_set.discard(player_id)

        if player_id in self.drafted_player_ids:
            self.drafted_player_ids.remove(player_id)

        if team_id in self.team_rosters and player_id in self.team_rosters[team_id]:
            self.team_rosters[team_id].remove(player_id)

        self.available_player_id_set.add(player_id)
        self.available_player_ids = [
            pid for pid in self.player_pool.ids_by_value if pid in self.available_player_id_set
        ]

        return self.player_pool.get_player(player_id)

    def search_available_players(self, query: str, limit: int = 10) -> list[Player]:
        matches = self.player_pool.search_by_name(query, limit=limit * 3)
        available: list[Player] = []
        for player in matches:
            if not self.is_drafted(player.player_id):
                available.append(player)
            if len(available) >= limit:
                break
        return available

    def remaining_pick_count(self) -> int:
        return len(self.available_player_ids)

    def clone(self) -> "DraftState":
        return deepcopy(self)