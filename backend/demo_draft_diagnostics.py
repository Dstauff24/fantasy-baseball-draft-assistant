from __future__ import annotations

import argparse
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


def _global_headers() -> list[str]:
    return [
        "engine_rank",
        "player_name",
        "team",
        "positions",
        "projected_points",
        "adp",
        "adp_rank",
        "derived_rank",
        "value_vs_adp",
        "vorp",
        "cliff_label",
        "cliff_raw_drop",
    ]


def _live_headers() -> list[str]:
    return [
        "engine_rank",
        "player_name",
        "team",
        "positions",
        "projected_points",
        "adp",
        "adp_rank",
        "derived_rank",
        "value_vs_adp",
        "vorp",
        "draft_score",
        "survival_probability",
        "take_now_edge",
        "roster_fit_score",
        "team_need_pressure",
        "tier_cliff_score",
        "sp_cliff_multiplier",
        "cliff_label",
        "cliff_raw_drop",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft diagnostics table")
    parser.add_argument(
        "--mode",
        choices=["global_board", "live_context"],
        default="global_board",
        help="global_board (default) excludes live-context metrics; live_context includes default-context approximations.",
    )
    parser.add_argument("--top", type=int, default=40)
    args = parser.parse_args()

    include_live_context = args.mode == "live_context"
    catalog = load_ranked_player_catalog(include_live_context=include_live_context)

    if not catalog:
        print("No players found in catalog.")
        return

    rows = catalog[: max(1, args.top)]
    headers = _live_headers() if include_live_context else _global_headers()

    print(f"\n=== Top Player Diagnostics ({args.mode}) ===")
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
            _fmt(row.get("value_vs_adp")),
            _fmt(row.get("vorp")),
        ]
        if include_live_context:
            line.extend(
                [
                    _fmt(row.get("draft_score")),
                    _fmt(row.get("survival_probability")),
                    _fmt(row.get("take_now_edge")),
                    _fmt(row.get("roster_fit_score")),
                    _fmt(row.get("team_need_pressure")),
                    _fmt(row.get("tier_cliff_score")),
                    _fmt(row.get("sp_cliff_multiplier")),
                    _fmt(row.get("cliff_label")),
                    _fmt(row.get("cliff_raw_drop")),
                ]
            )
        else:
            line.extend([
                _fmt(row.get("cliff_label")),
                _fmt(row.get("cliff_raw_drop")),
            ])

        print(" | ".join(line))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers + ["metrics_scope", "live_context_note"])
        writer.writeheader()
        for row in catalog:
            row_out = dict(row)
            row_out["positions"] = "/".join(row.get("positions") or [])
            writer.writerow({k: row_out.get(k) for k in headers + ["metrics_scope", "live_context_note"]})

    print(f"\nWrote diagnostics CSV: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
