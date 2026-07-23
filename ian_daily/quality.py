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

    if not 1 <= story_count <= 5:
        errors.append(f"合格事件应为 1—5 条，当前为 {story_count} 条")
    if bundle.category in {"education", "sports"}:
        required_domestic = min(3, story_count)
        if domestic_count < required_domestic:
            warnings.append(f"国内事件未达到优先目标：期望 {required_domestic} 条，当前 {domestic_count} 条")

    pack_ids = {item.story_id for item in bundle.story_set.fact_packs}
    reading_ids = {item.story_id for item in bundle.reading.sections}
    podcast_ids = {item.story_id for item in bundle.podcast.blocks if item.role == "story" and item.story_id}
    aligned = pack_ids & reading_ids & podcast_ids
    alignment = len(aligned) / len(pack_ids) if pack_ids else 0
    if alignment < 1:
        errors.append("图文版与播客版没有完整覆盖同一组事件")

    for index, section in enumerate(bundle.reading.sections, 1):
        if not section.image_url:
            errors.append(f"图文第 {index} 章没有有效配图")
        if not section.source_refs:
            errors.append(f"图文第 {index} 章没有可追溯来源")
        if bundle.schema_version >= 4 and (not section.image_status or not section.image_phash):
            errors.append(f"图文第 {index} 章缺少图片来源状态或去重指纹")
        if _length(section.body) < 350:
            errors.append(f"图文第 {index} 章分析不足 350 字")
        if re.search(r"(?<![A-Za-z])\d{2,}(?![A-Za-z])", section.body) and len({source.source for source in section.source_refs}) < 2:
            errors.append(f"图文第 {index} 章含数字但不足两个独立来源")
    image_hashes = [section.image_phash for section in bundle.reading.sections if section.image_phash]
    if len(image_hashes) != len(set(image_hashes)):
        errors.append("同一期存在重复事件配图")
    minimum_reading_chars = max(500, story_count * 400)
    minimum_podcast_chars = {1: 1000, 2: 1700, 3: 2500, 4: 3400, 5: 3800}.get(story_count, 1000)
    if reading_chars < minimum_reading_chars:
        errors.append(f"图文版过短：{reading_chars} 字，当前事件量至少需要 {minimum_reading_chars} 字")
    if podcast_chars < minimum_podcast_chars:
        errors.append(f"播客内容过短：{podcast_chars} 字，当前事件量至少需要 {minimum_podcast_chars} 字")

    listeners = [block for block in bundle.podcast.blocks if block.speaker == "listener"]
    minimum_listeners = 1 if story_count == 1 else 2
    if not minimum_listeners <= len(listeners) <= 3:
        errors.append(f"听众提问应为 {minimum_listeners}—3 次，当前 {len(listeners)} 次")
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
        else:
            minimum_duration, maximum_duration = {
                1: (180, 480),
                2: (300, 660),
                3: (480, 840),
                4: (660, 1080),
                5: (780, 1080),
            }.get(story_count, (180, 1080))
            if not minimum_duration <= duration <= maximum_duration:
                errors.append(
                    f"音频时长 {duration / 60:.1f} 分钟，不在当前事件量对应的 "
                    f"{minimum_duration / 60:.0f}—{maximum_duration / 60:.0f} 分钟范围内"
                )
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
