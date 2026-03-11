import importlib
import traceback
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from app.live_draft_routes import router as live_draft_router
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(live_draft_router)

from app.draft_state import DraftState
from app.config import LeagueConfig, ScoringConfig
from app.models import Player, ProjectionLine
from app.normalization import (
    canonicalize_player_name,
    normalize_positions,
    build_player_id,
)
from app.loader import load_projections_csv, get_loader_diagnostics
from app.valuation import (
    derive_hitter_stats,
    derive_pitcher_stats,
    rank_players_by_points,
)
from app.player_pool import build_player_pool
from app.opponent_model import simulate_picks_until_next_turn, analyze_player_availability
from app.recommendation_engine import recommend_for_user
from app.api_contracts import get_packaged_recommendation_from_request
from app.response_packager import get_user_team_profile

# Set this to your CSV path
CSV_PATH = r"c:\Users\dstauffer\Desktop\Fantasy Baseball Draft Assistant\draft-assistant\fantasy-baseball-draft-assistant-backend\Data\Baseball Ranks_2026 Pre-Season.csv"


def build_player(name: str, positions_raw: str, team: str, adp: float, projection: ProjectionLine) -> Player:
    display_name, normalized_name = canonicalize_player_name(name)
    positions = normalize_positions(positions_raw)
    player_id = build_player_id(display_name, positions)

    return Player(
        player_id=player_id,
        name=display_name,
        normalized_name=normalized_name,
        adp=adp,
        positions=positions,
        mlb_team=team,
        projection=projection,
    )


def _is_pitcher(positions) -> bool:
    return any(p in ["SP", "RP", "P"] for p in positions)


def _first_attr(obj, names, default=None):
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _candidate_player_id(candidate_obj):
    if candidate_obj is None:
        return None
    if hasattr(candidate_obj, "player_id"):
        return candidate_obj.player_id
    if isinstance(candidate_obj, str):
        return candidate_obj
    return None


def _fmt_player_line(pool, pid, score_obj=None) -> str:
    if not pid:
        return "None"

    p = pool.get_player(pid)
    score_txt = f", Score={getattr(score_obj, 'score', 0.0):.3f}" if score_obj is not None else ""

    if p is None:
        return f"{pid} (N/A), ADP=N/A, Pts=N/A{score_txt}"

    pts = f"{p.projected_points:.2f}" if p.projected_points is not None else "N/A"
    pos = "/".join(p.positions) if getattr(p, "positions", None) else "N/A"
    return f"{p.name} ({pos}), ADP={p.adp}, Pts={pts}{score_txt}"


def main() -> None:
    scoring = ScoringConfig(
        runs=1.0,
        total_bases=1.0,
        rbi=1.0,
        walks=1.0,
        strikeouts_hitters=-1,
        stolen_bases=1.0,
        home_runs=0,
        innings_pitched=3.0,
        hits_allowed=-1.0,
        earned_runs=-1.0,
        walks_issued=-1.0,
        strikeouts_pitchers=1.0,
        wins=2.0,
        losses=-2.0,
        saves=5.0,
        holds=2.0,
    )

    config = LeagueConfig(
        team_count=12,
        user_draft_slot=4,
        scoring=scoring,
    )

    print("Fantasy Baseball Draft Assistant")
    print(f"Teams: {config.team_count}")
    print(f"User Slot: {config.user_draft_slot}")
    print()

    if CSV_PATH and Path(CSV_PATH).exists():
        print(f"Loading projections from: {CSV_PATH}")
        players_by_id, player_ids_sorted = load_projections_csv(CSV_PATH)
        diagnostics = get_loader_diagnostics()

        print(f"\nDiagnostics:")
        print(f"  Rows read: {diagnostics['rows_read']}")
        print(f"  Players kept: {diagnostics['players_kept']}")
        print(f"  Duplicates removed: {diagnostics['duplicates_removed']}")
        print(f"  Encoding used: {diagnostics['encoding_used']}")

        print("\nValuing all players...")
        players_by_id, player_ids_sorted = rank_players_by_points(players_by_id, config.scoring)

        # Build player pool from valued universe
        pool = build_player_pool(players_by_id)

        draft_state = DraftState.create(config, pool)

        print("\nDraftState Initialized:")
        print(f"  Current Pick: {draft_state.get_current_pick_number()}")
        print(f"  Team On Clock: {draft_state.get_current_team_for_pick()}")
        print(f"  Next User Pick: {draft_state.get_next_user_pick()}")

        opening_picks = [
            "Shohei Ohtani",
            "Aaron Judge",
            "Juan Soto",
            "Paul Skenes",
            "Bobby Witt Jr.",
            "Tarik Skubal",
        ]

        print("\nApplying Opening Picks:")
        for name in opening_picks:
            picked = draft_state.apply_pick_by_name(name)
            print(
                f"  Pick #{draft_state.pick_history[-1].pick_number}: "
                f"Team {draft_state.pick_history[-1].team_id} selected {picked.name}"
            )

        print("\nDraftState After 6 Picks:")
        print(f"  Current Pick: {draft_state.get_current_pick_number()}")
        print(f"  Team On Clock: {draft_state.get_current_team_for_pick()}")
        print(f"  Next User Pick: {draft_state.get_next_user_pick()}")

        simulated_market = simulate_picks_until_next_turn(draft_state)
        print("\nSimulated Picks Until Next User Turn:")
        if simulated_market:
            for sp in simulated_market:
                print(
                    f"  Pick #{sp.pick_number}: Team {sp.team_id} -> {sp.player_name} "
                    f"(ADP={sp.adp}, Rank={sp.derived_rank}) [{sp.reason}]"
                )
        else:
            print("  No picks to simulate before your turn.")

        # Focused debug line: Jose Ramirez
        jose_matches = draft_state.search_available_players("Jose Ramirez", limit=1)
        if jose_matches:
            jose = jose_matches[0]
            jose_report = analyze_player_availability(draft_state, jose.player_id)
            print(
                "\nJosé Ramírez Debug:"
                f" ADP={jose.adp}, survival={jose_report.estimated_survival_score:.2f}, "
                f"likely_taken_before_next={jose_report.likely_taken_before_next}"
            )

        by_value_15 = draft_state.get_available_players_by_value(15)
        by_adp_10 = draft_state.get_available_players_by_adp(10)

        sample_ids: list[str] = []
        if by_value_15:
            sample_ids.append(by_value_15[0].player_id)  # top by value
        if by_adp_10 and by_adp_10[0].player_id not in sample_ids:
            sample_ids.append(by_adp_10[0].player_id)  # top by ADP
        if len(by_value_15) > 5 and by_value_15[5].player_id not in sample_ids:
            sample_ids.append(by_value_15[5].player_id)  # deterministic extra (index 5)
        else:
            for p in by_value_15:
                if p.player_id not in sample_ids:
                    sample_ids.append(p.player_id)
                if len(sample_ids) >= 3:
                    break

        print("\nAvailability Reports:")
        for player_id in sample_ids[:3]:
            report = analyze_player_availability(draft_state, player_id)
            print(
                f"  {report.target_player_name}: "
                f"survival={report.estimated_survival_score:.2f}, "
                f"likely_taken_before_next={report.likely_taken_before_next}"
            )
            print("    Threatened by:")
            if report.threatened_by:
                for t in report.threatened_by:
                    print(
                        f"      Pick #{t.pick_number} Team {t.team_id} -> {t.player_name} "
                        f"(ADP={t.adp}, Rank={t.derived_rank})"
                    )
            else:
                print("      None")

        current_pick = draft_state.get_current_pick_number()
        team_on_clock = draft_state.get_current_team_for_pick()
        user_slot = draft_state.league_config.user_draft_slot
        user_next_pick = draft_state.get_next_user_pick()
        recommendation_context = (
            "On the clock now"
            if team_on_clock == user_slot
            else "Projected recommendation for your next pick"
        )

        print("\nRecommendation Context:")
        print(f"  Current Pick: {current_pick}")
        print(f"  Team On Clock: {team_on_clock}")
        print(f"  User Draft Slot: {user_slot}")
        print(f"  User Next Pick: {user_next_pick}")
        print(f"  Recommendation Context: {recommendation_context}")

        user_profile = get_user_team_profile(draft_state)
        print("\nTEAM CATEGORY PROFILE:")
        print(f"  Power Score: {float(getattr(user_profile, 'power_score', 0.0) or 0.0):.2f}")
        print(f"  Speed Score: {float(getattr(user_profile, 'speed_score', 0.0) or 0.0):.2f}")
        print(f"  Avg Stability: {float(getattr(user_profile, 'average_stability', 0.0) or 0.0):.2f}")
        print(f"  SP Volume: {float(getattr(user_profile, 'sp_volume', 0.0) or 0.0):.2f}")
        print(f"  SP Ratio Stability: {float(getattr(user_profile, 'sp_ratio_stability', 0.0) or 0.0):.2f}")
        print(f"  SP Strikeout Score: {float(getattr(user_profile, 'sp_strikeout_score', 0.0) or 0.0):.2f}")
        print(f"  Save Potential: {float(getattr(user_profile, 'save_potential', 0.0) or 0.0):.2f}")
        print(f"  Risk Index: {float(getattr(user_profile, 'risk_index', 0.0) or 0.0):.2f}")
        notes = getattr(user_profile, "notes", []) or []
        if notes:
            print("  Notes:")
            for note in notes:
                print(f"    - {note}")

        try:
            recommendation_result = recommend_for_user(draft_state, top_n=10)
        except Exception:
            traceback.print_exc()
            raise

        print("\nRecommendation Engine v2:")

        top_candidates = _first_attr(
            recommendation_result,
            ["top_candidates", "candidate_scores", "candidates", "ranked_candidates"],
            [],
        ) or []

        print(f"  Debug: total candidates in recommendation.top_candidates = {len(top_candidates)}")

        rec_obj = _first_attr(
            recommendation_result,
            ["recommendation", "recommended", "top_recommendation", "recommendation_player_id", "recommended_player_id"],
            None,
        )
        alt_obj = _first_attr(
            recommendation_result,
            ["alternative", "alt_recommendation", "alternative_player_id", "alt_player_id"],
            None,
        )
        # REMOVE unused variable:
        # explanation = _first_attr(recommendation_result, ["explanation", "summary"], "")

        # REMOVE redundant pre-assignment block:
        # rec_pid = _candidate_player_id(rec_obj)
        # alt_pid = _candidate_player_id(alt_obj)
        # third_pid = None
        # if len(top_candidates) >= 3 and hasattr(top_candidates[2], "player_id"):
        #     third_pid = top_candidates[2].player_id

        # Build robust top-3 IDs from candidate list first (prevents Third Option = None)
        top_candidate_ids: list[str | None] = []
        for cs in top_candidates:
            pid = _candidate_player_id(cs)
            if pid:
                top_candidate_ids.append(pid)
            if len(top_candidate_ids) >= 3:
                break
        while len(top_candidate_ids) < 3:
            top_candidate_ids.append(None)

        rec_pid = _candidate_player_id(rec_obj) or top_candidate_ids[0]
        alt_pid = _candidate_player_id(alt_obj) or top_candidate_ids[1]
        third_pid = top_candidate_ids[2]

        rec_score_obj = top_candidates[0] if len(top_candidates) > 0 and hasattr(top_candidates[0], "player_id") else None
        alt_score_obj = top_candidates[1] if len(top_candidates) > 1 and hasattr(top_candidates[1], "player_id") else None
        third_score_obj = top_candidates[2] if len(top_candidates) > 2 and hasattr(top_candidates[2], "player_id") else None

        print("\nTop-3 Recommendation Summary:")
        print(f"  Recommended Player: {_fmt_player_line(pool, rec_pid, rec_score_obj)}")
        print(f"  Best Alternative: {_fmt_player_line(pool, alt_pid, alt_score_obj)}")
        print(f"  Third Option: {_fmt_player_line(pool, third_pid, third_score_obj)}")
        explanation_text = getattr(recommendation_result, "explanation", None)
        if explanation_text and str(explanation_text).strip().lower() != "none":
            print(f"  Explanation: {explanation_text}")

        print("\nDRAFT PATH SIMULATION V1")
        path_results = getattr(recommendation_result, "path_results", None) or []
        if path_results:
            for i, pr in enumerate(path_results, start=1):
                print(f"{i}. Opening: {pr.opening_player_name}")
                print(f"   Path: {' -> '.join(pr.path_player_names)}")
                print(f"   Total Path Points: {pr.total_path_projected_points:.1f}")
                print(f"   Total Path Draft Score: {pr.total_path_draft_score:.1f}")
                print(f"   Path Roster Quality: {pr.path_roster_quality:.1f}")
                print(f"   Final Path Score: {pr.final_path_score:.1f}")
                print(f"   Roster After Path: {', '.join(pr.final_roster_snapshot)}")
        else:
            reason = getattr(recommendation_result, "path_results_debug_reason", None) or "Path simulation returned no results."
            print(f"  {reason}")

        print("\nDRAFT PATH SIMULATION V2")
        for i, pr in enumerate(path_results, start=1):
            print(f"{i}. Opening: {pr.opening_player_name}")
            print(f"   Best Branch: {getattr(pr, 'best_branch_name', 'best_value')}")
            bs = getattr(pr, "branch_scores", {}) or {}
            if bs:
                print(
                    "   Branch Scores: "
                    + " | ".join(f"{k}={float(v):.1f}" for k, v in bs.items())
                )
            print(f"   Average Branch Score: {float(getattr(pr, 'average_branch_score', 0.0)):.1f}")
            print(f"   Best Path: {' -> '.join(pr.path_player_names)}")
            print(f"   Total Path Points: {pr.total_path_projected_points:.1f}")
            print(f"   Total Path Draft Score: {pr.total_path_draft_score:.1f}")
            print(f"   Path Roster Quality: {pr.path_roster_quality:.1f}")
            print(f"   Final Path Score: {pr.final_path_score:.1f}")

        print("\nTop 10 Candidate Scores:")
        for idx, cs in enumerate(top_candidates[:10], start=1):
            if not hasattr(cs, "player_id"):
                print(f"  {idx:>2}. <unknown candidate object>")
                continue

            p = pool.get_player(cs.player_id)
            name = p.name if p is not None else cs.player_id
            pos = "/".join(p.positions) if (p is not None and getattr(p, "positions", None)) else "N/A"

            adp_val = float(p.adp) if (p is not None and p.adp is not None) else None
            pts_val = float(p.projected_points) if (p is not None and p.projected_points is not None) else None
            adp_txt = f"{adp_val:.1f}" if adp_val is not None else "N/A"
            pts_txt = f"{pts_val:.2f}" if pts_val is not None else "N/A"

            comp = getattr(cs, "component_scores", {}) or {}
            score = float(getattr(cs, "score", 0.0) or 0.0)

            value_score = float(comp.get("value_score", 0.0) or 0.0)
            urgency = float(comp.get("urgency_bonus", 0.0) or 0.0)
            category_balance_bonus = float(comp.get("category_balance_bonus", 0.0) or 0.0)

            board_pressure_score = float(comp.get("board_pressure_score", 0.0) or 0.0)
            next_turn_loss_risk = float(comp.get("next_turn_loss_risk", 0.0) or 0.0)
            expected_value_loss_if_wait = float(comp.get("expected_value_loss_if_wait", 0.0) or 0.0)
            run_risk_score = float(comp.get("run_risk_score", 0.0) or 0.0)
            market_heat_score = float(comp.get("market_heat_score", 0.0) or 0.0)
            take_now_confidence = float(comp.get("take_now_confidence", 0.0) or 0.0)
            wait_confidence = float(comp.get("wait_confidence", 0.0) or 0.0)

            wait_penalty_mag = abs(float(comp.get("waitability_penalty", 0.0) or 0.0))
            deferrability_penalty = float(comp.get("deferrability_penalty", 0.0) or 0.0)
            roster_bonus = float(comp.get("roster_bonus", 0.0) or 0.0)
            adp_score = float(comp.get("adp_score", 0.0) or 0.0)
            scarcity = float(comp.get("scarcity", 0.0) or 0.0)
            repl = float(comp.get("repl", comp.get("replacement_window_value", 0.0)) or 0.0)
            tier_signal = float(comp.get("tier_cliff_signal", comp.get("tier_cliff_score", 0.0)) or 0.0)
            sp_penalty_mag = abs(float(comp.get("sp_build_penalty", 0.0) or 0.0))
            early_sp_penalty_mag = abs(float(comp.get("early_sp_penalty", 0.0) or 0.0))
            anchor_bonus = float(comp.get("anchor_bonus", 0.0) or 0.0)
            survival = float(comp.get("survival_score", 0.0) or 0.0)

            fallback_raw = (
                getattr(cs, "expected_fallback_player", None)
                or comp.get("expected_fallback_player")
                or comp.get("fallback_player_name")
                or comp.get("fallback_player_id")
            )
            fallback_name = "None"
            if fallback_raw:
                fp = pool.get_player(str(fallback_raw))
                fallback_name = fp.name if fp is not None else str(fallback_raw)

            dropoff_val = float(
                comp.get("position_dropoff", getattr(cs, "position_dropoff", 0.0)) or 0.0
            )
            dropoff_rank = int(
                float(comp.get("position_dropoff_rank", getattr(cs, "position_dropoff_rank", 0)) or 0)
            )
            window_bonus = float(
                comp.get("window_comparison_bonus", getattr(cs, "window_comparison_bonus", 0.0)) or 0.0
            )
            why = getattr(cs, "explanation", None) or comp.get("why") or comp.get("explanation") or ""

            print(
                f"{idx:>4}. {name} ({pos}) | ADP={adp_txt} | Pts={pts_txt} | Score={score:.3f} | "
                f"value={value_score:.3f} | urgency={urgency:.1f} | cat={category_balance_bonus:.2f} | "
                f"board={board_pressure_score:.2f} | loss_if_wait={expected_value_loss_if_wait:.2f} | "
                f"run_risk={run_risk_score:.2f} | heat={market_heat_score:.2f} | "
                f"take_now={take_now_confidence:.2f} | wait={wait_confidence:.2f} | "
                f"WaitPenalty={wait_penalty_mag:.3f} | DeferrabilityPenalty={deferrability_penalty:.3f} | "
                f"roster={roster_bonus:.2f} | adp_score={adp_score:.2f} | scarcity={scarcity:.2f} | "
                f"repl={repl:.3f} | tier={tier_signal:.1f} | SPPenalty={sp_penalty_mag:.3f} | "
                f"EarlySPPenalty={early_sp_penalty_mag:.3f} | anchor={anchor_bonus:.1f} | survival={survival:.1f} | "
                f"ExpectedFallback={fallback_name} | Dropoff={dropoff_val:.2f} | DropoffRank={dropoff_rank} | "
                f"WindowBonus={window_bonus:.2f} | why={why}"
            )

        position_window_map = getattr(recommendation_result, "position_window_map", {}) or {}
        position_dropoff_ranks = getattr(recommendation_result, "position_dropoff_ranks", {}) or {}

        print("\nPOSITION WINDOW COMPARISON")
        if position_window_map:
            ordered = sorted(position_window_map.items(), key=lambda kv: position_dropoff_ranks.get(kv[0], 999))
            for bucket, row in ordered:
                cur_id = row.get("current_best_player_id")
                fb_id = row.get("fallback_player_id")
                cur_p = pool.get_player(cur_id) if cur_id else None
                fb_p = pool.get_player(fb_id) if fb_id else None
                cur_name = cur_p.name if cur_p is not None else (cur_id or "None")
                fb_name = fb_p.name if fb_p is not None else (fb_id or "None")
                drop = float(row.get("dropoff", 0.0) or 0.0)
                rank = position_dropoff_ranks.get(bucket, 0)
                fallback_survival = float(row.get("fallback_survival_probability", 0.0) or 0.0)
                print(
                    f"  - {bucket}: current={cur_name} | fallback={fb_name} | "
                    f"fallback_survival={fallback_survival:.2f} | dropoff={drop:.1f} | rank={rank}"
                )
        else:
            print("  None")

        print("\nCANDIDATE-RELATIVE WINDOW COMPARISON")
        candidate_relative_ranks = getattr(recommendation_result, "candidate_relative_window_ranks", {}) or {}
        if position_window_map and candidate_relative_ranks:
            ordered_rel = sorted(candidate_relative_ranks.items(), key=lambda kv: kv[1])
            for bucket, rank in ordered_rel:
                row = position_window_map.get(bucket, {}) or {}
                cur_id = row.get("current_best_player_id")
                fb_id = row.get("fallback_player_id")
                cur_p = pool.get_player(cur_id) if cur_id else None
                fb_p = pool.get_player(fb_id) if fb_id else None
                cur_name = cur_p.name if cur_p is not None else (cur_id or "None")
                fb_name = fb_p.name if fb_p is not None else (fb_id or "None")
                drop = float(row.get("dropoff", 0.0) or 0.0)
                print(
                    f"  - {bucket}: current={cur_name} | fallback={fb_name} | "
                    f"dropoff={drop:.1f} | rank={rank}"
                )
        else:
            print("  No candidate-relative buckets.")

        likely_taken_next = _first_attr(
            recommendation_result,
            ["likely_taken_before_next_pick", "likely_taken_before_next_pick_ids"],
            [],
        )
        print("\nLikely Taken Before Next Pick:")
        if simulated_market:
            seen_taken = set()
            for sp in simulated_market:
                p = pool.get_player(sp.player_id)
                if p is None or p.player_id in seen_taken:
                    continue
                seen_taken.add(p.player_id)
                print(f"  - {p.name} ({'/'.join(p.positions)})")
        else:
            print("  None")

        print("\nTop 10 Available by Value:")
        for player in draft_state.get_available_players_by_value(10):
            print(
                f"  #{player.derived_rank:>2} | {player.name} ({'/'.join(player.positions)}) "
                f"- {player.mlb_team} - ADP: {player.adp} - Points: {player.projected_points:.2f}"
            )

        print("\nTop 10 Available by ADP:")
        for player in draft_state.get_available_players_by_adp(10):
            print(
                f"  ADP {player.adp} | {player.name} ({'/'.join(player.positions)}) "
                f"- {player.mlb_team} - Rank #{player.derived_rank} - Points: {player.projected_points:.2f}"
            )

        print("\nTeam Rosters (Teams 1-6):")
        for team_id in range(1, 7):
            roster = draft_state.get_team_roster(team_id)
            roster_names = ", ".join(player.name for player in roster) if roster else "None"
            print(f"  Team {team_id}: {roster_names}")

        undone = draft_state.undo_last_pick()
        print("\nUndo Last Pick:")
        if undone:
            print(f"  Undid: {undone.name}")
        else:
            print("  Nothing to undo.")

        print("\nTop 5 Available by Value After Undo:")
        for player in draft_state.get_available_players_by_value(5):
            print(
                f"  #{player.derived_rank:>2} | {player.name} ({'/'.join(player.positions)}) "
                f"- {player.mlb_team} - ADP: {player.adp} - Points: {player.projected_points:.2f}"
            )

        print("\nTop 10 by Value:")
        for i, p in enumerate(pool.get_top_by_value(10), start=1):
            pos_str = "/".join(p.positions)
            adp_str = f"{p.adp:.1f}" if p.adp is not None else "N/A"
            pts_str = f"{p.projected_points:.2f}" if p.projected_points is not None else "N/A"
            print(f"  #{i:>2} | {p.name:<25} | {pos_str:<10} | ADP: {adp_str:<6} | Pts: {pts_str}")

        print("\nTop 10 by ADP:")
        for i, p in enumerate(pool.get_top_by_adp(10), start=1):
            pos_str = "/".join(p.positions)
            adp_str = f"{p.adp:.1f}" if p.adp is not None else "N/A"
            pts_str = f"{p.projected_points:.2f}" if p.projected_points is not None else "N/A"
            print(f"  #{i:>2} | {p.name:<25} | {pos_str:<10} | ADP: {adp_str:<6} | Pts: {pts_str}")

        two_way = pool.get_two_way_players()
        print("\nDetected Two-Way Players:")
        if two_way:
            for p in two_way:
                pos_str = "/".join(p.positions)
                adp_str = f"{p.adp:.1f}" if p.adp is not None else "N/A"
                pts_str = f"{p.projected_points:.2f}" if p.projected_points is not None else "N/A"
                print(f"  {p.name:<25} | {pos_str:<10} | ADP: {adp_str:<6} | Pts: {pts_str}")
        else:
            print("  None detected.")

        print('\nSearch results for "oht":')
        matches = pool.search_by_name("oht", limit=10)
        if matches:
            for p in matches:
                pos_str = "/".join(p.positions)
                adp_str = f"{p.adp:.1f}" if p.adp is not None else "N/A"
                pts_str = f"{p.projected_points:.2f}" if p.projected_points is not None else "N/A"
                print(f"  {p.name:<25} | {pos_str:<10} | ADP: {adp_str:<6} | Pts: {pts_str}")
        else:
            print("  No matches.")

        print(f"\nFirst 5 Players (debug detail):")
        for pid in player_ids_sorted[:5]:
            p = players_by_id[pid]
            pos_str = "/".join(p.positions)
            adp_str = f"{p.adp:.1f}" if p.adp is not None else "N/A"

            print(f"\n  {p.name} ({pos_str}) - {p.mlb_team or 'N/A'} - ADP: {adp_str}")

            if _is_pitcher(p.positions):
                print(f"    Raw Projections:")
                print(f"      IP: {p.projection.ip or 'N/A'}")
                print(f"      W: {p.projection.w or 'N/A'}")
                print(f"      QS: {p.projection.qs or 'N/A'}")
                print(f"      SV: {p.projection.sv or 'N/A'}")
                print(f"      HLD: {p.projection.hld or 'N/A'}")
                print(f"      K: {p.projection.k or 'N/A'}")
                print(f"      K/9: {p.projection.k_per_9 or 'N/A'}")
                print(f"      K/BB: {p.projection.k_per_bb or 'N/A'}")
                print(f"      ERA: {p.projection.era or 'N/A'}")
                print(f"      WHIP: {p.projection.whip or 'N/A'}")

                pitcher_derived = derive_pitcher_stats(p)
                print(f"    Derived Stats:")
                print(f"      BB: {pitcher_derived['BB']:.2f} (source: {pitcher_derived.get('BB_source', 'n/a')})")
                print(f"      H: {pitcher_derived['H']:.2f} (source: {pitcher_derived.get('H_source', 'n/a')})")
                print(f"      ER: {pitcher_derived['ER']:.2f} (source: {pitcher_derived.get('ER_source', 'n/a')})")
                print(f"      Archetype: {pitcher_derived.get('Pitcher_archetype', 'N/A')}")
            else:
                print(f"    Raw Projections:")
                print(f"      R: {p.projection.r or 'N/A'}")
                print(f"      HR: {p.projection.hr or 'N/A'}")
                print(f"      RBI: {p.projection.rbi or 'N/A'}")
                print(f"      TB: {p.projection.tb or 'N/A'}")
                print(f"      SB: {p.projection.sb or 'N/A'}")
                print(f"      AVG: {p.projection.avg or 'N/A'}")
                print(f"      OBP: {p.projection.obp or 'N/A'}")
                print(f"      SLG: {p.projection.slg or 'N/A'}")

                hitter_derived = derive_hitter_stats(p)
                k_rate_display = hitter_derived.get("K_rate_reg", hitter_derived.get("K_rate", 0.0))
                print(f"    Derived Stats:")
                print(f"      BB: {hitter_derived['BB']:.2f} (source: {hitter_derived.get('BB_source', 'n/a')})")
                print(f"      K: {hitter_derived['K']:.2f} (source: {hitter_derived.get('K_source', 'n/a')}, K_rate: {k_rate_display:.3f})")
                print(f"      Contact_skill: {hitter_derived.get('Contact_skill', 0.0):.4f}")
                print(f"      Speed_skill: {hitter_derived.get('Speed_skill', 0.0):.4f}")
                print(f"      Archetype: {hitter_derived.get('Archetype', 'N/A')}")

        ohtani_candidates = [pid for pid, p in players_by_id.items() if "ohtani" in p.normalized_name]
        if ohtani_candidates:
            print(f"\n{'=' * 70}")
            print("SHOHEI OHTANI VALUATION")
            print('=' * 70)

            ohtani = players_by_id[ohtani_candidates[0]]
            print(f"\nName: {ohtani.name}")
            print(f"Positions: {'/'.join(ohtani.positions)}")
            print(f"Team: {ohtani.mlb_team or 'N/A'}")
            print(f"ADP: {ohtani.adp if ohtani.adp is not None else 'N/A'}")
            print(f"Derived Rank: #{ohtani.derived_rank}")
            print(f"Projected Points: {ohtani.projected_points:.2f}")

            hitter_derived = derive_hitter_stats(ohtani)
            pitcher_derived = derive_pitcher_stats(ohtani)
            ohtani_k_rate = hitter_derived.get("K_rate_reg", hitter_derived.get("K_rate", 0.0))

            print(f"\nHitter Derived Stats:")
            print(f"  R: {hitter_derived['R']:.1f}")
            print(f"  TB: {hitter_derived['TB']:.1f}")
            print(f"  RBI: {hitter_derived['RBI']:.1f}")
            print(f"  BB: {hitter_derived['BB']:.1f} (source: {hitter_derived.get('BB_source', 'n/a')})")
            print(f"  K: {hitter_derived['K']:.1f} (source: {hitter_derived.get('K_source', 'n/a')})")
            print(f"  SB: {hitter_derived['SB']:.1f}")
            print(f"  Contact_skill: {hitter_derived.get('Contact_skill', 0.0):.4f}")
            print(f"  Speed_skill: {hitter_derived.get('Speed_skill', 0.0):.4f}")
            print(f"  K_rate: {ohtani_k_rate:.4f}")
            print(f"  Archetype: {hitter_derived.get('Archetype', 'N/A')}")

            print(f"\nPitcher Derived Stats:")
            print(f"  IP: {pitcher_derived['IP']:.1f}")
            print(f"  H: {pitcher_derived['H']:.1f}")
            print(f"  ER: {pitcher_derived['ER']:.1f}")
            print(f"  BB: {pitcher_derived['BB']:.1f} (source: {pitcher_derived['BB_source']})")
            print(f"  K: {pitcher_derived['K']:.1f}")
            print(f"  W: {pitcher_derived['W']:.1f}")
            print(f"  SV: {pitcher_derived['SV']:.1f}")
            print(f"  Archetype: {pitcher_derived.get('Pitcher_archetype', 'N/A')}")

        print()
    else:
        if CSV_PATH:
            print(f"CSV file not found: {CSV_PATH}")
        else:
            print("No CSV path set. Update CSV_PATH in main.py to load projections.")
        print()

    print("=" * 70)
    print("SMOKE TEST")
    print("=" * 70)

    hitter_projection = ProjectionLine(
        gp=145,
        ab=560,
        r=105,
        hr=26,
        rbi=88,
        tb=310,
        sb=14,
        avg=0.292,
        avg_hits=164,
        avg_ab=560,
        obp=0.373,
        obp_times_on_base=235,
        obp_pa=630,
        slg=0.554,
        slg_bases=310,
        slg_ab=560,
        walks_drawn=58,
    )

    pitcher_projection = ProjectionLine(
        gp=32,
        ip=198.0,
        w=15,
        l=7,
        qs=22,
        sv=0,
        hld=0,
        k=224,
        era=3.11,
        era_er=68,
        era_ip=198.0,
        whip=1.05,
        whip_wh=208,
        whip_ip=198.0,
        hits_allowed=154,
        walks_issued=54,
        k_per_9=10.2,
        k_per_bb=4.15,
    )

    hitter = build_player("Mookie Betts", "OF", "LAD", 14.2, hitter_projection)
    pitcher = build_player("Zack Wheeler", "SP", "PHI", 22.5, pitcher_projection)

    print("\nScoring Config:")
    print(config.scoring)

    print("\nHitter Smoke Test Player:")
    print(hitter)
    hitter_derived = derive_hitter_stats(hitter)
    print(f"Derived BB: {hitter_derived['BB']:.1f}")
    print(f"Derived K: {hitter_derived['K']:.1f}")
    print(f"Contact_skill: {hitter_derived['Contact_skill']:.4f}")
    print(f"Speed_skill: {hitter_derived['Speed_skill']:.4f}")
    print(f"K_rate: {hitter_derived['K_rate']:.4f}")

    print("\nPitcher Smoke Test Player:")
    print(pitcher)
    print(f"K/9: {pitcher.projection.k_per_9}")
    print(f"K/BB: {pitcher.projection.k_per_bb}")
    pitcher_derived = derive_pitcher_stats(pitcher)
    print(f"Derived H: {pitcher_derived['H']:.1f}")
    print(f"Derived ER: {pitcher_derived['ER']:.1f}")
    print(f"Derived BB: {pitcher_derived['BB']:.1f} (source: {pitcher_derived['BB_source']})")
    print(f"BB_per_IP: {pitcher_derived['BB_per_IP']:.4f}")
    print(f"Archetype: {pitcher_derived.get('Pitcher_archetype', 'N/A')}")


if __name__ == "__main__":
    main()