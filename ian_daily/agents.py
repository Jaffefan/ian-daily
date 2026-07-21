from __future__ import annotations

import json
import re
from typing import Any

from . import config
from .models import (
    Article, AudioBlock, FactPack, PodcastEpisode, ReadingEdition,
    ReadingSection, SourceRef,
)
from .sources import related_articles


IAN_CONSTITUTION = """你是中文播客主持人和作者伊恩。你聪明、清醒、能把复杂事情讲简单，称呼受众为「你」。
先陈述可以核对的事实，再表达判断；判断必须回到提供的事实包。不得创造数字、引语、赛况、政策条款或因果关系。
公众评论只能作为明确标注的平台观点，不能作为事实。使用自然中文，不念新闻稿，不堆术语，不使用空洞热词。
博主案例只用于提炼分析方法，不模仿任何具体个人的口癖、固定句式或标志性表达。"""


def build_fact_packs(
    selected: list[Article],
    all_candidates: list[Article],
    corroboration_by_story: dict[str, list[Article]] | None = None,
) -> list[FactPack]:
    packs: list[FactPack] = []
    corroboration_by_story = corroboration_by_story or {}
    for article in selected:
        direct = corroboration_by_story.get(article.id, [])
        related = related_articles(article, all_candidates, limit=3)
        source_candidates = [article, *direct, *related]
        sources: list[Article] = []
        seen_urls: set[str] = set()
        seen_publishers: set[str] = set()
        for source in source_candidates:
            if source.url in seen_urls or source.source in seen_publishers:
                continue
            sources.append(source)
            seen_urls.add(source.url)
            seen_publishers.add(source.source)
            if len(sources) >= 4:
                break
        body = article.full_body or article.summary
        facts = [part.strip() for part in re.split(r"\n+|(?<=[。！？!?])\s+", body) if len(part.strip()) >= 20]
        packs.append(FactPack(
            story_id=article.id,
            headline=article.title,
            facts=[item[:700] for item in (facts[:10] or [article.summary or article.title])],
            sources=[SourceRef(
                article_id=item.id, title=item.title, source=item.source, url=item.url,
                published_at_bjt=item.published_at_bjt, authority_tier=item.authority_tier,
            ) for item in sources],
            uncertainties=[] if article.full_body else ["未取得完整正文，只能使用来源摘要"],
            community_signals=article.community_signals[:3],
        ))
    return packs


def _client():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("生成内容需要安装 openai") from exc
    return OpenAI(api_key=config.require_deepseek_key(), base_url=config.DEEPSEEK_BASE_URL)


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(line for line in cleaned.splitlines() if not line.strip().startswith("```"))
    start, end = cleaned.find("{"), cleaned.rfind("}")
    candidate = cleaned[start:end + 1] if start >= 0 and end > start else cleaned
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json
            repaired = repair_json(candidate, return_objects=True)
            if isinstance(repaired, dict):
                return repaired
        except Exception:
            pass
        raise ValueError("模型输出不是可解析的 JSON")


def _generate(system: str, payload: dict[str, Any], temperature: float = 0.55) -> dict[str, Any]:
    response = _client().chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        max_tokens=16384,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    return _parse_json(response.choices[0].message.content)


def _pack_payload(packs: list[FactPack]) -> list[dict[str, Any]]:
    return [pack.to_dict() for pack in packs]


def generate_reading(category: str, selected: list[Article], packs: list[FactPack]) -> ReadingEdition:
    profile = config.CATEGORIES[category]
    system = f"""{IAN_CONSTITUTION}

你正在独立创作「伊恩每日·{profile.name}」的公众号式图文版。这不是播客逐字稿，也不要写任何口播提示。
选题方向：{profile.selection_focus}
分析方法：{profile.reading_lens}
语气：{profile.tone}
禁止：{profile.exclusions}

按事实包顺序写 {len(packs)} 章，每章 450—700 个中文字符，包含背景、核心变化、独立分析、普通人影响、可执行建议或后续观察。
每章必须严格对应一个 story_id，source_ids 只能使用该事实包中的 article_id。正文不能用 Markdown 小标题。
输出 JSON：title、lead、sections、synthesis。sections 每项含 story_id、title、dek、body、takeaway、source_ids。"""
    data = _generate(system, {"fact_packs": _pack_payload(packs)}, 0.55)
    article_by_id = {item.id: item for item in selected}
    pack_by_id = {pack.story_id: pack for pack in packs}
    sections: list[ReadingSection] = []
    for index, raw in enumerate(data.get("sections") or []):
        fallback = packs[min(index, len(packs) - 1)]
        story_id = raw.get("story_id") if raw.get("story_id") in pack_by_id else fallback.story_id
        pack = pack_by_id[story_id]
        allowed = {source.article_id: source for source in pack.sources}
        ids = [item for item in raw.get("source_ids", []) if item in allowed] or [pack.sources[0].article_id]
        article = article_by_id[story_id]
        sections.append(ReadingSection(
            story_id=story_id,
            title=str(raw.get("title") or pack.headline).strip(),
            dek=str(raw.get("dek") or article.summary).strip(),
            body=str(raw.get("body") or "").strip(),
            takeaway=str(raw.get("takeaway") or "").strip(),
            image_url=article.image_url,
            image_credit=article.image_credit,
            source_ids=ids,
            source_refs=[allowed[item] for item in ids],
        ))
    if len(sections) != len(packs):
        raise ValueError(f"图文版章节数量应为 {len(packs)}，实际为 {len(sections)}")
    edition = ReadingEdition(
        title=str(data.get("title") or f"伊恩每日·{profile.name}").strip(),
        lead=str(data.get("lead") or "").strip(),
        sections=sections,
        synthesis=str(data.get("synthesis") or "").strip(),
    )
    edition = deepen_reading(category, edition, packs)
    pack_by_id = {pack.story_id: pack for pack in packs}
    for section in edition.sections:
        pack = pack_by_id[section.story_id]
        section.source_ids = [source.article_id for source in pack.sources]
        section.source_refs = list(pack.sources)
    return edition


def deepen_reading(category: str, edition: ReadingEdition, packs: list[FactPack]) -> ReadingEdition:
    if all(len(re.sub(r"\s+", "", section.body)) >= 480 for section in edition.sections):
        return edition
    profile = config.CATEGORIES[category]
    system = f"""{IAN_CONSTITUTION}

你是「伊恩每日·{profile.name}」图文版的深度编辑。根据事实包扩写现有章节，不增加事实包以外的新事实。
每章正文必须达到 480—650 个去空格后的中文字符，保留原判断方向，并进一步解释机制、现实代价、普通人影响和可执行观察。
如果某个数字只有一个来源，不重复或放大该数字，改用不带精确数字的边界表达。
输出 JSON：sections，每项只含 story_id 和 body；story_id 与输入完全一致。"""
    result = _generate(system, {
        "analysis_lens": profile.reading_lens,
        "fact_packs": _pack_payload(packs),
        "sections": [{"story_id": item.story_id, "body": item.body} for item in edition.sections],
    }, 0.4)
    replacements = {str(item.get("story_id")): str(item.get("body") or "").strip() for item in result.get("sections", [])}
    pack_by_id = {pack.story_id: pack for pack in packs}
    for section in edition.sections:
        replacement = replacements.get(section.story_id, "")
        if len(re.sub(r"\s+", "", replacement)) >= 450:
            section.body = replacement
        pack = pack_by_id[section.story_id]
        for _ in range(2):
            current_length = len(re.sub(r"\s+", "", section.body))
            if current_length >= 480:
                break
            addition_result = _generate(
                f"""{IAN_CONSTITUTION}
你是{profile.name}图文版的续写编辑。只补充一段与现有正文自然衔接的深度分析，不复述新闻，不引入事实包外信息。
补充机制、现实代价、普通人影响或可执行观察。addition 写 220—320 个中文字符，禁止小标题。输出 JSON：addition。""",
                {"fact_pack": pack.to_dict(), "existing_body": section.body},
                0.38,
            )
            addition = str(addition_result.get("addition") or "").strip()
            if len(re.sub(r"\s+", "", addition)) < 80:
                break
            section.body = f"{section.body}\n\n{addition}"
        if re.search(r"(?<![A-Za-z])\d{2,}(?![A-Za-z])", section.body):
            existing = {source.source for source in section.source_refs}
            for source in pack.sources:
                if source.source not in existing:
                    section.source_ids.append(source.article_id)
                    section.source_refs.append(source)
                    existing.add(source.source)
                if len(existing) >= 2:
                    break
    return edition


def generate_podcast(category: str, packs: list[FactPack]) -> PodcastEpisode:
    profile = config.CATEGORIES[category]
    story_count = len(packs)
    if story_count >= 4:
        format_description, text_target, question_target = "约 15 分钟的完整播客栏目", "3300—4300", "2—3"
    elif story_count == 3:
        format_description, text_target, question_target = "约 8—14 分钟的短一期播客栏目", "2400—3300", "2—3"
    elif story_count == 2:
        format_description, text_target, question_target = "约 5—11 分钟的短一期播客栏目", "1700—2500", "2—3"
    else:
        format_description, text_target, question_target = "约 3—8 分钟的单主题播客栏目", "1000—1700", "1—2"
    system = f"""{IAN_CONSTITUTION}

你正在独立创作「伊恩每日·{profile.name}」{format_description}。它与图文版共享事件和事实边界，但你看不到图文稿，也不得写成逐章念稿。
播客方法：{profile.podcast_lens}
语气：{profile.tone}
禁止：{profile.exclusions}

节目必须有：建立当日主题的开场；按顺序故事化解读 {story_count} 个事件；{question_target} 次听众提问或质疑；跨事件主题复盘；自然收束。
伊恩负责所有事实和核心判断。听众问题由第二声音提出，每次不超过 70 个中文字符，不得引入新事实。
伊恩块 speaker=ian，听众块 speaker=listener。role 仅可为 opening、story、question、answer、synthesis、closing。
每个事件至少一个 story 块，story_id 必须来自事实包；问题和回答可带对应 story_id。整体文本目标 {text_target} 中文字符。
输出 JSON：title、description、blocks。blocks 每项含 block_id、speaker、role、text、story_id。"""
    data = _generate(system, {"fact_packs": _pack_payload(packs)}, 0.68)
    story_order = [pack.story_id for pack in packs]
    story_ids = set(story_order)
    allowed_roles = {"opening", "story", "question", "answer", "synthesis", "closing"}
    blocks: list[AudioBlock] = []
    for index, raw in enumerate(data.get("blocks") or []):
        speaker = "listener" if raw.get("speaker") == "listener" else "ian"
        role = str(raw.get("role") or "story").lower()
        if role not in allowed_roles:
            role = "question" if speaker == "listener" else "story"
        story_id = str(raw.get("story_id") or "")
        if story_id not in story_ids:
            story_id = ""
        blocks.append(AudioBlock(
            block_id=str(raw.get("block_id") or f"block-{index + 1:02d}"),
            speaker=speaker,
            role=role,
            text=str(raw.get("text") or "").strip(),
            story_id=story_id,
        ))
    if not blocks:
        raise ValueError("播客生成结果没有音频块")
    assigned: set[str] = set()
    for block in blocks:
        if block.role != "story":
            continue
        if block.story_id not in story_ids or block.story_id in assigned:
            replacement_id = next((item for item in story_order if item not in assigned), "")
            if not replacement_id:
                block.role = "answer"
                block.story_id = next((item for item in reversed(story_order) if item in assigned), "")
                continue
            block.story_id = replacement_id
        if block.story_id:
            assigned.add(block.story_id)
    covered = {block.story_id for block in blocks if block.role == "story"}
    missing = story_ids - covered
    for story_id in story_order:
        if story_id not in missing:
            continue
        pack = next(item for item in packs if item.story_id == story_id)
        recovered = _generate(
            f"""{IAN_CONSTITUTION}
你正在补回「伊恩每日·{profile.name}」播客中缺失的一个事件段落。只依据这个 FactPack 写完整的声音叙事。
从具体场景进入，讲清事实、冲突、机制、人的处境和普通人影响，最后给出有边界的伊恩判断。
不得使用小标题，不得引入新数字、引语、赛况或因果。text 写 720—900 个中文字符。输出 JSON：text。""",
            {"fact_pack": pack.to_dict(), "podcast_lens": profile.podcast_lens},
            0.5,
        )
        text = str(recovered.get("text") or "").strip()
        if len(re.sub(r"\s+", "", text)) < 300:
            continue
        recovered_block = AudioBlock(
            block_id=f"recovered-{story_id}", speaker="ian", role="story",
            text=text, story_id=story_id,
        )
        insert_at = next((index for index, block in enumerate(blocks) if block.role in {"synthesis", "closing"}), len(blocks))
        blocks.insert(insert_at, recovered_block)
        covered.add(story_id)
    if missing:
        missing = story_ids - covered
    if missing:
        raise ValueError(f"播客未覆盖全部事件：{', '.join(sorted(missing))}")
    episode = PodcastEpisode(
        title=str(data.get("title") or f"伊恩每日·{profile.name}").strip(),
        description=str(data.get("description") or "").strip(),
        blocks=blocks,
    )
    return deepen_podcast(category, episode, packs)


def deepen_podcast(category: str, episode: PodcastEpisode, packs: list[FactPack]) -> PodcastEpisode:
    total = len(re.sub(r"\s+", "", "".join(block.text for block in episode.blocks)))
    story_blocks = [block for block in episode.blocks if block.role == "story"]
    target_total = {1: 1200, 2: 1900, 3: 2700, 4: 3600, 5: 4000}.get(len(packs), 4000)
    if total >= target_total and all(len(re.sub(r"\s+", "", block.text)) >= 680 for block in story_blocks):
        return episode
    profile = config.CATEGORIES[category]
    system = f"""{IAN_CONSTITUTION}

你是「伊恩每日·{profile.name}」播客的深度制作编辑。图文稿不可见；只基于事实包和现有播客块补足声音叙事。
每个 story 文本写到 720—850 个去空格后的中文字符：从具体场景进入，解释事实、冲突、机制、普通人代价，并给出有边界的伊恩判断。
不要改成文章腔，不要使用小标题，不要复述同一句新闻。opening 120—180 字，synthesis 320—450 字，closing 100—160 字。
不能增加事实包之外的数字、引语、赛况或因果。输出 JSON：stories、opening、synthesis、closing；stories 每项只含 story_id 和 text。"""
    result = _generate(system, {
        "podcast_lens": profile.podcast_lens,
        "fact_packs": _pack_payload(packs),
        "stories": [{"story_id": block.story_id, "text": block.text} for block in story_blocks],
        "opening": next((block.text for block in episode.blocks if block.role == "opening"), ""),
        "synthesis": next((block.text for block in episode.blocks if block.role == "synthesis"), ""),
        "closing": next((block.text for block in episode.blocks if block.role == "closing"), ""),
    }, 0.52)
    replacements = {str(item.get("story_id")): str(item.get("text") or "").strip() for item in result.get("stories", [])}
    for block in story_blocks:
        replacement = replacements.get(block.story_id, "")
        if len(re.sub(r"\s+", "", replacement)) >= 650:
            block.text = replacement
        pack = next(item for item in packs if item.story_id == block.story_id)
        target_length = 860 if category == "sports" else 700
        for _ in range(2):
            current_length = len(re.sub(r"\s+", "", block.text))
            if current_length >= target_length:
                break
            addition_result = _generate(
                f"""{IAN_CONSTITUTION}
你是{profile.name}播客的续写制作人。只补充一段能直接接在现有口播后的声音叙事，不写文章小标题，不复述新闻，不引入事实包外信息。
补充冲突、机制、人的处境、普通人代价或有边界的伊恩判断。addition 写 260—380 个中文字符。输出 JSON：addition。""",
                {"fact_pack": pack.to_dict(), "existing_audio_script": block.text},
                0.48,
            )
            addition = str(addition_result.get("addition") or "").strip()
            if len(re.sub(r"\s+", "", addition)) < 100:
                break
            block.text = f"{block.text}\n\n{addition}"
    for role in ("opening", "synthesis", "closing"):
        replacement = str(result.get(role) or "").strip()
        target = next((block for block in episode.blocks if block.role == role), None)
        if target and replacement:
            target.text = replacement
    return episode


def audit_editions(reading: ReadingEdition, podcast: PodcastEpisode, packs: list[FactPack]) -> list[str]:
    system = """你是独立事实审校员。只依据事实包检查图文版和播客版中的数字、日期、人名、引语、因果、赛况与政策条款。
不要评价文风，不要把「与事实一致」「列举不完整但没有声称完整」写成问题。公众评论不能作事实。
可通过删除、降级确定性或改写解决的问题，必须在 corrections 中给出修正后的完整正文，不得放入 blocking_errors。
只有素材本身无法支持整条事件、无法通过改写修复时，才写入 blocking_errors。
输出 JSON：reading_corrections、podcast_corrections、blocking_errors。reading_corrections 每项含 story_id、body；podcast_corrections 每项含 block_id、text。"""
    result = _generate(system, {
        "fact_packs": _pack_payload(packs),
        "reading": {"sections": [{"story_id": s.story_id, "body": s.body} for s in reading.sections]},
        "podcast": {"blocks": [{"block_id": b.block_id, "story_id": b.story_id, "text": b.text} for b in podcast.blocks]},
    }, 0.0)
    reading_by_id = {section.story_id: section for section in reading.sections}
    podcast_by_id = {block.block_id: block for block in podcast.blocks}
    for item in result.get("reading_corrections", []):
        target = reading_by_id.get(str(item.get("story_id") or ""))
        corrected = str(item.get("body") or "").strip()
        if target and len(re.sub(r"\s+", "", corrected)) >= 350:
            target.body = corrected
    for item in result.get("podcast_corrections", []):
        target = podcast_by_id.get(str(item.get("block_id") or ""))
        corrected = str(item.get("text") or "").strip()
        if target and len(re.sub(r"\s+", "", corrected)) >= 100:
            target.text = corrected
    pack_by_id = {pack.story_id: pack for pack in packs}
    numeric_claim = re.compile(r"(?<![A-Za-z])\d{2,}(?![A-Za-z])")
    for section in reading.sections:
        pack = pack_by_id[section.story_id]
        if len({source.source for source in pack.sources}) >= 2 or not numeric_claim.search(section.body):
            continue
        sanitized = _generate(
            """你是事实审校员。这个事件目前只有一个可信来源，因此不能保留无法交叉核对的精确数字。
在不改变事件、分析角度和篇幅层次的前提下，把阿拉伯数字、精确日期、精确比分、金额和数量改成来源边界清楚的非精确表达。
不得增加新事实，正文保持至少 350 个中文字符。输出 JSON：body。""",
            {"fact_pack": pack.to_dict(), "body": section.body},
            0.0,
        )
        corrected = str(sanitized.get("body") or "").strip()
        if len(re.sub(r"\s+", "", corrected)) < 350:
            continue
        corrected = _remove_residual_numeric_precision(corrected)
        if not numeric_claim.search(corrected):
            section.body = corrected
    return [str(item) for item in result.get("blocking_errors", []) if str(item).strip()]


def _remove_residual_numeric_precision(text: str) -> str:
    """Remove precise numeric residue after a single-source model rewrite."""
    replacements = (
        (r"(?:19|20)\d{2}年", "本年度"),
        (r"\d{1,2}月\d{1,2}日", "近期"),
        (r"\d+(?:\.\d+)?%", "相关比例"),
        (r"\d+\s*(?:亿元|万元|元|美元|人民币)", "相关金额"),
        (r"\d+\s*[:：比-]\s*\d+", "具体比分"),
        (r"(?<![A-Za-z])\d{2,}(?![A-Za-z])", "相关数量"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text
