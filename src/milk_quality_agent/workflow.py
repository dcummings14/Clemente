from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .analyzer import analyze_rows, parse_quality_csv_bytes
from .email_render import (
    group_issues_by_producer,
    render_missing_report_email,
    render_producer_email,
    render_summary_email,
    write_dry_run_artifacts,
)
from .history import RunHistory
from .models import AnalysisResult, AppConfig, EmailContent, Issue, ReportAttachment


@dataclass(frozen=True)
class ProcessResult:
    analysis: AnalysisResult
    new_issues: list[Issue]
    producer_emails: dict[str, EmailContent]
    missing_contact_producers: list[str]
    drafted_producers: list[str]
    summary: EmailContent


def analyze_csv_bytes(
    content: bytes,
    *,
    config: AppConfig,
    history: RunHistory,
    report: ReportAttachment | None = None,
) -> ProcessResult:
    rows = parse_quality_csv_bytes(content)
    analysis = analyze_rows(rows, config.thresholds)
    new_issues = history.filter_new(analysis.issues)
    producer_emails, missing_contacts = build_producer_drafts(config, analysis, new_issues)
    summary = render_summary_email(
        analysis,
        new_issues=new_issues,
        missing_contact_producers=missing_contacts,
        drafted_producers=[],
        report=report,
    )
    return ProcessResult(
        analysis=analysis,
        new_issues=new_issues,
        producer_emails=producer_emails,
        missing_contact_producers=missing_contacts,
        drafted_producers=[],
        summary=summary,
    )


def analyze_file(
    path: str | Path,
    *,
    config: AppConfig,
    history: RunHistory,
    output_dir: Path | None = None,
) -> ProcessResult:
    content = Path(path).read_bytes()
    result = analyze_csv_bytes(content, config=config, history=history)
    if output_dir:
        actions = build_connector_actions(config=config, result=result)
        write_dry_run_artifacts(
            output_dir,
            summary=result.summary,
            producer_emails=result.producer_emails,
            metadata={
                "csv_path": str(path),
                "rows": len(result.analysis.rows),
                "total_issues": len(result.analysis.issues),
                "new_issues": len(result.new_issues),
                "producer_drafts": sorted(result.producer_emails),
                "missing_contact_producers": result.missing_contact_producers,
                "pickup_start": result.analysis.pickup_start.isoformat() if result.analysis.pickup_start else None,
                "pickup_end": result.analysis.pickup_end.isoformat() if result.analysis.pickup_end else None,
            },
        )
        write_connector_actions(output_dir / "connector_actions.json", actions)
    return result


def build_producer_drafts(
    config: AppConfig,
    analysis: AnalysisResult,
    new_issues: list[Issue],
) -> tuple[dict[str, EmailContent], list[str]]:
    producer_emails: dict[str, EmailContent] = {}
    missing_contacts: list[str] = []
    for producer_id, issues in group_issues_by_producer(new_issues).items():
        contact = config.producer_contacts.get(producer_id)
        if not contact or not contact.email:
            missing_contacts.append(producer_id)
            continue
        producer_emails[producer_id] = render_producer_email(contact, issues, analysis.pickup_end)
    return producer_emails, sorted(missing_contacts)


def build_connector_actions(*, config: AppConfig, result: ProcessResult) -> dict[str, object]:
    if not config.outlook.summary_recipient or config.outlook.summary_recipient.startswith("REPLACE_WITH_"):
        summary_email = None
    else:
        summary_email = {
            "tool": "mcp__codex_apps__microsoft_outlook_email._send_email",
            "payload": {
                "to": [{"email": config.outlook.summary_recipient}],
                "subject": result.summary.subject,
                "text_content": result.summary.text,
                "save_to_sent_items": True,
            },
        }

    issue_keys_by_producer: dict[str, list[str]] = {}
    drafts: list[dict[str, object]] = []
    for producer_id, content in result.producer_emails.items():
        contact = config.producer_contacts[producer_id]
        producer_issue_keys = [
            issue.key for issue in result.new_issues if issue.producer_id == producer_id
        ]
        issue_keys_by_producer[producer_id] = producer_issue_keys
        drafts.append(
            {
                "producer_id": producer_id,
                "tool": "mcp__codex_apps__microsoft_outlook_email._draft_email",
                "payload": {
                    "to": [{"email": contact.email, "name": contact.name}],
                    "subject": content.subject,
                    "text_content": content.text,
                },
                "issue_keys": producer_issue_keys,
            }
        )

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary_email": summary_email,
        "producer_drafts": drafts,
        "issue_keys_by_producer": issue_keys_by_producer,
        "missing_contact_producers": result.missing_contact_producers,
        "stats": {
            "rows": len(result.analysis.rows),
            "total_issues": len(result.analysis.issues),
            "new_issues": len(result.new_issues),
            "pickup_start": result.analysis.pickup_start.isoformat() if result.analysis.pickup_start else None,
            "pickup_end": result.analysis.pickup_end.isoformat() if result.analysis.pickup_end else None,
        },
    }


def build_missing_report_action(config: AppConfig) -> dict[str, object]:
    content = render_missing_report_email(
        sender=config.outlook.sender,
        subject_prefix=config.outlook.subject_prefix,
        attachment_name=config.outlook.attachment_name,
    )
    if not config.outlook.summary_recipient or config.outlook.summary_recipient.startswith("REPLACE_WITH_"):
        payload = None
    else:
        payload = {
            "to": [{"email": config.outlook.summary_recipient}],
            "subject": content.subject,
            "text_content": content.text,
            "save_to_sent_items": True,
        }
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "missing_report_email": {
            "tool": "mcp__codex_apps__microsoft_outlook_email._send_email",
            "payload": payload,
        },
        "expected": {
            "sender": config.outlook.sender,
            "subject_prefix": config.outlook.subject_prefix,
            "attachment_name": config.outlook.attachment_name,
        },
    }


def write_connector_actions(path: Path, actions: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(actions, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finalize_connector_actions(
    *,
    actions_path: Path,
    history: RunHistory,
    drafted_producers: list[str] | None = None,
) -> list[str]:
    actions = json.loads(actions_path.read_text(encoding="utf-8"))
    drafts = list(actions.get("producer_drafts") or [])
    if drafted_producers is None or not drafted_producers:
        drafted_producers = [str(draft["producer_id"]) for draft in drafts]

    processed_keys: list[str] = []
    for draft in drafts:
        producer_id = str(draft.get("producer_id") or "")
        if producer_id not in drafted_producers:
            continue
        processed_keys.extend(str(key) for key in draft.get("issue_keys") or [])

    history.processed_issue_keys.update(processed_keys)
    history.data["processed_issue_keys"] = sorted(history.processed_issue_keys)
    history.record_run(
        "connector_finalized",
        {
            "actions_path": str(actions_path),
            "drafted_producers": sorted(drafted_producers),
            "processed_issue_keys": len(processed_keys),
        },
    )
    history.save()
    return sorted(set(drafted_producers))
