from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RecommendationMetric:
    label: str
    value: float
    display_value: str
    impact: str  # "high", "medium", "low"


@dataclass
class RecommendationCard:
    player_id: str
    player_name: str
    team: str
    positions: List[str]
    recommendation_rank: int
    draft_score: float
    projected_points: float
    adp: Optional[float]
    tier: Optional[str]
    why_now: str
    why_not_wait: str
    key_metrics: List[RecommendationMetric] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass
class RiskFlag:
    flag_type: str
    severity: str
    title: str
    message: str


@dataclass
class DraftContextSummary:
    current_pick: int
    next_user_pick: Optional[int]
    teams_until_next_pick: int
    roster_snapshot: Dict[str, Any]
    positional_pressure: Dict[str, Any]
    likely_run_positions: List[str]


@dataclass
class PackagedRecommendationResponse:
    headline_recommendation: RecommendationCard
    alternate_recommendations: List[RecommendationCard]
    value_falls: List[RecommendationCard]
    wait_on_it_candidates: List[RecommendationCard]
    risk_flags: List[RiskFlag]
    strategic_explanation: List[str]
    draft_context: DraftContextSummary
    raw_debug: Dict[str, Any] = field(default_factory=dict)