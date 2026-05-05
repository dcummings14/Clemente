from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from html import escape
from pathlib import Path

from .models import AnalysisResult, Contact, EmailContent, Issue, ReportAttachment


def group_issues_by_producer(issues: list[Issue]) -> dict[str, list[Issue]]:
    grouped: dict[str, list[Issue]] = defaultdict(list)
    for issue in issues:
        grouped[issue.producer_id].append(issue)
    return dict(grouped)


def render_summary_email(
    analysis: AnalysisResult,
    *,
    new_issues: list[Issue],
    missing_contact_producers: list[str],
    drafted_producers: list[str],
    report: ReportAttachment | None,
) -> EmailContent:
    subject_date = analysis.pickup_end.isoformat() if analysis.pickup_end else date.today().isoformat()
    subject = f"Daily milk quality report - {subject_date}"
    rows = [
        ("Rows analyzed", str(len(analysis.rows))),
        ("Pickup date range", _date_range(analysis)),
        ("Total current issues", str(len(analysis.issues))),
        ("New issues for drafts", str(len(new_issues))),
        ("Producers with current issues", str(len(analysis.producers_with_issues))),
        ("Producer drafts created", str(len(drafted_producers))),
        ("Missing producer email mappings", str(len(missing_contact_producers))),
    ]
    report_rows = ""
    if report:
        report_rows = "".join(
            _table_row(label, value)
            for label, value in [
                ("Report email subject", report.message_subject),
                ("Report received", report.received_at),
                ("Attachment", report.attachment_name),
            ]
        )

    report_detail_rows = [
        ("Report email subject", report.message_subject),
        ("Report received", report.received_at),
        ("Attachment", report.attachment_name),
    ] if report else []
    text = "\n".join(
        [
            "Daily milk quality report",
            "",
            *[f"{label}: {value}" for label, value in rows],
            *[f"{label}: {value}" for label, value in report_detail_rows],
            "",
            "Issues by severity:",
            render_counts_text(analysis.issue_counts_by_severity),
            "",
            "Issues by metric:",
            render_counts_text(analysis.issue_counts_by_metric),
            "",
            "New issue detail:",
            render_issue_text(new_issues),
            "",
            f"Drafts created for: {', '.join(sorted(drafted_producers)) or 'none'}",
            f"Missing producer email mappings: {', '.join(sorted(missing_contact_producers)) or 'none'}",
        ]
    )
    html = f"""
    <html>
      <body>
        <h2>Daily milk quality report</h2>
        <table border="1" cellspacing="0" cellpadding="6">
          {''.join(_table_row(label, value) for label, value in rows)}
          {report_rows}
        </table>
        <h3>Issues by severity</h3>
        {render_counts_table(analysis.issue_counts_by_severity)}
        <h3>Issues by metric</h3>
        {render_counts_table(analysis.issue_counts_by_metric)}
        <h3>New issue detail</h3>
        {render_issue_table(new_issues)}
        <h3>Draft status</h3>
        <p>Drafts created for: {escape(', '.join(sorted(drafted_producers)) or 'none')}</p>
        <p>Missing producer email mappings: {escape(', '.join(sorted(missing_contact_producers)) or 'none')}</p>
      </body>
    </html>
    """
    return EmailContent(subject=subject, html=_compact_html(html), text=text)


def render_missing_report_email(*, sender: str, subject_prefix: str, attachment_name: str) -> EmailContent:
    subject = "Milk quality report missing"
    text = "\n".join(
        [
            "Milk quality report missing",
            "",
            "The daily agent did not find the expected milk quality report before the retry window closed.",
            f"Expected sender: {sender}",
            f"Expected subject prefix: {subject_prefix}",
            f"Expected attachment: {attachment_name}",
        ]
    )
    html = f"""
    <html>
      <body>
        <h2>Milk quality report missing</h2>
        <p>The daily agent did not find the expected milk quality report before the retry window closed.</p>
        <table border="1" cellspacing="0" cellpadding="6">
          {_table_row("Expected sender", sender)}
          {_table_row("Expected subject prefix", subject_prefix)}
          {_table_row("Expected attachment", attachment_name)}
        </table>
      </body>
    </html>
    """
    return EmailContent(subject=subject, html=_compact_html(html), text=text)


def render_producer_email(contact: Contact, issues: list[Issue], pickup_end: date | None) -> EmailContent:
    date_text = pickup_end.isoformat() if pickup_end else "current report"
    subject = f"Milk quality follow-up - {contact.name} - {date_text}"
    text = "\n".join(
        [
            "Hello,",
            "",
            f"The latest milk quality report has the following items for review for {contact.name}.",
            "",
            render_issue_text(issues),
            "",
            "Please review these results and follow up with Cobblestone if you have questions.",
            "",
            "Thank you.",
        ]
    )
    html = f"""
    <html>
      <body>
        <p>Hello,</p>
        <p>The latest milk quality report has the following items for review for {escape(contact.name)}.</p>
        {render_issue_table(issues)}
        <p>Please review these results and follow up with Cobblestone if you have questions.</p>
        <p>Thank you.</p>
      </body>
    </html>
    """
    return EmailContent(subject=subject, html=_compact_html(html), text=text)


def render_counts_table(counts: dict[str, int]) -> str:
    if not counts:
        return "<p>None.</p>"
    rows = "".join(_table_row(key, str(value)) for key, value in sorted(counts.items()))
    return f'<table border="1" cellspacing="0" cellpadding="6">{rows}</table>'


def render_counts_text(counts: dict[str, int]) -> str:
    if not counts:
        return "None."
    return "\n".join(f"- {key}: {value}" for key, value in sorted(counts.items()))


def render_issue_table(issues: list[Issue]) -> str:
    if not issues:
        return "<p>No new issues.</p>"
    rows = []
    for issue in sorted(issues, key=lambda item: (item.producer_id, item.pickup_date, item.tank, item.metric)):
        rows.append(
            "<tr>"
            f"<td>{escape(issue.producer_id)}</td>"
            f"<td>{escape(issue.tank)}</td>"
            f"<td>{escape(issue.pickup_date.isoformat())}</td>"
            f"<td>{escape(issue.test_date.isoformat() if issue.test_date else '')}</td>"
            f"<td>{escape(issue.barcode)}</td>"
            f"<td>{escape(issue.metric)}</td>"
            f"<td>{escape(issue.severity)}</td>"
            f"<td>{escape(f'{issue.value:g}')}</td>"
            f"<td>{escape(issue.message)}</td>"
            "</tr>"
        )
    header = (
        "<tr><th>Producer</th><th>Tank</th><th>Pickup</th><th>Test</th>"
        "<th>Barcode</th><th>Metric</th><th>Severity</th><th>Value</th><th>Issue</th></tr>"
    )
    return f'<table border="1" cellspacing="0" cellpadding="6">{header}{"".join(rows)}</table>'


def render_issue_text(issues: list[Issue]) -> str:
    if not issues:
        return "No new issues."
    lines = []
    for issue in sorted(issues, key=lambda item: (item.producer_id, item.pickup_date, item.tank, item.metric)):
        test_date = issue.test_date.isoformat() if issue.test_date else ""
        lines.append(
            "- "
            f"Producer {issue.producer_id}, tank {issue.tank}, pickup {issue.pickup_date.isoformat()}, "
            f"test {test_date}, barcode {issue.barcode}, {issue.metric} {issue.value:g} "
            f"({issue.severity}): {issue.message}"
        )
    return "\n".join(lines)


def write_dry_run_artifacts(
    output_dir: Path,
    *,
    summary: EmailContent,
    producer_emails: dict[str, EmailContent],
    metadata: dict[str, object],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.html").write_text(summary.html, encoding="utf-8")
    (output_dir / "summary.txt").write_text(summary.text + "\n", encoding="utf-8")
    (output_dir / "summary_subject.txt").write_text(summary.subject + "\n", encoding="utf-8")
    drafts_dir = output_dir / "producer_drafts"
    drafts_dir.mkdir(exist_ok=True)
    for producer_id, content in producer_emails.items():
        safe_id = "".join(char for char in producer_id if char.isalnum() or char in ("-", "_"))
        (drafts_dir / f"{safe_id}.html").write_text(content.html, encoding="utf-8")
        (drafts_dir / f"{safe_id}.txt").write_text(content.text + "\n", encoding="utf-8")
        (drafts_dir / f"{safe_id}.subject.txt").write_text(content.subject + "\n", encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _date_range(analysis: AnalysisResult) -> str:
    if not analysis.pickup_start or not analysis.pickup_end:
        return "none"
    if analysis.pickup_start == analysis.pickup_end:
        return analysis.pickup_start.isoformat()
    return f"{analysis.pickup_start.isoformat()} to {analysis.pickup_end.isoformat()}"


def _table_row(label: str, value: str) -> str:
    return f"<tr><th align=\"left\">{escape(label)}</th><td>{escape(value)}</td></tr>"


def _compact_html(html: str) -> str:
    return "\n".join(line.strip() for line in html.splitlines() if line.strip())
