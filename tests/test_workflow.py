from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from milk_quality_agent.analyzer import CsvSchemaError
from milk_quality_agent.config import load_config
from milk_quality_agent.email_render import render_missing_report_email
from milk_quality_agent.history import RunHistory
from milk_quality_agent.models import Contact
from milk_quality_agent.workflow import (
    analyze_file,
    build_connector_actions,
    build_missing_report_action,
    finalize_connector_actions,
)


class WorkflowTests(unittest.TestCase):
    def test_analyze_file_writes_dry_run_artifacts_and_connector_actions(self) -> None:
        config = load_config("config/settings.example.json")
        csv_text = (
            "PICKUPDATE,TESTDATE,PRODDIV,PRODNUM,TANK,BARCODE,BF,SCC,SPC,PIC,LPC\n"
            "4/1/2026,4/2/2026,4CS,1009,2,a,3.4,300,,,\n"
        )
        root = Path.cwd() / "data" / "test_workflow_artifacts"
        root.mkdir(parents=True, exist_ok=True)
        csv_path = root / "report.csv"
        csv_path.write_text(csv_text, encoding="utf-8")
        history = RunHistory(root / "history.json")
        output_dir = root / "out"
        result = analyze_file(csv_path, config=config, history=history, output_dir=output_dir)
        self.assertEqual(len(result.analysis.rows), 1)
        self.assertTrue((output_dir / "summary.html").exists())
        self.assertTrue((output_dir / "summary.txt").exists())
        self.assertTrue((output_dir / "metadata.json").exists())
        self.assertTrue((output_dir / "connector_actions.json").exists())

    def test_connector_actions_include_plain_text_summary_and_draft_payloads(self) -> None:
        config = load_config("config/settings.example.json")
        config = replace(
            config,
            outlook=replace(config.outlook, summary_recipient="manager@example.com"),
            producer_contacts={
                **config.producer_contacts,
                "1009": Contact("1009", "Producer 1009", "producer1009@example.com"),
            },
        )
        csv_text = (
            "PICKUPDATE,TESTDATE,PRODDIV,PRODNUM,TANK,BARCODE,BF,SCC,SPC,PIC,LPC\n"
            "4/1/2026,4/2/2026,4CS,1009,2,a,3.4,300,,,\n"
        )
        root = Path.cwd() / "data" / "test_workflow_artifacts"
        root.mkdir(parents=True, exist_ok=True)
        csv_path = root / "report_for_actions.csv"
        csv_path.write_text(csv_text, encoding="utf-8")
        result = analyze_file(csv_path, config=config, history=RunHistory(root / "history.json"))

        actions = build_connector_actions(config=config, result=result)

        self.assertEqual(
            actions["summary_email"]["payload"]["to"],
            [{"email": "manager@example.com"}],
        )
        self.assertIn("Daily milk quality report", actions["summary_email"]["payload"]["text_content"])
        drafts = actions["producer_drafts"]
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["payload"]["to"][0]["email"], "producer1009@example.com")
        self.assertIn("latest milk quality report", drafts[0]["payload"]["text_content"])
        self.assertGreater(len(drafts[0]["issue_keys"]), 0)

    def test_finalize_connector_actions_marks_issue_keys_processed(self) -> None:
        root = Path.cwd() / "data" / "test_workflow_artifacts"
        root.mkdir(parents=True, exist_ok=True)
        actions_path = root / "connector_actions_for_finalize.json"
        actions_path.write_text(
            json.dumps(
                {
                    "producer_drafts": [
                        {"producer_id": "1009", "issue_keys": ["a", "b"]},
                        {"producer_id": "1011", "issue_keys": ["c"]},
                    ]
                }
            ),
            encoding="utf-8",
        )
        history = RunHistory(root / "finalize_history.json")

        finalized = finalize_connector_actions(
            actions_path=actions_path,
            history=history,
            drafted_producers=["1009"],
        )

        self.assertEqual(finalized, ["1009"])
        self.assertIn("a", history.processed_issue_keys)
        self.assertIn("b", history.processed_issue_keys)
        self.assertNotIn("c", history.processed_issue_keys)

    def test_malformed_csv_raises_schema_error(self) -> None:
        config = load_config("config/settings.example.json")
        root = Path.cwd() / "data" / "test_workflow_artifacts"
        root.mkdir(parents=True, exist_ok=True)
        csv_path = root / "bad_report.csv"
        csv_path.write_text("PICKUPDATE,BF\n4/1/2026,3.4\n", encoding="utf-8")
        with self.assertRaises(CsvSchemaError):
            analyze_file(csv_path, config=config, history=RunHistory(root / "history.json"))

    def test_missing_report_notice_has_expected_match_details(self) -> None:
        content = render_missing_report_email(
            sender="noreply@dfamilk.com",
            subject_prefix="4CS Current Month was executed at",
            attachment_name="4CS Current Month.csv",
        )
        self.assertIn("noreply@dfamilk.com", content.html)
        self.assertIn("4CS Current Month.csv", content.html)
        self.assertIn("noreply@dfamilk.com", content.text)

    def test_missing_report_action_uses_connector_send_payload(self) -> None:
        config = load_config("config/settings.example.json")
        config = replace(config, outlook=replace(config.outlook, summary_recipient="manager@example.com"))
        actions = build_missing_report_action(config)
        self.assertEqual(
            actions["missing_report_email"]["tool"],
            "mcp__codex_apps__microsoft_outlook_email._send_email",
        )
        self.assertEqual(actions["missing_report_email"]["payload"]["to"], [{"email": "manager@example.com"}])


if __name__ == "__main__":
    unittest.main()
