import json
from types import SimpleNamespace

from app.response_packager import package_recommendation_response
from app.serializers import to_dict


class _DemoDraftState:
    def get_current_pick_number(self):
        return 45

    def get_next_user_pick(self):
        return 52

    def get_user_roster(self):
        return [
            SimpleNamespace(name="Paul Skenes", positions=("SP",)),
            SimpleNamespace(name="Austin Riley", positions=("3B",)),
        ]


def _mock_scored_player(
    player_id: str,
    name: str,
    team: str,
    positions: list,
    score: float,
    survival: float,
    tier_cliff: float,
    fall: float,
    adp: float = None,
    vorp: float = 10.0,
    fit: float = 0.5,
    board: float = 2.4,
):
    """Create a fully metadata-rich mock candidate."""
    return SimpleNamespace(
        player_id=player_id,
        player_name=name,
        team=team,
        positions=positions,
        primary_position=positions[0] if positions else "UTIL",
        draft_score=score,
        projected_points=400.0 + score,
        adp=adp,
        tier=None,
        fall_bonus=fall,
        reach_penalty=0.0,
        component_scores={
            "projected_points": 400.0 + score,
            "projected_points_score": 400.0 + score,
            "vorp": vorp,
            "vorp_score": vorp,
            "tier_cliff_score": tier_cliff,
            "survival_probability": survival,
            "team_need_pressure": 1.0 if fit > 0.5 else 0.3,
            "roster_fit_score": fit,
            "take_now_edge": 12.0 if survival < 0.4 else 6.0,
            "board_pressure_score": board,
            "expected_value_loss_if_wait": 2.0 if survival < 0.4 else 0.3,
            "fall_bonus": fall,
            "reach_penalty": 0.0,
            "team": team,
            "positions": positions,
            "player_name": name,
            "primary_position": positions[0] if positions else "UTIL",
            "adp": adp,
            "tier": None,
        },
        explanation="demo candidate",
        metadata_source_notes=["demo"],
    )


if __name__ == "__main__":
    draft_state = _DemoDraftState()
    
    # Build diverse candidate pool to demonstrate guaranteed wait-on-it
    scored_players = [
        # Headline: high urgency + low survival
        _mock_scored_player(
            "julio-rodriguez__of",
            "Julio Rodríguez",
            "SEA",
            ["OF"],
            52.1,
            0.25,
            3.2,
            0.0,
            adp=24.5,
            vorp=14.0,
            fit=1.8,
            board=6.2,
        ),
        # Alternate: strong urgency + moderate survival
        _mock_scored_player(
            "gunnar-henderson__ss",
            "Gunnar Henderson",
            "BAL",
            ["SS"],
            47.4,
            0.45,
            2.8,
            0.0,
            adp=24.9,
            vorp=12.5,
            fit=1.5,
            board=5.1,
        ),
        # Value fall: lower urgency + strong value/vorp
        _mock_scored_player(
            "yordan-alvarez__dh",
            "Yordan Alvarez",
            "HOU",
            ["OF", "DH"],
            39.0,
            0.82,
            1.2,
            1.3,
            adp=36.5,
            vorp=11.0,
            fit=0.8,
            board=3.2,
        ),
        # Wait-on-it PRIMARY: high survival + good score + low board
        _mock_scored_player(
            "brent-rooker__of",
            "Brent Rooker",
            "TB",
            ["OF", "DH"],
            34.2,
            0.88,
            0.5,
            2.1,
            adp=49.6,
            vorp=9.5,
            fit=0.6,
            board=2.8,
        ),
        # Wait-on-it SECONDARY: high survival + acceptable score + very low board
        _mock_scored_player(
            "mitch-garver__c",
            "Mitch Garver",
            "COL",
            ["C"],
            32.5,
            0.80,
            1.8,
            0.3,
            adp=52.1,
            vorp=8.2,
            fit=1.2,
            board=2.1,
        ),
        # Pool filler: lower score, moderate survival (does not qualify for wait)
        _mock_scored_player(
            "kyle-schwarber__of",
            "Kyle Schwarber",
            "PHI",
            ["OF", "1B", "DH"],
            28.5,
            0.65,
            0.8,
            0.9,
            adp=42.3,
            vorp=10.1,
            fit=0.7,
            board=4.2,
        ),
    ]

    packaged = package_recommendation_response(
        scored_players=scored_players,
        draft_state=draft_state,
        team_context={},
        include_debug=True,
    )
    
    response_dict = to_dict(packaged)
    print(json.dumps(response_dict, indent=2))
    
    # Print bucket summary with qualification details
    print("\n=== BUCKET ASSIGNMENT SUMMARY ===")
    print(f"\nHeadline ({len(packaged.headline_recommendation.__class__.__name__)} card):")
    print(f"  {packaged.headline_recommendation.player_name} ({packaged.headline_recommendation.team})")
    
    print(f"\nAlternates ({len(packaged.alternate_recommendations)} cards):")
    for p in packaged.alternate_recommendations:
        print(f"  {p.player_name} ({p.team})")
    
    print(f"\nValue Falls ({len(packaged.value_falls)} cards):")
    for p in packaged.value_falls:
        print(f"  {p.player_name} ({p.team})")
    
    print(f"\nWait-on-it ({len(packaged.wait_on_it_candidates)} cards):")
    for p in packaged.wait_on_it_candidates:
        print(f"  {p.player_name} ({p.team})")
    
    # Print qualification details from debug
    if packaged.raw_debug:
        print(f"\n=== WAIT QUALIFICATION NOTES ===")
        for candidate in packaged.raw_debug.get("top_candidate_scores", []):
            is_qualified = candidate.get("is_wait_qualified", False)
            print(f"{candidate['player_name']}: qualified={is_qualified}, survival={candidate['survival_probability']:.2f}, board={candidate['board_pressure_score']:.1f}, draft_score={candidate['draft_score']:.1f}")
    
    print(f"\n=== HEADLINE EXPLANATION ===")
    print(f"Why Now: {packaged.headline_recommendation.why_now}")
    print(f"Why Not Wait: {packaged.headline_recommendation.why_not_wait}")
    
    if packaged.wait_on_it_candidates:
        print(f"\n=== FIRST WAIT-ON-IT EXPLANATION ===")
        print(f"Why Now: {packaged.wait_on_it_candidates[0].why_now}")
        print(f"Why Not Wait: {packaged.wait_on_it_candidates[0].why_not_wait}")