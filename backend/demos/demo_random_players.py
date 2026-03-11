import random

from app.config import LeagueConfig, ScoringConfig
from app.loader import load_projections_csv
from app.valuation import (
    derive_hitter_stats,
    derive_pitcher_stats,
    rank_players_by_points,
)


CSV_PATH = r"c:\Users\dstauffer\Desktop\Fantasy Baseball Draft Assistant\draft-assistant\fantasy-baseball-draft-assistant-backend\Data\Baseball Ranks_2026 Pre-Season.csv"


def _has_hitter_data(player) -> bool:
    """Check if player has meaningful hitter projection data."""
    proj = player.projection
    return any([
        proj.ab and proj.ab > 0,
        proj.r and proj.r > 0,
        proj.hr and proj.hr > 0,
        proj.rbi and proj.rbi > 0,
    ])


def _has_pitcher_data(player) -> bool:
    """Check if player has meaningful pitcher projection data."""
    proj = player.projection
    return any([
        proj.ip and proj.ip > 0,
        proj.w and proj.w > 0,
        proj.k and proj.k > 0,
        proj.sv and proj.sv > 0,
    ])


def main() -> None:
    scoring = ScoringConfig(
        runs=1.0,
        total_bases=1.0,
        rbi=1.0,
        walks=1.0,
        strikeouts_hitters=-1.,
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

    print("=" * 80)
    print("RANDOM PLAYER VALUATION DEMO")
    print("=" * 80)
    print(f"\nLoading: {CSV_PATH}")

    # Load and value players
    players_by_id, _ = load_projections_csv(CSV_PATH)
    print(f"Loaded {len(players_by_id)} players")

    print("Valuing all players...")
    players_by_id, sorted_by_value = rank_players_by_points(players_by_id, config.scoring)
    print("Valuation complete")

    # Sample 10 random players
    all_player_ids = list(players_by_id.keys())
    sample_size = min(10, len(all_player_ids))
    sampled_ids = random.sample(all_player_ids, sample_size)

    print(f"\nShowing {sample_size} randomly selected players:\n")

    for idx, pid in enumerate(sampled_ids, start=1):
        player = players_by_id[pid]
        proj = player.projection

        print("=" * 80)
        print(f"PLAYER {idx}/{sample_size}")
        print("=" * 80)
        print(f"Name: {player.name}")
        print(f"Positions: {'/'.join(player.positions)}")
        print(f"Team: {player.mlb_team or 'N/A'}")
        print(f"ADP: {player.adp if player.adp is not None else 'N/A'}")
        print(f"Derived Rank: #{player.derived_rank}")
        print(f"Projected Fantasy Points: {player.projected_points:.2f}")

        # Raw projections summary
        print(f"\n--- RAW UPLOADED PROJECTIONS ---")
        
        if _has_hitter_data(player):
            print(f"Hitter Projections:")
            print(f"  GP: {proj.gp or 'N/A'}")
            print(f"  AB: {proj.ab or 'N/A'}")
            print(f"  R: {proj.r or 'N/A'}")
            print(f"  HR: {proj.hr or 'N/A'}")
            print(f"  RBI: {proj.rbi or 'N/A'}")
            print(f"  TB: {proj.tb or 'N/A'}")
            print(f"  SB: {proj.sb or 'N/A'}")
            print(f"  AVG: {proj.avg or 'N/A'}")
            print(f"  OBP: {proj.obp or 'N/A'}")
            print(f"  SLG: {proj.slg or 'N/A'}")

        if _has_pitcher_data(player):
            print(f"Pitcher Projections:")
            print(f"  IP: {proj.ip or 'N/A'}")
            print(f"  W: {proj.w or 'N/A'}")
            print(f"  L: {proj.l or 'N/A'}")
            print(f"  QS: {proj.qs or 'N/A'}")
            print(f"  SV: {proj.sv or 'N/A'}")
            print(f"  HLD: {proj.hld or 'N/A'}")
            print(f"  K: {proj.k or 'N/A'}")
            print(f"  K/9: {proj.k_per_9 or 'N/A'}")
            print(f"  K/BB: {proj.k_per_bb or 'N/A'}")
            print(f"  ERA: {proj.era or 'N/A'}")
            print(f"  WHIP: {proj.whip or 'N/A'}")

        # Derived stats
        print(f"\n--- DERIVED SCORING STATS ---")

        if _has_hitter_data(player):
            hitter_derived = derive_hitter_stats(player)
            print(f"Hitter Derived:")
            print(f"  R: {hitter_derived['R']:.2f}")
            print(f"  TB: {hitter_derived['TB']:.2f}")
            print(f"  RBI: {hitter_derived['RBI']:.2f}")
            print(f"  BB: {hitter_derived['BB']:.2f}")
            print(f"  K: {hitter_derived['K']:.2f}")
            print(f"  SB: {hitter_derived['SB']:.2f}")
            print(f"\n  Hitter Derivation Details:")
            print(f"    Contact_skill: {hitter_derived['Contact_skill']:.4f}")
            print(f"    Speed_skill: {hitter_derived['Speed_skill']:.4f}")
            print(f"    K_rate: {hitter_derived['K_rate']:.4f}")
            print(f"    PA_est: {hitter_derived['PA_est']:.2f}")

        if _has_pitcher_data(player):
            pitcher_derived = derive_pitcher_stats(player)
            print(f"Pitcher Derived:")
            print(f"  IP: {pitcher_derived['IP']:.2f}")
            print(f"  H: {pitcher_derived['H']:.2f}")
            print(f"  ER: {pitcher_derived['ER']:.2f}")
            print(f"  BB: {pitcher_derived['BB']:.2f}")
            print(f"  K: {pitcher_derived['K']:.2f}")
            print(f"  W: {pitcher_derived['W']:.2f}")
            print(f"  L: {pitcher_derived['L']:.2f}")
            print(f"  SV: {pitcher_derived['SV']:.2f}")
            print(f"  HD: {pitcher_derived['HD']:.2f}")
            print(f"\n  Pitcher Derivation Details:")
            print(f"    BB source: {pitcher_derived['BB_source']}")
            print(f"    BB_per_IP: {pitcher_derived['BB_per_IP']:.4f}")
            print(f"    K_per_IP: {pitcher_derived['K_per_IP']:.4f}")
            if pitcher_derived.get('K_per_9_input', 0.0) > 0:
                print(f"    K/9 input: {pitcher_derived['K_per_9_input']:.2f}")
            if pitcher_derived.get('K_per_BB_input', 0.0) > 0:
                print(f"    K/BB input: {pitcher_derived['K_per_BB_input']:.2f}")
            if pitcher_derived.get('BB_per_9_input', 0.0) > 0:
                print(f"    BB/9 input: {pitcher_derived['BB_per_9_input']:.2f}")

        print()

    print("=" * 80)
    print("END OF DEMO")
    print("=" * 80)


if __name__ == "__main__":
    main()