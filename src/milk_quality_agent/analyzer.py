from __future__ import annotations

import csv
from collections import Counter
from datetime import date, datetime
from io import StringIO
from pathlib import Path

from .models import AnalysisResult, Issue, QualityRow


REQUIRED_COLUMNS = [
    "PICKUPDATE",
    "TESTDATE",
    "PRODDIV",
    "PRODNUM",
    "TANK",
    "BARCODE",
    "BF",
    "SCC",
    "SPC",
    "PIC",
    "LPC",
]
METRICS = ["BF", "SCC", "SPC", "PIC", "LPC"]
HIGH_LIMIT_METRICS = ["SCC", "SPC", "PIC", "LPC"]


class CsvSchemaError(ValueError):
    pass


def load_quality_csv(path: str | Path) -> list[QualityRow]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return parse_quality_csv(handle.read())


def parse_quality_csv(text: str) -> list[QualityRow]:
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        raise CsvSchemaError("CSV has no header row.")

    missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
    if missing:
        raise CsvSchemaError(f"CSV is missing required columns: {', '.join(missing)}")

    rows: list[QualityRow] = []
    for line_number, raw in enumerate(reader, start=2):
        try:
            pickup_date = _parse_date(raw["PICKUPDATE"])
        except ValueError as exc:
            raise CsvSchemaError(f"Invalid PICKUPDATE on line {line_number}: {raw['PICKUPDATE']!r}") from exc

        test_date = None
        if raw.get("TESTDATE", "").strip():
            try:
                test_date = _parse_date(raw["TESTDATE"])
            except ValueError as exc:
                raise CsvSchemaError(f"Invalid TESTDATE on line {line_number}: {raw['TESTDATE']!r}") from exc

        rows.append(
            QualityRow(
                pickup_date=pickup_date,
                test_date=test_date,
                prod_div=raw.get("PRODDIV", "").strip(),
                producer_id=raw.get("PRODNUM", "").strip(),
                tank=raw.get("TANK", "").strip(),
                barcode=raw.get("BARCODE", "").strip(),
                metrics={metric: _parse_float(raw.get(metric, "")) for metric in METRICS},
                raw=raw,
            )
        )
    return rows


def parse_quality_csv_bytes(content: bytes) -> list[QualityRow]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return parse_quality_csv(content.decode(encoding))
        except UnicodeDecodeError:
            continue
    return parse_quality_csv(content.decode("utf-8-sig", errors="replace"))


def analyze_rows(rows: list[QualityRow], thresholds: dict[str, dict[str, float]]) -> AnalysisResult:
    ordered_rows = sorted(
        rows,
        key=lambda row: (
            row.producer_id,
            row.tank,
            row.pickup_date,
            row.test_date or date.min,
            row.barcode,
        ),
    )
    issues: list[Issue] = []
    previous_bf_by_tank: dict[tuple[str, str], float] = {}

    for row in ordered_rows:
        bf = row.metrics.get("BF")
        bf_thresholds = thresholds.get("BF", {})
        if bf is not None:
            low_warning = bf_thresholds.get("low_warning")
            if low_warning is not None and bf < low_warning:
                issues.append(
                    _issue(
                        row,
                        metric="BF",
                        issue_type="low",
                        severity="warning",
                        value=bf,
                        message=f"BF {bf:g} is below the warning limit of {low_warning:g}.",
                    )
                )

            tank_key = (row.producer_id, row.tank)
            previous_bf = previous_bf_by_tank.get(tank_key)
            drop_warning = bf_thresholds.get("drop_warning")
            if previous_bf is not None and drop_warning is not None:
                drop = previous_bf - bf
                if drop > drop_warning:
                    issues.append(
                        _issue(
                            row,
                            metric="BF",
                            issue_type="drop",
                            severity="warning",
                            value=bf,
                            comparison_value=previous_bf,
                            message=(
                                f"BF dropped by {drop:.2f}, from {previous_bf:g} to {bf:g}, "
                                f"which is more than the {drop_warning:g} warning limit."
                            ),
                        )
                    )
            previous_bf_by_tank[tank_key] = bf

        for metric in HIGH_LIMIT_METRICS:
            value = row.metrics.get(metric)
            if value is None:
                continue
            metric_thresholds = thresholds.get(metric, {})
            warning = metric_thresholds.get("warning")
            serious = metric_thresholds.get("serious")
            if serious is not None and value >= serious:
                issues.append(
                    _issue(
                        row,
                        metric=metric,
                        issue_type="high",
                        severity="serious",
                        value=value,
                        message=f"{metric} {value:g} is at or above the serious limit of {serious:g}.",
                    )
                )
            elif warning is not None and value >= warning:
                issues.append(
                    _issue(
                        row,
                        metric=metric,
                        issue_type="high",
                        severity="warning",
                        value=value,
                        message=f"{metric} {value:g} is at or above the warning limit of {warning:g}.",
                    )
                )

    metric_counts = Counter(issue.metric for issue in issues)
    severity_counts = Counter(issue.severity for issue in issues)
    pickup_dates = [row.pickup_date for row in rows]
    return AnalysisResult(
        rows=rows,
        issues=issues,
        issue_counts_by_metric=dict(metric_counts),
        issue_counts_by_severity=dict(severity_counts),
        producers_with_issues={issue.producer_id for issue in issues},
        pickup_start=min(pickup_dates) if pickup_dates else None,
        pickup_end=max(pickup_dates) if pickup_dates else None,
        analyzed_at=datetime.now(),
    )


def _issue(
    row: QualityRow,
    *,
    metric: str,
    issue_type: str,
    severity: str,
    value: float,
    message: str,
    comparison_value: float | None = None,
) -> Issue:
    return Issue(
        producer_id=row.producer_id,
        tank=row.tank,
        pickup_date=row.pickup_date,
        test_date=row.test_date,
        barcode=row.barcode,
        metric=metric,
        issue_type=issue_type,
        severity=severity,
        value=value,
        comparison_value=comparison_value,
        message=message,
    )


def _parse_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(value)


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return float(stripped)

