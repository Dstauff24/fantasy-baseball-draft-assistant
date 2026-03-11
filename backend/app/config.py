from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ScoringConfig:
    # Hitter scoring
    runs: float = 1.0
    total_bases: float = 1.0
    rbi: float = 1.0
    walks: float = 1.0
    strikeouts_hitters: float = -0.5
    stolen_bases: float = 2.0
    home_runs: float = 4.0
    
    # Pitcher scoring
    innings_pitched: float = 3.0
    hits_allowed: float = -1.0
    earned_runs: float = -2.0
    walks_issued: float = -1.0
    strikeouts_pitchers: float = 1.0
    wins: float = 5.0
    losses: float = -5.0
    saves: float = 5.0
    holds: float = 4.0
    
    # Non-core fields (storage only)
    cycle_bonus: float = 0.0
    pickoff_bonus: float = 0.0
    no_hitter_bonus: float = 0.0
    perfect_game_bonus: float = 0.0


@dataclass
class LeagueConfig:
    team_count: int = 12
    user_draft_slot: int = 1
    roster_slots: Optional[Dict[str, int]] = None
    scoring_format: Optional[str] = None
    hitter_pitcher_balance: float = 1.0
    pitcher_aggression: float = 1.0
    closer_aggression: float = 1.0
    catcher_scarcity_boost: float = 1.0
    market_sharpness: float = 1.0
    opponent_need_aggression: float = 1.0
    adp_confidence: float = 1.0
    scoring: ScoringConfig = field(default_factory=ScoringConfig)

    def __post_init__(self) -> None:
        if self.roster_slots is None:
            self.roster_slots = {
                "C": 1,
                "1B": 1,
                "2B": 1,
                "3B": 1,
                "SS": 1,
                "OF": 3,
                "UTIL": 1,
                "SP": 5,
                "RP": 2,
            }