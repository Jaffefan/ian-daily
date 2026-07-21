from __future__ import annotations

import re

from .models import EpisodeBundle, QualityReport


def _length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _ngrams(text: str, size: int = 10) -> set[str]:
    clean = re.sub(r"[^\w\u4e00-\u9fff]", "", text.lower())
    return {clean[index:index + size] for index in range(max(0, len(clean) - size + 1))}


def evaluate_bundle(bundle: EpisodeBundle, audit_errors: list[str] | None = None, require_audio: bool = True) -> QualityReport:
    errors = [f"事实审校：{item}" for item in (audit_errors or [])]
    warnings: list[str] = []
    story_count = len(bundle.story_set.articles)
    domestic_count = sum(item.region == "domestic" for item in bundle.story_set.articles)
    source_ids = {source.article_id for pack in bundle.story_set.fact_packs for source in pack.sources}
    reading_chars = _length(bundle.reading.lead + bundle.reading.synthesis + "".join(s.body for s in bundle.reading.sections))
    podcast_chars = _length("".join(block.text for block in bundle.podcast.blocks))

    if story_count not in {4, 5}:
        errors.append(f"合格事件应为 4—5 条，当前为 {story_count} 条")
    if bundle.category in {"education", "sports"}:
        required_domestic = 3 if story_count == 5 else 2
        if domestic_count < required_domestic:
            errors.append(f"国内事件不足：需要 {required_domestic} 条，当前 {domestic_count} 条")

    pack_ids = {item.story_id for item in bundle.story_set.fact_packs}
    reading_ids = {item.story_id for item in bundle.reading.sections}
    podcast_ids = {item.story_id for item in bundle.podcast.blocks if item.role == "story" and item.story_id}
    aligned = pack_ids & reading_ids & podcast_ids
    alignment = len(aligned) / len(pack_ids) if pack_ids else 0
    if alignment < 1:
        errors.append("图文版与播客版没有完整覆盖同一组事件")

    for index, section in enumerate(bundle.reading.sections, 1):
        if not section.source_refs:
            errors.append(f"图文第 {index} 章没有可追溯来源")
        if _length(section.body) < 350:
            errors.append(f"图文第 {index} 章分析不足 350 字")
        if re.search(r"\d", section.body) and len({source.source for source in section.source_refs}) < 2:
            errors.append(f"图文第 {index} 章含数字但不足两个独立来源")
    if reading_chars < 2000:
        errors.append(f"图文版过短：{reading_chars} 字")
    if podcast_chars < 2800:
        errors.append(f"播客内容过短：{podcast_chars} 字")

    listeners = [block for block in bundle.podcast.blocks if block.speaker == "listener"]
    if not 2 <= len(listeners) <= 3:
        errors.append(f"听众提问应为 2—3 次，当前 {len(listeners)} 次")
    if any(_length(block.text) > 70 for block in listeners):
        errors.append("听众提问超过 70 字")
    if len({block.speaker for block in bundle.podcast.blocks}) < 2:
        errors.append("播客缺少第二声音")

    reading_grams = _ngrams("".join(section.body for section in bundle.reading.sections))
    podcast_grams = _ngrams("".join(block.text for block in bundle.podcast.blocks))
    overlap = len(reading_grams & podcast_grams) / max(1, min(len(reading_grams), len(podcast_grams)))
    if overlap > 0.25:
        errors.append(f"图文与播客存在大段复用：{overlap:.0%}")

    duration = bundle.podcast.total_duration_sec
    if require_audio:
        if not bundle.podcast.full_audio_file or duration <= 0:
            errors.append("缺少完整播客音频")
        elif not 780 <= duration <= 1080:
            errors.append(f"音频时长 {duration / 60:.1f} 分钟，不在 13—18 分钟门禁内")
        if not bundle.podcast.chapters:
            errors.append("缺少音频章节时间轴")

    return QualityReport(
        episode_id=bundle.episode_id,
        publishable=not errors,
        story_count=story_count,
        source_count=len(source_ids),
        domestic_count=domestic_count,
        reading_chars=reading_chars,
        podcast_chars=podcast_chars,
        audio_duration_sec=round(duration, 1),
        fact_alignment=round(alignment, 3),
        text_overlap=round(overlap, 3),
        errors=errors,
        warnings=warnings,
    )
