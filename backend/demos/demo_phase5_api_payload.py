import json
from pathlib import Path

from app.api_contracts import get_packaged_recommendation_from_request


if __name__ == "__main__":
    projections_csv = Path(
        r"C:\Users\dstauffer\Desktop\Fantasy Baseball Draft Assistant\draft-assistant\fantasy-baseball-draft-assistant-backend\Data\Baseball Ranks_2026 Pre-Season.csv"
    ).resolve()

    payload = {
        "current_pick": 45,
        "user_slot": 4,
        "teams": 12,
        "drafted_player_ids": ["shohei-ohtani__util", "aaron-judge__of"],
        "user_roster_player_ids": ["paul-skenes__sp", "austin-riley__3b"],
        "available_player_ids": None,
        "include_debug": True,
        "top_n": 10,
        "projections_csv_path": str(projections_csv),
    }

    result = get_packaged_recommendation_from_request(payload)

    if result.get("ok"):
        print("=== SUCCESS ===\n")
        rec = result.get("recommendation", {})
        dc = rec.get("draft_context", {})
        roster = dc.get("roster_snapshot", {})

        print("CONSISTENCY CHECKS:")
        print(f"  Request current_pick:        {payload['current_pick']}")
        print(f"  Response current_pick:       {dc.get('current_pick')}")
        print(f"  Match: {payload['current_pick'] == dc.get('current_pick')} ✓" if payload['current_pick'] == dc.get('current_pick') else "  Match: False ✗")

        print(f"\n  Request user_roster_count:   {len(payload['user_roster_player_ids'])}")
        print(f"  Response roster_count:       {roster.get('count', 0)}")
        print(f"  Match: {len(payload['user_roster_player_ids']) == roster.get('count')} ✓" if len(payload['user_roster_player_ids']) == roster.get('count') else "  Match: False ✗")

        print(f"\n  Response roster players:     {roster.get('players', [])}")
        print(f"  Response roster positions:   {roster.get('positions', [])}")
        print(f"\n  Response next_user_pick:     {dc.get('next_user_pick')}")
        print(f"  Response teams_until_next:   {dc.get('teams_until_next_pick')}")

    else:
        print("=== FAILURE ===")
        print(f"error:   {result.get('error')}")
        print(f"details: {result.get('details')}")
        if result.get("debug"):
            print("\nDebug trace:")
            for ev in result["debug"].get("events", []):
                print(f"  [{ev['stage']}] {ev['message']}")

    print("\n=== INVALID REQUEST TEST ===")
    bad = get_packaged_recommendation_from_request({"teams": 12})
    print("error  :", bad.get("error"))
    print("details:", bad.get("details"))