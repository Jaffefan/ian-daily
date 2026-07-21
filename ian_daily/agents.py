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


def build_fact_packs(selected: list[Article], all_candidates: list[Article]) -> list[FactPack]:
    packs: list[FactPack] = []
    for article in selected:
        corroboration = related_articles(article, all_candidates, limit=3)
        sources = [article, *corroboration]
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
    return ReadingEdition(
        title=str(data.get("title") or f"伊恩每日·{profile.name}").strip(),
        lead=str(data.get("lead") or "").strip(),
        sections=sections,
        synthesis=str(data.get("synthesis") or "").strip(),
    )


def generate_podcast(category: str, packs: list[FactPack]) -> PodcastEpisode:
    profile = config.CATEGORIES[category]
    system = f"""{IAN_CONSTITUTION}

你正在独立创作「伊恩每日·{profile.name}」约 15 分钟的完整播客栏目。它与图文版共享事件和事实边界，但你看不到图文稿，也不得写成逐章念稿。
播客方法：{profile.podcast_lens}
语气：{profile.tone}
禁止：{profile.exclusions}

节目必须有：建立当日主题的开场；按顺序故事化解读 {len(packs)} 个事件；2—3 次听众提问或质疑；跨事件主题复盘；自然收束。
伊恩负责所有事实和核心判断。听众问题由第二声音提出，每次不超过 70 个中文字符，不得引入新事实。
伊恩块 speaker=ian，听众块 speaker=listener。role 仅可为 opening、story、question、answer、synthesis、closing。
每个事件至少一个 story 块，story_id 必须来自事实包；问题和回答可带对应 story_id。整体文本目标 3300—4300 中文字符。
输出 JSON：title、description、blocks。blocks 每项含 block_id、speaker、role、text、story_id。"""
    data = _generate(system, {"fact_packs": _pack_payload(packs)}, 0.68)
    story_ids = {pack.story_id for pack in packs}
    blocks: list[AudioBlock] = []
    for index, raw in enumerate(data.get("blocks") or []):
        speaker = "listener" if raw.get("speaker") == "listener" else "ian"
        role = str(raw.get("role") or "story")
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
    covered = {block.story_id for block in blocks if block.role == "story"}
    missing = story_ids - covered
    if missing:
        raise ValueError(f"播客未覆盖全部事件：{', '.join(sorted(missing))}")
    return PodcastEpisode(
        title=str(data.get("title") or f"伊恩每日·{profile.name}").strip(),
        description=str(data.get("description") or "").strip(),
        blocks=blocks,
    )


def audit_editions(reading: ReadingEdition, podcast: PodcastEpisode, packs: list[FactPack]) -> list[str]:
    system = f"""你是独立事实审校员。只依据事实包检查图文版和播客版中的数字、日期、人名、引语、因果、赛况与政策条款。
不要评价文风。公众评论不能作事实。输出 JSON：errors，值为具体且可定位的问题数组；没有问题时返回空数组。"""
    result = _generate(system, {
        "fact_packs": _pack_payload(packs),
        "reading": {"sections": [{"story_id": s.story_id, "body": s.body} for s in reading.sections]},
        "podcast": {"blocks": [{"block_id": b.block_id, "story_id": b.story_id, "text": b.text} for b in podcast.blocks]},
    }, 0.0)
    return [str(item) for item in result.get("errors", []) if str(item).strip()]
