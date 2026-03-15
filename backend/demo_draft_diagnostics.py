from __future__ import annotations

import csv
from pathlib import Path

from app.players_service import load_ranked_player_catalog

OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "draft_diagnostics.csv"


def _fmt(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def main() -> None:
    catalog = load_ranked_player_catalog()

    if not catalog:
        print("No players found in catalog.")
        return

    top_n = 40
    rows = catalog[:top_n]

    headers = [
        "engine_rank",
        "player_name",
        "team",
        "positions",
        "projected_points",
        "adp",
        "adp_rank",
        "derived_rank",
        "vorp",
        "draft_score",
        "survival_probability",
        "take_now_edge",
        "roster_fit_score",
        "team_need_pressure",
        "tier_cliff_score",
    ]

    print("\n=== Top Player Diagnostics (Real Data) ===")
    print(" | ".join(headers))
    print("-" * 220)
    for row in rows:
        line = [
            _fmt(row.get("engine_rank")),
            _fmt(row.get("player_name")),
            _fmt(row.get("team")),
            "/".join(row.get("positions") or []),
            _fmt(row.get("projected_points")),
            _fmt(row.get("adp")),
            _fmt(row.get("adp_rank")),
            _fmt(row.get("derived_rank")),
            _fmt(row.get("vorp")),
            _fmt(row.get("draft_score")),
            _fmt(row.get("survival_probability")),
            _fmt(row.get("take_now_edge")),
            _fmt(row.get("roster_fit_score")),
            _fmt(row.get("team_need_pressure")),
            _fmt(row.get("tier_cliff_score")),
        ]
        print(" | ".join(line))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "player_name",
                "team",
                "positions",
                "projected_points",
                "adp",
                "adp_rank",
                "engine_rank",
                "derived_rank",
                "vorp",
                "draft_score",
                "survival_probability",
                "take_now_edge",
                "roster_fit_score",
                "team_need_pressure",
                "tier_cliff_score",
                "path_score",
            ],
        )
        writer.writeheader()
        for row in catalog:
            writer.writerow(
                {
                    "player_name": row.get("player_name"),
                    "team": row.get("team"),
                    "positions": "/".join(row.get("positions") or []),
                    "projected_points": row.get("projected_points"),
                    "adp": row.get("adp"),
                    "adp_rank": row.get("adp_rank"),
                    "engine_rank": row.get("engine_rank"),
                    "derived_rank": row.get("derived_rank"),
                    "vorp": row.get("vorp"),
                    "draft_score": row.get("draft_score"),
                    "survival_probability": row.get("survival_probability"),
                    "take_now_edge": row.get("take_now_edge"),
                    "roster_fit_score": row.get("roster_fit_score"),
                    "team_need_pressure": row.get("team_need_pressure"),
                    "tier_cliff_score": row.get("tier_cliff_score"),
                    "path_score": row.get("path_score"),
                }
            )

    print(f"\nWrote diagnostics CSV: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
