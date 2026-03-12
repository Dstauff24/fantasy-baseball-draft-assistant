from types import SimpleNamespace

from app.response_packager import build_draft_context_summary


class DummyDraftState:
    def __init__(self, current_pick: int, user_slot: int, team_count: int):
        self.current_pick = current_pick
        self.user_slot = user_slot
        self.team_rosters = {i: [] for i in range(1, team_count + 1)}

    def get_current_pick_number(self) -> int:
        return self.current_pick

    def get_next_user_pick(self) -> int | None:
        current_pick = self.current_pick
        user_slot = self.user_slot
        team_count = len(self.team_rosters)

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

    def get_user_roster(self):
        return []


def test_snake_pick_math_user_on_clock_round_4_reverse():
    draft_state = DummyDraftState(current_pick=45, user_slot=4, team_count=12)

    summary = build_draft_context_summary(
        draft_state=draft_state,
        team_context={},
        opponent_model=None,
    )

    assert summary.current_pick == 45
    assert summary.next_user_pick == 52
    assert summary.teams_until_next_pick == 6