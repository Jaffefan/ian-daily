from __future__ import annotations

from . import config
from .feishu import send_channel_card
from .site import build_site
from .storage import EpisodeStore


def publish_ready(date_bjt: str | None = None, store: EpisodeStore | None = None) -> list[str]:
    store = store or EpisodeStore()
    ready = [item for item in store.list_bundles({"quality_passed"}) if not date_bjt or item.date_bjt == date_bjt]
    published: list[str] = []
    for bundle in ready:
        report = store.load_quality(bundle.episode_id)
        if not report.publishable:
            continue
        published.append(bundle.episode_id)
    build_site(store, include_ids=set(published))
    for episode_id in published:
        bundle = store.transition(episode_id, "published")
        send_channel_card(bundle, store.load_quality(episode_id), bundle.category)
    return published


def notify_generation_failures() -> None:
    path = config.DATA_DIR / "last_generation.json"
    if not path.exists():
        return
    import json
    payload = json.loads(path.read_text(encoding="utf-8"))
    for category, error in payload.get("failures", {}).items():
        if category in config.CATEGORIES:
            send_channel_card(None, None, category, str(error))
