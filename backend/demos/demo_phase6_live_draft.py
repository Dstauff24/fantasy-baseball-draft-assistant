from __future__ import annotations

from pathlib import Path

from app.live_draft_service import (
    get_recommendation_for_payload,
    recompute_after_pick,
)


def _print_summary(tag: str, result: dict):
    print(f"\n=== {tag} ===")
    print("ok:", result.get("ok"))
    if not result.get("ok"):
        print("error:", result.get("error"))
        print("details:", result.get("details"))
        return

    state = result.get("state")
    rec = result.get("recommendation")

    if state:
        print("state.current_pick:", state.get("current_pick"))
        print("state.drafted_count:", len(state.get("drafted_player_ids", [])))
        print("state.user_roster_count:", len(state.get("user_roster_player_ids", [])))

    if rec:
        dc = rec.get("draft_context", {})
        roster = dc.get("roster_snapshot", {})
        print("draft_context.current_pick:", dc.get("current_pick"))
        print("draft_context.next_user_pick:", dc.get("next_user_pick"))
        print("draft_context.teams_until_next_pick:", dc.get("teams_until_next_pick"))
        print("roster.count:", roster.get("count"))
        print("roster.players:", roster.get("players", [])[:3])


if __name__ == "__main__":
    projections_csv = Path(
        r"C:\Users\dstauffer\Desktop\Fantasy Baseball Draft Assistant\draft-assistant\fantasy-baseball-draft-assistant-backend\Data\Baseball Ranks_2026 Pre-Season.csv"
    ).resolve()

    state = {
        "current_pick": 45,
        "user_slot": 4,
        "teams": 12,
        "drafted_player_ids": ["shohei-ohtani__util", "aaron-judge__of"],
        "user_roster_player_ids": ["paul-skenes__sp", "austin-riley__3b"],
        "available_player_ids": None,
        "include_debug": False,
        "top_n": 10,
        "projections_csv_path": str(projections_csv),
    }

    # 1) initial recommendation
    initial = get_recommendation_for_payload(state)
    _print_summary("INITIAL RECOMMENDATION", {"ok": initial.get("ok"), "recommendation": initial.get("recommendation"), "state": state, "error": initial.get("error"), "details": initial.get("details")})

    # 2) apply one non-user pick + recompute
    step2 = recompute_after_pick(
        payload=state,
        picked_player_id="julio-rodriguez__of",
        picked_by_slot=5,
        apply_to_user_roster=False,
        advance_pick=True,
    )
    _print_summary("AFTER NON-USER PICK", step2)

    # 3) apply one user pick + recompute
    if step2.get("ok"):
        step3 = recompute_after_pick(
            payload=step2["state"],
            picked_player_id="corbin-burnes__sp",
            picked_by_slot=4,
            apply_to_user_roster=True,
            advance_pick=True,
        )
        _print_summary("AFTER USER PICK", step3)