from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .config import ConfigError, load_config
from .history import RunHistory
from .workflow import (
    analyze_file,
    build_missing_report_action,
    finalize_connector_actions,
    write_connector_actions,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (ConfigError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    config_parent = argparse.ArgumentParser(add_help=False)
    config_parent.add_argument(
        "--config",
        default="config/settings.json",
        help="Path to settings JSON. Defaults to config/settings.json.",
    )
    parser = argparse.ArgumentParser(
        description="Daily milk quality reporting agent.",
        parents=[config_parent],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze-file",
        parents=[config_parent],
        help="Analyze a local report CSV and write connector-ready action files.",
    )
    analyze.add_argument("csv_path", help="Path to a milk quality report CSV.")
    analyze.add_argument(
        "--output-dir",
        default=None,
        help="Directory for generated summary and producer draft HTML files.",
    )
    analyze.set_defaults(func=cmd_analyze_file)

    missing = subparsers.add_parser(
        "missing-report-actions",
        parents=[config_parent],
        help="Write a connector-ready missing-report summary email payload.",
    )
    missing.add_argument("--output-dir", default=None, help="Directory for connector_actions.json.")
    missing.set_defaults(func=cmd_missing_report_actions)

    finalize = subparsers.add_parser(
        "finalize-connector-actions",
        parents=[config_parent],
        help="Mark connector-created producer drafts as processed in local history.",
    )
    finalize.add_argument("actions_json", help="Path to a connector_actions.json file.")
    finalize.add_argument(
        "--drafted-producer",
        action="append",
        default=None,
        help="Producer ID drafted successfully. Repeat for partial finalization. Defaults to all producer draft actions.",
    )
    finalize.set_defaults(func=cmd_finalize_connector_actions)

    schedule = subparsers.add_parser(
        "automation-prompt",
        parents=[config_parent],
        help="Print a Codex automation prompt that uses the Outlook connector.",
    )
    schedule.set_defaults(func=cmd_automation_prompt)
    return parser


def cmd_analyze_file(args: argparse.Namespace) -> int:
    config = load_config(args.config, allow_example=True)
    if config.is_example:
        print("Using config/settings.example.json. Copy it to config/settings.json for real Outlook runs.")
    history = RunHistory.load(config.history_path)
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir(config.reports_dir)
    result = analyze_file(args.csv_path, config=config, history=history, output_dir=output_dir)
    print(f"Rows analyzed: {len(result.analysis.rows)}")
    print(f"Current issues: {len(result.analysis.issues)}")
    print(f"New issues: {len(result.new_issues)}")
    print(f"Producer draft files: {len(result.producer_emails)}")
    if result.missing_contact_producers:
        print("Missing producer email mappings: " + ", ".join(result.missing_contact_producers))
    print(f"Dry-run artifacts: {output_dir}")
    print(f"Connector actions: {output_dir / 'connector_actions.json'}")
    return 0


def cmd_missing_report_actions(args: argparse.Namespace) -> int:
    config = load_config(args.config, allow_example=True)
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir(config.reports_dir)
    actions = build_missing_report_action(config)
    write_connector_actions(output_dir / "connector_actions.json", actions)
    print(f"Missing-report connector actions: {output_dir / 'connector_actions.json'}")
    return 0


def cmd_finalize_connector_actions(args: argparse.Namespace) -> int:
    config = load_config(args.config, allow_example=True)
    history = RunHistory.load(config.history_path)
    producers = finalize_connector_actions(
        actions_path=Path(args.actions_json),
        history=history,
        drafted_producers=args.drafted_producer,
    )
    print("Finalized drafted producers: " + (", ".join(producers) or "none"))
    return 0


def cmd_automation_prompt(args: argparse.Namespace) -> int:
    config = load_config(args.config, allow_example=True)
    print(
        "Daily Codex automation prompt:\n\n"
        "Use the Outlook Email connector to list recent Inbox messages ordered by receivedDateTime desc. "
        f"Find the first message from {config.outlook.sender!r} whose subject starts with "
        f"{config.outlook.subject_prefix!r} and that has an attachment named "
        f"{config.outlook.attachment_name!r}. If the report is not found, retry every "
        f"{config.outlook.poll_interval_seconds // 60} minutes until {config.outlook.retry_until}. "
        "If still missing, run `python run_agent.py missing-report-actions`, read the generated "
        "`connector_actions.json`, and use the Outlook connector send_email action with that payload. "
        "If found, fetch the attachment bytes, save them under `data/downloads/`, run "
        "`python run_agent.py analyze-file <downloaded_csv_path>`, read the generated "
        "`connector_actions.json`, use the Outlook connector send_email action for `summary_email`, "
        "use the draft_email action for each item in `producer_drafts`, then run "
        "`python run_agent.py finalize-connector-actions <connector_actions.json>`."
    )
    return 0


def _default_output_dir(reports_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return reports_dir / f"dry_run_{stamp}"


if __name__ == "__main__":
    raise SystemExit(main())
