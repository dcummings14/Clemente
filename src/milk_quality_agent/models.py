from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Contact:
    producer_id: str
    name: str
    email: str = ""


@dataclass(frozen=True)
class OutlookSettings:
    sender: str
    subject_prefix: str
    attachment_name: str
    max_messages: int
    summary_recipient: str
    retry_until: str
    poll_interval_seconds: int


@dataclass(frozen=True)
class AppConfig:
    path: Path
    base_dir: Path
    timezone: str
    history_path: Path
    downloads_dir: Path
    reports_dir: Path
    outlook: OutlookSettings
    thresholds: dict[str, dict[str, float]]
    producer_contacts: dict[str, Contact]
    is_example: bool = False


@dataclass(frozen=True)
class QualityRow:
    pickup_date: date
    test_date: date | None
    prod_div: str
    producer_id: str
    tank: str
    barcode: str
    metrics: dict[str, float | None]
    raw: dict[str, str] = field(repr=False)


@dataclass(frozen=True)
class Issue:
    producer_id: str
    tank: str
    pickup_date: date
    test_date: date | None
    barcode: str
    metric: str
    issue_type: str
    severity: str
    value: float
    message: str
    comparison_value: float | None = None

    @property
    def key(self) -> str:
        test = self.test_date.isoformat() if self.test_date else ""
        return "|".join(
            [
                self.producer_id,
                self.tank,
                self.pickup_date.isoformat(),
                test,
                self.barcode,
                self.metric,
                self.issue_type,
            ]
        )


@dataclass(frozen=True)
class AnalysisResult:
    rows: list[QualityRow]
    issues: list[Issue]
    issue_counts_by_metric: dict[str, int]
    issue_counts_by_severity: dict[str, int]
    producers_with_issues: set[str]
    pickup_start: date | None
    pickup_end: date | None
    analyzed_at: datetime


@dataclass(frozen=True)
class EmailContent:
    subject: str
    html: str
    text: str


@dataclass(frozen=True)
class ReportAttachment:
    message_id: str
    message_subject: str
    received_at: str
    attachment_name: str
    content: bytes


JsonObject = dict[str, Any]
