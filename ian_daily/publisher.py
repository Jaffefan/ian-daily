from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config
from .feishu import send_channel_card
from .site import build_site
from .storage import EpisodeStore, now_bjt_iso, write_json
from .operations import RunLedgerStore

BJT = timezone(timedelta(hours=8))
MANIFEST = config.DATA_DIR / "release_manifest.json"


def prepare_release(date_bjt: str | None = None, store: EpisodeStore | None = None, rebuild: bool = False) -> list[str]:
    store = store or EpisodeStore()
    date_bjt = date_bjt or datetime.now(BJT).strftime("%Y-%m-%d")
    candidates = [
        item for item in store.list_bundles({"quality_passed", "published"})
        if item.date_bjt == date_bjt
        and (rebuild or item.status == "quality_passed" or not item.feishu_notified_at_bjt)
    ]
    ids = [item.episode_id for item in candidates if store.load_quality(item.episode_id).publishable]
    build_site(store, include_ids=set(ids))
    write_json(MANIFEST, {"date_bjt": date_bjt, "episode_ids": ids, "prepared_at_bjt": now_bjt_iso()})
    ledger = RunLedgerStore()
    for item in candidates:
        if item.episode_id in ids:
            ledger.set_release(date_bjt, item.category, "prepared", item.episode_id)
    return ids


def verify_release(manifest_path: Path = MANIFEST, attempts: int = 8) -> None:
    import httpx
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    urls = [config.PUBLIC_SITE_URL]
    for episode_id in payload.get("episode_ids", []):
        category = episode_id.rsplit("-", 1)[-1]
        base = f"{config.PUBLIC_SITE_URL}{category}/{episode_id}/"
        urls.extend((base, base + "episode.mp3"))
    last = ""
    for attempt in range(attempts):
        try:
            for url in urls:
                response = httpx.get(url, params={"release": payload.get("prepared_at_bjt", "")}, timeout=30, follow_redirects=True)
                response.raise_for_status()
                if url.endswith(".mp3") and len(response.content) < 100_000:
                    raise RuntimeError(f"音频文件异常：{url}")
            ledger = RunLedgerStore()
            for episode_id in payload.get("episode_ids", []):
                ledger.set_release(payload["date_bjt"], episode_id.rsplit("-", 1)[-1], "verified", episode_id)
            return
        except Exception as exc:
            last = str(exc)
            if attempt < attempts - 1:
                time.sleep(10)
    ledger = RunLedgerStore()
    for episode_id in payload.get("episode_ids", []):
        ledger.set_release(payload["date_bjt"], episode_id.rsplit("-", 1)[-1], "failed", last)
    raise RuntimeError(f"Pages 上线验证失败：{last}")


def finalize_release(manifest_path: Path = MANIFEST, store: EpisodeStore | None = None) -> list[str]:
    store = store or EpisodeStore()
    ledger = RunLedgerStore()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    published: list[str] = []
    for episode_id in payload.get("episode_ids", []):
        bundle = store.load_bundle(episode_id)
        if bundle.status == "quality_passed":
            bundle = store.transition(episode_id, "published")
        if bundle.status != "published":
            continue
        if not bundle.published_at_bjt:
            bundle.published_at_bjt = now_bjt_iso()
        if not bundle.feishu_notified_at_bjt:
            if send_channel_card(bundle, store.load_quality(episode_id), bundle.category):
                bundle.feishu_notified_at_bjt = now_bjt_iso()
                ledger.set_release(payload.get("date_bjt", bundle.date_bjt), bundle.category, "feishu_notified", bundle.episode_id)
            else:
                ledger.set_release(payload.get("date_bjt", bundle.date_bjt), bundle.category, "feishu_failed", bundle.episode_id)
        store.save_bundle(bundle)
        date_bjt = payload.get("date_bjt", bundle.date_bjt)
        ledger.set_release(date_bjt, bundle.category, "published", bundle.episode_id)
        ledger.finish(date_bjt, bundle.category, "published", bundle.episode_id)
        source = store.episode_dir(episode_id) / bundle.podcast.full_audio_file
        source.unlink(missing_ok=True)
        published.append(episode_id)
    return published


def publish_ready(date_bjt: str | None = None, store: EpisodeStore | None = None) -> list[str]:
    ids = prepare_release(date_bjt, store)
    return finalize_release(MANIFEST, store) if ids else []


def notify_generation_failures() -> None:
    path = config.DATA_DIR / "last_generation.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    date_bjt = str(payload.get("at_bjt") or datetime.now(BJT).isoformat())[:10]
    ledger = RunLedgerStore()
    notified: set[str] = set()
    for category, error in payload.get("failures", {}).items():
        if category in config.CATEGORIES:
            key = f"generation:{category}"
            if ledger.should_notify(date_bjt, key) and send_channel_card(None, None, category, str(error)):
                ledger.mark_notified(date_bjt, key)
            notified.add(category)
    store = EpisodeStore()
    for episode_id in payload.get("episodes", []):
        try:
            bundle = store.load_bundle(str(episode_id))
            if bundle.status != "failed" or bundle.category in notified:
                continue
            report = store.load_quality(bundle.episode_id)
            key = f"generation:{bundle.category}"
            if ledger.should_notify(date_bjt, key) and send_channel_card(None, report, bundle.category, "；".join(report.errors[:3]) or "内容生成失败"):
                ledger.mark_notified(date_bjt, key)
        except (OSError, ValueError, TypeError):
            continue


def notify_release_overdue(date_bjt: str | None = None) -> None:
    date_bjt = date_bjt or datetime.now(BJT).strftime("%Y-%m-%d")
    store = EpisodeStore()
    ledger = RunLedgerStore()
    for bundle in store.list_bundles({"quality_passed"}):
        if bundle.date_bjt == date_bjt:
            key = f"release-overdue:{bundle.category}"
            if ledger.should_notify(date_bjt, key) and send_channel_card(None, store.load_quality(bundle.episode_id), bundle.category, "09:51 后仍未完成 Pages 上线验证，系统将继续保留待发布状态"):
                ledger.mark_notified(date_bjt, key)
