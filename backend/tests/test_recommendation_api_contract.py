import unittest
from unittest.mock import patch

from app.api_contracts import get_packaged_recommendation_from_request


class DemoDraftState:
    def __init__(self):
        self.current_pick = None
        self.user_slot = 1
        self.teams = 12
        self.drafted_player_ids = []
        self.user_roster_player_ids = []
        self.available_player_ids = []

    def set_current_pick_number(self, value): self.current_pick = int(value)
    def set_user_slot(self, value): self.user_slot = int(value)
    def set_teams(self, value): self.teams = int(value)
    def mark_player_drafted(self, pid): self.drafted_player_ids.append(pid)
    def add_user_roster_player(self, pid): self.user_roster_player_ids.append(pid)
    def set_available_player_ids(self, ids): self.available_player_ids = list(ids)


def demo_factory(_: dict) -> DemoDraftState:
    return DemoDraftState()


class RecommendationApiContractTests(unittest.TestCase):
    def test_invalid_missing_current_pick(self):
        result = get_packaged_recommendation_from_request({"teams": 12}, draft_state_factory=demo_factory)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Invalid recommendation request")

    def test_invalid_bad_drafted_list(self):
        payload = {"current_pick": 45, "drafted_player_ids": "not-a-list"}
        result = get_packaged_recommendation_from_request(payload, draft_state_factory=demo_factory)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Invalid recommendation request")

    @patch("app.api_contracts.recommend_for_user_packaged_dict")
    def test_success_json_safe_and_debug_passthrough(self, mock_packaged):
        mock_packaged.return_value = {
            "headline_recommendation": {"player_id": "x"},
            "alternate_recommendations": [],
            "value_falls": [],
            "wait_on_it_candidates": [],
            "risk_flags": [],
            "strategic_explanation": [],
            "draft_context": {},
            "raw_debug": {"enabled": True},
        }

        payload = {
            "current_pick": 45,
            "user_slot": 4,
            "teams": 12,
            "drafted_player_ids": [],
            "user_roster_player_ids": [],
            "include_debug": True,
        }
        result = get_packaged_recommendation_from_request(payload, draft_state_factory=demo_factory)
        self.assertTrue(result["ok"])
        self.assertIn("recommendation", result)
        self.assertTrue(result["recommendation"]["raw_debug"]["enabled"])


if __name__ == "__main__":
    unittest.main()