from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import config
from .storage import now_bjt_iso, write_json

BJT = timezone(timedelta(hours=8))


@dataclass(slots=True)
class ChannelRun:
    attempts: int = 0
    status: str = "pending"
    stages: dict[str, dict[str, str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    episode_id: str = ""
    updated_at_bjt: str = ""


@dataclass(slots=True)
class RunLedger:
    date_bjt: str
    channels: dict[str, ChannelRun]
    notifications: dict[str, str] = field(default_factory=dict)
    release: dict[str, Any] = field(default_factory=dict)
    updated_at_bjt: str = ""

    @classmethod
    def new(cls, date_bjt: str) -> "RunLedger":
        return cls(date_bjt, {category: ChannelRun() for category in config.CATEGORIES})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunLedger":
        channels = {
            category: ChannelRun(**data.get("channels", {}).get(category, {}))
            for category in config.CATEGORIES
        }
        return cls(
            str(data.get("date_bjt") or ""), channels,
            dict(data.get("notifications", {})), dict(data.get("release", {})),
            str(data.get("updated_at_bjt") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RunLedgerStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or config.RUNS_DIR)

    def path(self, date_bjt: str) -> Path:
        datetime.strptime(date_bjt, "%Y-%m-%d")
        return self.root / f"{date_bjt}.json"

    def load(self, date_bjt: str) -> RunLedger:
        path = self.path(date_bjt)
        if not path.exists():
            return RunLedger.new(date_bjt)
        return RunLedger.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, ledger: RunLedger) -> None:
        ledger.updated_at_bjt = now_bjt_iso()
        write_json(self.path(ledger.date_bjt), ledger.to_dict())

    def begin_attempt(self, date_bjt: str, category: str) -> RunLedger:
        ledger = self.load(date_bjt)
        channel = ledger.channels[category]
        channel.attempts += 1
        channel.status = "running"
        channel.updated_at_bjt = now_bjt_iso()
        self.save(ledger)
        return ledger

    def stage(self, date_bjt: str, category: str, stage: str, status: str, detail: str = "") -> None:
        ledger = self.load(date_bjt)
        channel = ledger.channels[category]
        channel.stages[stage] = {"status": status, "detail": detail, "at_bjt": now_bjt_iso()}
        channel.updated_at_bjt = now_bjt_iso()
        if status == "failed" and detail and detail not in channel.errors:
            channel.errors.append(detail[:500])
        self.save(ledger)

    def finish(self, date_bjt: str, category: str, status: str, episode_id: str = "", error: str = "") -> None:
        ledger = self.load(date_bjt)
        channel = ledger.channels[category]
        channel.status = status
        channel.episode_id = episode_id or channel.episode_id
        channel.updated_at_bjt = now_bjt_iso()
        if error and error not in channel.errors:
            channel.errors.append(error[:500])
        self.save(ledger)

    def set_release(self, date_bjt: str, category: str, status: str, detail: str = "") -> None:
        ledger = self.load(date_bjt)
        entry = ledger.release.setdefault(category, {"status": "pending", "stages": {}})
        entry.setdefault("stages", {})[status] = {"detail": detail, "at_bjt": now_bjt_iso()}
        entry["status"] = status
        entry["detail"] = detail
        entry["at_bjt"] = now_bjt_iso()
        self.save(ledger)

    def should_notify(self, date_bjt: str, key: str) -> bool:
        return key not in self.load(date_bjt).notifications

    def mark_notified(self, date_bjt: str, key: str) -> None:
        ledger = self.load(date_bjt)
        ledger.notifications[key] = now_bjt_iso()
        self.save(ledger)

    def retry_categories(self, date_bjt: str) -> list[str]:
        ledger = self.load(date_bjt)
        return [
            category for category, channel in ledger.channels.items()
            if channel.status in {"pending", "failed", "skipped"}
        ]


def run_status(date_bjt: str | None = None, root: Path | None = None) -> dict[str, Any]:
    date_bjt = date_bjt or datetime.now(BJT).strftime("%Y-%m-%d")
    payload = RunLedgerStore(root).load(date_bjt).to_dict()
    if root is None:
        from .model_api import usage_report
        payload["model_usage"] = usage_report(date_bjt, 1)
    return payload
