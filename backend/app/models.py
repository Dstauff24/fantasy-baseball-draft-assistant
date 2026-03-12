from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, List, Any


@dataclass
class ProjectionLine:
    gp: Optional[float] = None
    ab: Optional[float] = None
    r: Optional[float] = None
    hr: Optional[float] = None
    rbi: Optional[float] = None
    tb: Optional[float] = None
    sb: Optional[float] = None
    avg: Optional[float] = None
    avg_hits: Optional[float] = None
    avg_ab: Optional[float] = None
    obp: Optional[float] = None
    obp_times_on_base: Optional[float] = None
    obp_pa: Optional[float] = None
    slg: Optional[float] = None
    slg_bases: Optional[float] = None
    slg_ab: Optional[float] = None
    ip: Optional[float] = None
    w: Optional[float] = None
    l: Optional[float] = None
    qs: Optional[float] = None
    sv: Optional[float] = None
    hld: Optional[float] = None
    k: Optional[float] = None
    era: Optional[float] = None
    era_er: Optional[float] = None
    era_ip: Optional[float] = None
    whip: Optional[float] = None
    whip_wh: Optional[float] = None
    whip_ip: Optional[float] = None
    hits_allowed: Optional[float] = None
    walks_issued: Optional[float] = None
    walks_drawn: Optional[float] = None
    k_per_9: Optional[float] = None
    k_per_bb: Optional[float] = None


@dataclass(frozen=True)
class Player:
    player_id: str
    name: str
    normalized_name: str
    adp: Optional[float]
    positions: Tuple[str, ...]
    mlb_team: Optional[str] = None
    projection: ProjectionLine = field(default_factory=ProjectionLine)
    projected_points: Optional[float] = None
    derived_rank: Optional[int] = None
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class PickRecord:
    pick_number: int
    team_id: int
    player_id: str
    by_user: bool = False


@dataclass
class CandidateScore:
    player_id: str
    score: float
    internal_score: float
    component_scores: Dict[str, Any]
    explanation: str = ""


@dataclass
class RecommendationResult:
    recommendation: object | None
    alternative: object | None
    candidate_scores: list = field(default_factory=list)
    likely_available_next_pick: list = field(default_factory=list)
    likely_taken_before_next_pick: list = field(default_factory=list)
    validation_results: dict = field(default_factory=dict)
    explanation: str = ""