from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Issue


class RunHistory:
    def __init__(self, path: Path, data: dict[str, Any] | None = None) -> None:
        self.path = path
        self.data = data or {"processed_issue_keys": [], "runs": []}
        self.processed_issue_keys = set(self.data.get("processed_issue_keys") or [])

    @classmethod
    def load(cls, path: str | Path) -> "RunHistory":
        history_path = Path(path)
        if not history_path.exists():
            return cls(history_path)
        with history_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls(history_path, data)

    def is_new(self, issue: Issue) -> bool:
        return issue.key not in self.processed_issue_keys

    def filter_new(self, issues: list[Issue]) -> list[Issue]:
        return [issue for issue in issues if self.is_new(issue)]

    def mark_processed(self, issues: list[Issue]) -> None:
        for issue in issues:
            self.processed_issue_keys.add(issue.key)
        self.data["processed_issue_keys"] = sorted(self.processed_issue_keys)

    def record_run(self, status: str, details: dict[str, Any]) -> None:
        runs = list(self.data.get("runs") or [])
        runs.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": status,
                "details": details,
            }
        )
        self.data["runs"] = runs[-100:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(self.path)

