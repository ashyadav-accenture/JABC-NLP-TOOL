#!/usr/bin/env python3
"""
JABC NLP-Based Sentiment & Brand Health Matrix System
======================================================

Reads a directory of JABC educator/stakeholder interview Excel files, runs
local (no external LLM API) NLP + sentiment + rule-based analysis, scores
each respondent across six Brand Health Themes, classifies each respondent
into one of four Brand Personas, and exports:

  1. respondent_brand_health_scores.csv / .xlsx  - respondent-level scores
  2. respondent_theme_evidence.csv / .xlsx       - evidence audit trail
  3. brand_health_matrix.csv / .xlsx             - PRIMARY OUTPUT
     (the .xlsx also includes a "Persona Members" sheet listing which
     respondents fall into which persona)
  4. persona_roster.csv                          - same roster, standalone
  5. persona_validation.csv                      - vs. original sheet labels
  6. brand_health_matrix_heatmap.png             - optional, plus a
     brand_health_score_scale.png key for the face scale
  7. factor_circumplex.png                       - optional, with a
     factor_circumplex_positions.csv sidecar explaining each circle
  8. jabc_charts.pptx                            - optional, every chart
     redrawn as editable PowerPoint shapes rather than embedded images

Usage:
    python jabc_brand_health_analyzer.py --input_dir ./interviews --output_dir ./outputs

Optional:
    --generate_heatmap true
    --manual_review_threshold 0.55
    --include_reference_sheets false
    --config_dir ./config
    --calibration_csv ./human_review.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from jabc.calibration import run_calibration
from jabc.circumplex import layout_dataframe, resolve_layout, write_driver_circumplex
from jabc.config_loader import Config
from jabc.export import (
    evidence_dataframe,
    persona_roster_dataframe,
    respondent_scores_dataframe,
    validation_dataframe,
    write_csv,
    write_dataframe_excel,
    write_heatmap,
    write_score_scale,
    write_matrix_excel,
)
from jabc.matrix import build_brand_health_matrix
from jabc.opportunities import (
    load_opportunities,
    opportunity_dataframe,
    unnamed_respondents,
)
from jabc.pipeline import run_pipeline
from jabc.pptx_export import write_chart_deck
from jabc.reports import write_circumplex_report, write_opportunity_report
from jabc.theme_priority import write_theme_priority_matrix

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("jabc_brand_health_analyzer")


def _str2bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="JABC NLP-Based Sentiment & Brand Health Matrix System",
    )
    parser.add_argument("--input_dir", required=True, help="Directory containing .xlsx interview files")
    parser.add_argument("--output_dir", required=True, help="Directory to write output files to")
    parser.add_argument("--config_dir", default=str(Path(__file__).parent / "config"),
                         help="Directory containing the YAML configuration files")
    parser.add_argument("--generate_heatmap", default="false", help="true|false")
    parser.add_argument("--generate_circumplex", default="false", help="true|false")
    parser.add_argument("--generate_priority_matrix", default="false", help="true|false")
    parser.add_argument("--manual_review_threshold", type=float, default=None,
                         help="Override persona_rules.yaml's manual_review_threshold")
    parser.add_argument("--include_reference_sheets", default="false", help="true|false")
    parser.add_argument("--generate_reports", default="false",
                         help="true|false — two independent evidence workbooks, one per chart")
    parser.add_argument("--generate_deck", default="false",
                         help="true|false — one .pptx holding every chart as editable shapes")
    parser.add_argument("--calibration_csv", default=None,
                         help="Optional path to a human-review CSV to run the calibration workflow")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading configuration from %s", args.config_dir)
    config = Config.load(args.config_dir)

    if args.manual_review_threshold is not None:
        config.persona_rules["manual_review_threshold"] = args.manual_review_threshold

    include_reference_sheets = _str2bool(args.include_reference_sheets)
    generate_heatmap = _str2bool(args.generate_heatmap)
    generate_circumplex = _str2bool(args.generate_circumplex)
    generate_priority_matrix = _str2bool(args.generate_priority_matrix)
    generate_reports = _str2bool(args.generate_reports)
    generate_deck = _str2bool(args.generate_deck)

    logger.info("Running pipeline over input directory: %s", args.input_dir)
    profiles = run_pipeline(args.input_dir, config, include_reference_sheets=include_reference_sheets)
    logger.info("Extracted %d respondent profile(s).", len(profiles))

    if not profiles:
        logger.warning(
            "No respondents were extracted. Check that --input_dir contains .xlsx files "
            "with a completed 'Answer' column, and re-run with a lower-level logger if needed."
        )

    # --- 1. Respondent-level scores ---
    respondent_df = respondent_scores_dataframe(profiles, config=config)
    write_csv(respondent_df, output_dir / "respondent_brand_health_scores.csv")
    write_dataframe_excel(respondent_df, output_dir / "respondent_brand_health_scores.xlsx",
                           sheet_name="Respondent Scores")

    # --- 2. Evidence table ---
    evidence_df = evidence_dataframe(profiles)
    write_csv(evidence_df, output_dir / "respondent_theme_evidence.csv")
    write_dataframe_excel(evidence_df, output_dir / "respondent_theme_evidence.xlsx",
                           sheet_name="Evidence")

    # --- 3. Brand Health Matrix (PRIMARY OUTPUT) ---
    matrix_df = build_brand_health_matrix(profiles, config=config)
    write_csv(matrix_df, output_dir / "brand_health_matrix.csv")

    # --- 3b. Persona roster: which respondents fall into which persona ---
    roster_df = persona_roster_dataframe(profiles, config=config)
    write_csv(roster_df, output_dir / "persona_roster.csv")
    write_matrix_excel(matrix_df, output_dir / "brand_health_matrix.xlsx", roster_df=roster_df,
                        config=config)

    # --- 4. Persona validation table (diagnostic only, spec section 33) ---
    validation_df = validation_dataframe(profiles, config=config)
    write_csv(validation_df, output_dir / "persona_validation.csv")

    # --- 5. Optional heatmap ---
    if generate_heatmap:
        written = write_heatmap(matrix_df, output_dir / "brand_health_matrix_heatmap.png", config=config)
        if written:
            logger.info("Wrote optional heatmap to brand_health_matrix_heatmap.png")
        # The score-scale key is a separate asset: it never changes with the
        # data, so it is placed once rather than redrawn under every chart.
        if write_score_scale(output_dir / "brand_health_score_scale.png"):
            logger.info("Wrote score scale key to brand_health_score_scale.png")

    # --- 5b. Optional motivator/barrier sentiment circumplex ---
    if generate_circumplex:
        written = write_driver_circumplex(
            profiles, output_dir / "factor_circumplex.png", config,
        )
        if written:
            logger.info("Wrote optional circumplex chart to factor_circumplex.png")
            # Sidecar table so each circle's placement is auditable: which
            # numbers came from the coded analysis and which were derived here.
            write_csv(layout_dataframe(resolve_layout(profiles, config), config),
                       output_dir / "factor_circumplex_positions.csv")

    # --- 5c. Optional theme prioritization quadrant chart ---
    if generate_priority_matrix:
        written = write_theme_priority_matrix(
            profiles, output_dir / "opportunity_priority_matrix.png", config=config)
        if written:
            logger.info("Wrote optional priority matrix chart to opportunity_priority_matrix.png")
            # Sidecar: coded counts, authored difficulty, and the roster check.
            write_csv(opportunity_dataframe(load_opportunities(config), profiles),
                       output_dir / "opportunity_validation.csv")
            unnamed = unnamed_respondents(load_opportunities(config), profiles)
            if unnamed:
                logger.warning(
                    "Respondents named in no opportunity theme: %s", ", ".join(unnamed)
                )

    # --- 5d. Optional evidence reports, one standalone file per chart ---
    # They are written independently of the chart flags: the reports are the
    # audit trail for the numbers, and those exist whether or not the PNGs
    # were regenerated on this run (each report embeds its chart if present).
    if generate_reports:
        if write_circumplex_report(profiles, config,
                                    output_dir / "circumplex_evidence_report.xlsx"):
            logger.info("Wrote circumplex evidence report to circumplex_evidence_report.xlsx")
        if write_opportunity_report(profiles, config,
                                     output_dir / "opportunity_evidence_report.xlsx"):
            logger.info("Wrote opportunity evidence report to opportunity_evidence_report.xlsx")

    # --- 5e. Optional slide deck: every chart again, as editable shapes ---
    # Independent of the PNG flags: the deck re-draws the charts from the same
    # data rather than embedding the images, so it does not need them on disk.
    if generate_deck:
        if write_chart_deck(profiles, matrix_df, config, output_dir / "jabc_charts.pptx"):
            logger.info("Wrote editable chart deck to jabc_charts.pptx")

    # --- Optional calibration workflow ---
    if args.calibration_csv:
        logger.info("Running calibration against %s", args.calibration_csv)
        report_df, summary = run_calibration(profiles, args.calibration_csv)
        write_csv(report_df, output_dir / "calibration_report.csv")
        write_dataframe_excel(report_df, output_dir / "calibration_report.xlsx", sheet_name="Calibration")
        logger.info("Calibration summary: %s", summary)

    logger.info("Done. Outputs written to: %s", output_dir.resolve())
    print(f"\nBrand Health Matrix:\n{matrix_df.to_string(index=False)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
