from __future__ import annotations

from . import config
from .agents import audit_editions, build_content_brief, build_fact_packs, generate_podcast, generate_reading
from .audio import generate_podcast_audio
from .images import resolve_story_images
from .model_api import deepseek_model_available, siliconflow_model_available, usage_anomaly
from .feishu import send_ops_card
from .models import Article, DailyStorySet, EpisodeBundle
from .quality import evaluate_bundle
from .selection import select_articles
from .sources import enrich_article, event_fingerprint, fetch_category, fetch_community_signals, fetch_corroborating_articles
from .storage import EpisodeStore, now_bjt, now_bjt_iso, write_json
from .operations import RunLedgerStore


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


def generate_category(category: str, *, force: bool = False, retry_failed: bool = False, skip_audio: bool = False, store: EpisodeStore | None = None, claimed_ids: set[str] | None = None, ledger_store: RunLedgerStore | None = None) -> EpisodeBundle:
    if category not in config.CATEGORIES:
        raise ValueError(f"未知频道：{category}")
    store = store or EpisodeStore()
    now = now_bjt()
    date_bjt = now.strftime("%Y-%m-%d")
    ledger_store = ledger_store or RunLedgerStore()
    episode_id = f"{now:%Y-%m-%d}-{category}"
    bundle_path = store.episode_dir(episode_id) / "bundle.json"
    if bundle_path.exists():
        existing = store.load_bundle(episode_id)
        if existing.status == "published":
            ledger_store.finish(date_bjt, category, "published", episode_id)
            return existing
        if existing.status == "quality_passed" and not force:
            ledger_store.finish(date_bjt, category, "quality_passed", episode_id)
            return existing
        if existing.status in {"failed", "generated"} and retry_failed:
            if existing.status == "failed":
                store.transition(episode_id, "generated")
        elif not force:
            return existing

    ledger_store.begin_attempt(date_bjt, category)
    if not deepseek_model_available(config.DEEPSEEK_MODEL):
        raise RuntimeError(f"DeepSeek 写作模型不可用：{config.DEEPSEEK_MODEL}")
    ledger_store.stage(date_bjt, category, "preflight", "completed", config.DEEPSEEK_MODEL)

    candidates = fetch_category(category)
    ledger_store.stage(date_bjt, category, "collection", "completed", f"{len(candidates)} candidates")
    selected = select_articles(candidates, category, store.published_story_ids(), claimed_ids, now=now)
    if not selected:
        ledger_store.finish(date_bjt, category, "skipped", error="72 小时内没有可发布事件")
        raise InsufficientContent(f"{config.CATEGORIES[category].name}在 72 小时内没有可发布事件")
    if claimed_ids is not None:
        claimed_ids.update(item.id for item in selected)
        claimed_ids.update(event_fingerprint(item.title) for item in selected)
    corroboration_by_story = _prepare(selected, candidates)
    packs = build_fact_packs(selected, candidates, corroboration_by_story)
    ledger_store.stage(date_bjt, category, "fact_pack", "completed", f"{len(packs)} stories")
    story_set = DailyStorySet(category, now.strftime("%Y-%m-%d"), selected, packs)
    brief = build_content_brief(category, now.strftime("%Y-%m-%d"), packs)
    try:
        qwen_ready = siliconflow_model_available(config.PREP_MODEL)
    except Exception:
        qwen_ready = False
    ledger_store.stage(date_bjt, category, "content_brief", "completed" if qwen_ready else "fallback", config.PREP_MODEL if qwen_ready else "local FactPack")

    print("  [agent] 独立生成图文版")
    reading = generate_reading(category, selected, packs, brief)
    print("  [agent] 独立生成播客版")
    podcast = generate_podcast(category, packs, brief)
    ledger_store.stage(date_bjt, category, "writing", "completed", config.DEEPSEEK_MODEL)
    stamp = now_bjt_iso()
    bundle = EpisodeBundle(
        episode_id=episode_id, schema_version=4, category=category,
        category_name=config.CATEGORIES[category].name, date_bjt=now.strftime("%Y-%m-%d"),
        story_set=story_set, reading=reading, podcast=podcast,
        created_at_bjt=stamp, updated_at_bjt=stamp,
    )
    episode_dir = store.episode_dir(episode_id)
    episode_dir.mkdir(parents=True, exist_ok=True)
    print("  [images] 缓存来源图片并补齐题图")
    resolve_story_images(category, selected, reading, episode_dir)
    image_kinds = sorted({item.image_kind or "unknown" for item in selected})
    ledger_store.stage(date_bjt, category, "images", "completed", ", ".join(image_kinds))
    store.save_bundle(bundle)
    write_json(episode_dir / "story_set.json", story_set.to_dict())
    write_json(episode_dir / "content_brief.json", brief.to_dict())

    audit_errors = audit_editions(reading, podcast, packs, brief)
    ledger_store.stage(date_bjt, category, "audit", "completed" if not audit_errors else "failed", "；".join(audit_errors[:3]))
    if not skip_audio and not audit_errors:
        print("  [tts] 生成完整双声音频")
        try:
            bundle.podcast = generate_podcast_audio(bundle.podcast, category, episode_dir, {pack.story_id: pack.headline for pack in packs})
            ledger_store.stage(date_bjt, category, "tts", "completed", bundle.podcast.tts_provider)
        except Exception as exc:
            audit_errors.append(f"音频生成失败：{exc}")
            ledger_store.stage(date_bjt, category, "tts", "failed", str(exc))
        store.save_bundle(bundle)
    report = evaluate_bundle(bundle, audit_errors, require_audio=not skip_audio)
    store.save_quality(report)
    store.transition(episode_id, "quality_passed" if report.publishable else "failed")
    ledger_store.stage(date_bjt, category, "quality", "completed" if report.publishable else "failed", "；".join(report.errors[:3]))
    ledger_store.finish(date_bjt, category, "quality_passed" if report.publishable else "failed", episode_id, "；".join(report.errors[:3]))
    print(f"  [quality] {'PASS' if report.publishable else 'BLOCKED'}")
    return store.load_bundle(episode_id)


def generate_all(*, force: bool = False, retry_failed_only: bool = False, skip_audio: bool = False) -> list[EpisodeBundle]:
    claimed: set[str] = set()
    result: list[EpisodeBundle] = []
    failures: dict[str, str] = {}
    date_bjt = now_bjt().strftime("%Y-%m-%d")
    ledger_store = RunLedgerStore()
    categories = ledger_store.retry_categories(date_bjt) if retry_failed_only else list(config.CATEGORIES)
    for category in categories:
        try:
            result.append(generate_category(category, force=force, retry_failed=retry_failed_only, skip_audio=skip_audio, claimed_ids=claimed, ledger_store=ledger_store))
        except InsufficientContent as exc:
            print(f"  [skipped] {category}: {exc}")
        except Exception as exc:
            failures[category] = str(exc)
            ledger_store.finish(date_bjt, category, "failed", error=str(exc))
            print(f"  [failed] {category}: {exc}")
    write_json(config.DATA_DIR / "last_generation.json", {"at_bjt": now_bjt_iso(), "failures": failures, "episodes": [item.episode_id for item in result]})
    anomaly = usage_anomaly(now_bjt().strftime("%Y-%m-%d"))
    if anomaly:
        send_ops_card("伊恩每日 · 模型用量异常", anomaly)
    publishable = [item for item in result if item.status in {"quality_passed", "published"}]
    if not publishable:
        raise RuntimeError("今天没有频道通过质量门禁")
    return result


def retry_failed(date_bjt: str | None = None, *, skip_audio: bool = False) -> list[EpisodeBundle]:
    today = now_bjt().strftime("%Y-%m-%d")
    if date_bjt and date_bjt != today:
        raise ValueError("只能重试今天的失败频道")
    return generate_all(retry_failed_only=True, skip_audio=skip_audio)
