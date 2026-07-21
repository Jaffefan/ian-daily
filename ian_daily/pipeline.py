from __future__ import annotations

from . import config
from .agents import audit_editions, build_fact_packs, generate_podcast, generate_reading
from .audio import generate_podcast_audio
from .models import Article, DailyStorySet, EpisodeBundle
from .quality import evaluate_bundle
from .selection import select_articles
from .sources import enrich_article, event_fingerprint, fetch_category, fetch_community_signals, fetch_corroborating_articles
from .storage import EpisodeStore, now_bjt, now_bjt_iso, write_json


class InsufficientContent(RuntimeError):
    pass


def _prepare(selected: list[Article], candidates: list[Article]) -> dict[str, list[Article]]:
    corroboration_by_story: dict[str, list[Article]] = {}
    for article in selected:
        print(f"  [enrich] {article.source}: {article.title[:55]}")
        enrich_article(article)
        article.community_signals = fetch_community_signals(article)
        try:
            corroboration = fetch_corroborating_articles(article, limit=4)
            candidates.extend(corroboration)
            corroboration_by_story[article.id] = corroboration
        except Exception as exc:
            print(f"  [source-warning] {exc}")
    return corroboration_by_story


def generate_category(category: str, *, force: bool = False, skip_audio: bool = False, store: EpisodeStore | None = None, claimed_ids: set[str] | None = None) -> EpisodeBundle:
    if category not in config.CATEGORIES:
        raise ValueError(f"未知频道：{category}")
    store = store or EpisodeStore()
    now = now_bjt()
    episode_id = f"{now:%Y-%m-%d}-{category}"
    bundle_path = store.episode_dir(episode_id) / "bundle.json"
    if bundle_path.exists() and not force:
        return store.load_bundle(episode_id)
    if bundle_path.exists() and store.load_bundle(episode_id).status == "published":
        raise RuntimeError("已发布节目不可覆盖")

    candidates = fetch_category(category)
    selected = select_articles(candidates, category, store.published_story_ids(), claimed_ids, now=now)
    if len(selected) < 4:
        raise InsufficientContent(f"{config.CATEGORIES[category].name}在 72 小时内不足 4 条合格事件")
    if claimed_ids is not None:
        claimed_ids.update(item.id for item in selected)
        claimed_ids.update(event_fingerprint(item.title) for item in selected)
    corroboration_by_story = _prepare(selected, candidates)
    packs = build_fact_packs(selected, candidates, corroboration_by_story)
    story_set = DailyStorySet(category, now.strftime("%Y-%m-%d"), selected, packs)

    print("  [agent] 独立生成图文版")
    reading = generate_reading(category, selected, packs)
    print("  [agent] 独立生成播客版")
    podcast = generate_podcast(category, packs)
    stamp = now_bjt_iso()
    bundle = EpisodeBundle(
        episode_id=episode_id, schema_version=2, category=category,
        category_name=config.CATEGORIES[category].name, date_bjt=now.strftime("%Y-%m-%d"),
        story_set=story_set, reading=reading, podcast=podcast,
        created_at_bjt=stamp, updated_at_bjt=stamp,
    )
    episode_dir = store.episode_dir(episode_id)
    episode_dir.mkdir(parents=True, exist_ok=True)
    store.save_bundle(bundle)
    write_json(episode_dir / "story_set.json", story_set.to_dict())

    audit_errors = audit_editions(reading, podcast, packs)
    if not skip_audio and not audit_errors:
        print("  [tts] 生成完整双声音频")
        try:
            bundle.podcast = generate_podcast_audio(bundle.podcast, category, episode_dir)
        except Exception as exc:
            audit_errors.append(f"音频生成失败：{exc}")
        store.save_bundle(bundle)
    report = evaluate_bundle(bundle, audit_errors, require_audio=not skip_audio)
    store.save_quality(report)
    store.transition(episode_id, "quality_passed" if report.publishable else "failed")
    print(f"  [quality] {'PASS' if report.publishable else 'BLOCKED'}")
    return store.load_bundle(episode_id)


def generate_all(*, force: bool = False, skip_audio: bool = False) -> list[EpisodeBundle]:
    claimed: set[str] = set()
    result: list[EpisodeBundle] = []
    failures: dict[str, str] = {}
    for category in config.CATEGORIES:
        try:
            result.append(generate_category(category, force=force, skip_audio=skip_audio, claimed_ids=claimed))
        except Exception as exc:
            failures[category] = str(exc)
            print(f"  [failed] {category}: {exc}")
    write_json(config.DATA_DIR / "last_generation.json", {"at_bjt": now_bjt_iso(), "failures": failures, "episodes": [item.episode_id for item in result]})
    if failures and not result:
        raise RuntimeError("三个频道全部生成失败")
    return result
