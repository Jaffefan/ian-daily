from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import config
from .models import EpisodeBundle, QualityReport

BJT = timezone(timedelta(hours=8))


def now_bjt() -> datetime:
    return datetime.now(BJT)


def now_bjt_iso() -> str:
    return now_bjt().isoformat(timespec="seconds")


def write_json(path: Path, data: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class EpisodeStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or config.DRAFTS_DIR)

    def episode_dir(self, episode_id: str) -> Path:
        if not episode_id or not all(char.isalnum() or char in "-_" for char in episode_id):
            raise ValueError(f"不安全的节目 ID：{episode_id}")
        return self.root / episode_id

    def save_bundle(self, bundle: EpisodeBundle) -> Path:
        path = self.episode_dir(bundle.episode_id) / "bundle.json"
        write_json(path, bundle.to_dict())
        return path

    def save_quality(self, report: QualityReport) -> Path:
        path = self.episode_dir(report.episode_id) / "quality_report.json"
        write_json(path, report.to_dict())
        return path

    def load_bundle(self, episode_id: str) -> EpisodeBundle:
        return EpisodeBundle.from_dict(json.loads((self.episode_dir(episode_id) / "bundle.json").read_text(encoding="utf-8")))

    def load_quality(self, episode_id: str) -> QualityReport:
        return QualityReport.from_dict(json.loads((self.episode_dir(episode_id) / "quality_report.json").read_text(encoding="utf-8")))

    def transition(self, episode_id: str, state: str) -> EpisodeBundle:
        allowed = {"generated": {"quality_passed", "failed"}, "quality_passed": {"published", "failed"}, "published": set(), "failed": {"generated"}}
        bundle = self.load_bundle(episode_id)
        if bundle.status == state:
            return bundle
        if state not in allowed.get(bundle.status, set()):
            raise RuntimeError(f"非法状态转换：{bundle.status} → {state}")
        bundle.status = state
        bundle.updated_at_bjt = now_bjt_iso()
        self.save_bundle(bundle)
        return bundle

    def list_bundles(self, statuses: set[str] | None = None) -> list[EpisodeBundle]:
        result: list[EpisodeBundle] = []
        for path in self.root.glob("*/bundle.json") if self.root.exists() else []:
            try:
                bundle = EpisodeBundle.from_dict(json.loads(path.read_text(encoding="utf-8")))
                if not statuses or bundle.status in statuses:
                    result.append(bundle)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return sorted(result, key=lambda item: item.created_at_bjt, reverse=True)

    def published_story_ids(self, since_days: int = 30) -> set[str]:
        cutoff = now_bjt() - timedelta(days=since_days)
        result: set[str] = set()
        for bundle in self.list_bundles({"published"}):
            try:
                if datetime.fromisoformat(bundle.date_bjt).replace(tzinfo=BJT) < cutoff:
                    continue
            except ValueError:
                pass
            result.update(item.id for item in bundle.story_set.articles)
        return result
