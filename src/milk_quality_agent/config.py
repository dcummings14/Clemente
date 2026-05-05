from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AppConfig, Contact, OutlookSettings


DEFAULT_CONFIG_PATH = Path("config/settings.json")
EXAMPLE_CONFIG_PATH = Path("config/settings.example.json")


class ConfigError(ValueError):
    pass


def load_config(path: str | Path = DEFAULT_CONFIG_PATH, *, allow_example: bool = True) -> AppConfig:
    config_path = Path(path)
    is_example = False
    if not config_path.exists():
        if allow_example and config_path == DEFAULT_CONFIG_PATH and EXAMPLE_CONFIG_PATH.exists():
            config_path = EXAMPLE_CONFIG_PATH
            is_example = True
        else:
            raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    base_dir = _base_dir_for(config_path)
    return _parse_config(data, config_path.resolve(), base_dir.resolve(), is_example=is_example)


def _base_dir_for(config_path: Path) -> Path:
    parent = config_path.resolve().parent
    if parent.name.lower() == "config":
        return parent.parent
    return parent


def _parse_config(data: dict[str, Any], path: Path, base_dir: Path, *, is_example: bool) -> AppConfig:
    try:
        outlook = data["outlook"]
    except KeyError as exc:
        raise ConfigError(f"Missing required config section: {exc.args[0]}") from exc

    contacts = {
        str(producer_id): Contact(
            producer_id=str(producer_id),
            name=str(contact.get("name") or f"Producer {producer_id}"),
            email=str(contact.get("email") or "").strip(),
        )
        for producer_id, contact in (data.get("producer_contacts") or {}).items()
    }

    thresholds: dict[str, dict[str, float]] = {}
    for metric, values in (data.get("thresholds") or {}).items():
        thresholds[str(metric)] = {str(k): float(v) for k, v in values.items()}

    return AppConfig(
        path=path,
        base_dir=base_dir,
        timezone=str(data.get("timezone") or "America/New_York"),
        history_path=_resolve(base_dir, data.get("history_path") or "data/history.json"),
        downloads_dir=_resolve(base_dir, data.get("downloads_dir") or "data/downloads"),
        reports_dir=_resolve(base_dir, data.get("reports_dir") or "data/reports"),
        outlook=OutlookSettings(
            sender=str(outlook.get("sender") or "").strip().lower(),
            subject_prefix=str(outlook.get("subject_prefix") or ""),
            attachment_name=str(outlook.get("attachment_name") or ""),
            max_messages=int(outlook.get("max_messages") or 100),
            summary_recipient=str(outlook.get("summary_recipient") or "").strip(),
            retry_until=str(outlook.get("retry_until") or "09:00"),
            poll_interval_seconds=int(outlook.get("poll_interval_seconds") or 600),
        ),
        thresholds=thresholds,
        producer_contacts=contacts,
        is_example=is_example,
    )


def _resolve(base_dir: Path, value: str | Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return base_dir / candidate
