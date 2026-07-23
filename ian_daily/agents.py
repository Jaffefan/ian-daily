from __future__ import annotations

import re
from typing import Any

from . import config
from .model_api import generate_json, siliconflow_model_available
from .models import (
    Article, AudioBlock, BriefStory, ContentBrief, FactPack, PodcastEpisode,
    ReadingEdition, ReadingSection, SourceRef,
)
from .sources import related_articles

IAN_CONSTITUTION = """你是中文播客主持人和作者伊恩。聪明、清醒、把复杂事情讲简单，称呼受众为「你」。
先陈述可核对事实再表达判断。不得创造数字、引语、赛况、政策条款或因果。公众评论不能作为事实。
自然、具体，不念新闻稿，不堆术语，不使用空洞热词。"""


def _text_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def build_fact_packs(selected: list[Article], all_candidates: list[Article], corroboration_by_story: dict[str, list[Article]] | None = None) -> list[FactPack]:
    packs: list[FactPack] = []
    corroboration_by_story = corroboration_by_story or {}
    for article in selected:
        candidates = [article, *corroboration_by_story.get(article.id, []), *related_articles(article, all_candidates, limit=3)]
        sources: list[Article] = []
        seen_urls: set[str] = set()
        seen_publishers: set[str] = set()
        for source in candidates:
            if source.url in seen_urls or source.source in seen_publishers:
                continue
            sources.append(source); seen_urls.add(source.url); seen_publishers.add(source.source)
            if len(sources) >= 4:
                break
        body = article.full_body or article.summary
        facts = [part.strip() for part in re.split(r"\n+|(?<=[。！？!?])\s+", body) if len(part.strip()) >= 20]
        packs.append(FactPack(
            article.id, article.title, [item[:500] for item in (facts[:8] or [article.summary or article.title])],
            [SourceRef(item.id, item.title, item.source, item.url, item.published_at_bjt, item.authority_tier) for item in sources],
            [] if article.full_body else ["未取得完整正文，只能使用来源摘要"], article.community_signals[:2],
        ))
    return packs


def _local_brief(category: str, date_bjt: str, packs: list[FactPack]) -> ContentBrief:
    stories = []
    for pack in packs:
        facts = [re.sub(r"\s+", " ", fact).strip()[:360] for fact in pack.facts[:5]]
        numeric = [fact for fact in facts if re.search(r"\d", fact)][:4]
        stories.append(BriefStory(pack.story_id, pack.headline, facts, numeric, pack.uncertainties, [], pack.sources))
    return ContentBrief(category, date_bjt, stories)


def build_content_brief(category: str, date_bjt: str, packs: list[FactPack]) -> ContentBrief:
    fallback = _local_brief(category, date_bjt, packs)
    try:
        if not siliconflow_model_available(config.PREP_MODEL):
            return fallback
        data = generate_json(
            "siliconflow", config.PREP_MODEL,
            "你是事实压缩编辑。只能压缩输入，不得补充外部知识。保留关键事实、数字边界、不确定性和普通人影响线索。输出 JSON。",
            {"category": category, "date_bjt": date_bjt, "stories": [{"story_id": p.story_id, "headline": p.headline, "facts": p.facts, "uncertainties": p.uncertainties} for p in packs]},
            category=category, stage="content_brief", max_tokens=2600, temperature=0.0,
        )
        raw_by_id = {str(item.get("story_id")): item for item in data.get("stories", [])}
        stories: list[BriefStory] = []
        for base in fallback.stories:
            raw = raw_by_id.get(base.story_id, {})
            facts = [str(item).strip()[:380] for item in raw.get("facts", []) if str(item).strip()] or base.facts
            stories.append(BriefStory(
                base.story_id, base.headline, facts[:6],
                [str(item).strip()[:180] for item in raw.get("numeric_claims", []) if str(item).strip()][:5] or base.numeric_claims,
                [str(item).strip()[:180] for item in raw.get("uncertainties", []) if str(item).strip()] or base.uncertainties,
                [str(item).strip()[:180] for item in raw.get("impact_angles", []) if str(item).strip()][:4], base.sources,
            ))
        return ContentBrief(category, date_bjt, stories, str(data.get("shared_theme") or "").strip(), [str(item) for item in data.get("risk_flags", [])])
    except Exception as exc:
        print(f"  [brief-fallback] {category}: {exc}")
        return fallback


def _writer_system(category: str) -> str:
    profile = config.CATEGORIES[category]
    return f"""{IAN_CONSTITUTION}
你正在创作「伊恩每日·{profile.name}」。选题方向：{profile.selection_focus}。分析方法：{profile.reading_lens}。
播客方法：{profile.podcast_lens}。语气：{profile.tone}。禁止：{profile.exclusions}。
ContentBrief 是唯一事实边界。输出严格 JSON。"""


def _writer(category: str, stage: str, brief: ContentBrief, task: dict[str, Any], max_tokens: int, temperature: float) -> dict[str, Any]:
    return generate_json(
        "deepseek", config.DEEPSEEK_MODEL, _writer_system(category),
        {"content_brief": brief.to_dict(), "task": task}, category=category,
        stage=stage, max_tokens=max_tokens, temperature=temperature,
    )


def generate_reading(category: str, selected: list[Article], packs: list[FactPack], brief: ContentBrief | None = None) -> ReadingEdition:
    brief = brief or _local_brief(category, "", packs)
    task = {
        "edition": "公众号式图文版，不是口播稿", "story_count": len(packs),
        "requirements": "按顺序每事件一章，每章450至700中文字；背景、变化、机制、普通人影响、行动建议齐全；单一来源数字改为非精确表达；正文无Markdown小标题",
        "output": "title, lead, synthesis, sections；section含story_id,title,dek,body,takeaway",
    }
    data = _writer(category, "reading", brief, task, 5600, 0.55)
    raw_by_id = {str(item.get("story_id")): item for item in data.get("sections", [])}
    invalid = [pack.story_id for pack in packs if pack.story_id not in raw_by_id or _text_length(str(raw_by_id[pack.story_id].get("body") or "")) < 350]
    if invalid:
        data = _writer(category, "reading_retry", brief, {
            **task,
            "repair": f"上一版以下章节缺失或不足350字：{','.join(invalid)}。保留事实边界，完整返回全部章节；每章至少450字。",
            "previous_draft": data,
        }, 6200, 0.35)
    article_by_id = {item.id: item for item in selected}
    pack_by_id = {item.story_id: item for item in packs}
    raw_by_id = {str(item.get("story_id")): item for item in data.get("sections", [])}
    sections: list[ReadingSection] = []
    for pack in packs:
        raw = raw_by_id.get(pack.story_id)
        if not raw:
            raise ValueError(f"图文缺少事件：{pack.story_id}")
        body = str(raw.get("body") or "").strip()
        if _text_length(body) < 350:
            raise ValueError(f"图文章节过短：{pack.story_id}")
        if len({source.source for source in pack.sources}) < 2:
            body = _remove_residual_numeric_precision(body)
        article = article_by_id[pack.story_id]
        sections.append(ReadingSection(
            pack.story_id, str(raw.get("title") or pack.headline).strip(), str(raw.get("dek") or article.summary).strip(),
            body, str(raw.get("takeaway") or "继续观察后续变化").strip(), article.image_url, article.image_credit,
            [source.article_id for source in pack.sources], list(pack.sources),
        ))
    return ReadingEdition(str(data.get("title") or f"伊恩每日·{config.CATEGORIES[category].name}").strip(), str(data.get("lead") or "").strip(), sections, str(data.get("synthesis") or "").strip())


def generate_podcast(category: str, packs: list[FactPack], brief: ContentBrief | None = None) -> PodcastEpisode:
    brief = brief or _local_brief(category, "", packs)
    count = len(packs)
    minimum_chars = {5: 3800, 4: 3400, 3: 2500, 2: 1700, 1: 1000}[count]
    target = "3900至4600" if count >= 4 else {3: "2700至3400", 2: "1900至2600", 1: "1100至1700"}[count]
    questions = "1至2" if count == 1 else "2至3"
    task = {
        "edition": "完整声音播客，不朗读图文", "story_count": count,
        "requirements": f"有主题开场、按顺序故事化解读、{questions}次听众提问与伊恩回答、跨事件复盘和收束；每事件一个story块；总字数{target}",
        "roles": "opening,story,question,answer,synthesis,closing；speaker只能ian或listener；听众问题不超过70字",
        "output": "title,description,blocks；block含block_id,speaker,role,text,story_id",
    }
    data = _writer(category, "podcast", brief, task, 6200, 0.68)
    story_ids = {pack.story_id for pack in packs}
    def parse_blocks(payload: dict[str, Any]) -> list[AudioBlock]:
        result: list[AudioBlock] = []
        for index, raw in enumerate(payload.get("blocks", [])):
            role = str(raw.get("role") or "story")
            speaker = "listener" if raw.get("speaker") == "listener" else "ian"
            story_id = str(raw.get("story_id") or "")
            if story_id not in story_ids:
                story_id = ""
            result.append(AudioBlock(str(raw.get("block_id") or f"block-{index + 1:02d}"), speaker, role, str(raw.get("text") or "").strip(), story_id))
        return result
    blocks = parse_blocks(data)
    covered = {block.story_id for block in blocks if block.role == "story" and block.story_id}
    current_chars = sum(_text_length(block.text) for block in blocks)
    issues = []
    if covered != story_ids:
        issues.append(f"缺少事件：{','.join(sorted(story_ids - covered))}")
    if current_chars < minimum_chars:
        issues.append(f"总字数只有{current_chars}，至少需要{minimum_chars}")
    if issues:
        data = _writer(category, "podcast_retry", brief, {
            **task,
            "repair": "；".join(issues) + "。保留已有事实和栏目结构，完整重写并返回全部 blocks。",
            "previous_draft": data,
        }, 7600, 0.45)
        blocks = parse_blocks(data)
    if {block.story_id for block in blocks if block.role == "story" and block.story_id} != story_ids:
        raise ValueError("播客没有完整覆盖 ContentBrief 事件")
    final_chars = sum(_text_length(block.text) for block in blocks)
    if final_chars < minimum_chars:
        raise ValueError(f"播客内容过短：{final_chars} 字，至少需要 {minimum_chars} 字")
    return PodcastEpisode(str(data.get("title") or f"伊恩每日·{config.CATEGORIES[category].name}").strip(), str(data.get("description") or "").strip(), blocks)


def audit_editions(reading: ReadingEdition, podcast: PodcastEpisode, packs: list[FactPack], brief: ContentBrief | None = None) -> list[str]:
    brief = brief or _local_brief("", "", packs)
    try:
        if not siliconflow_model_available(config.PREP_MODEL):
            return []
        result = generate_json(
            "siliconflow", config.PREP_MODEL,
            "你是独立事实与栏目审校员。只依据ContentBrief检查数字、人名、赛况、政策、引语和因果；同时按5分制评估事实、观点、频道辨识度、可理解度、情绪风格。输出JSON：blocking_errors和rubric_scores。任何评分必须给出整数。",
            {"content_brief": brief.to_dict(), "reading": [section.body for section in reading.sections], "podcast": [block.text for block in podcast.blocks]},
            category=brief.category, stage="audit", max_tokens=1800, temperature=0.0,
        )
        errors = [str(item).strip() for item in result.get("blocking_errors", []) if str(item).strip()]
        labels = {
            "facts": "事实支撑", "viewpoint": "观点质量", "category_identity": "频道辨识度",
            "clarity": "可理解度", "tone": "情绪风格",
        }
        scores = result.get("rubric_scores", {})
        for key, label in labels.items():
            try:
                score = int(scores.get(key, 0))
            except (TypeError, ValueError):
                score = 0
            if score < 4:
                errors.append(f"Agent 校准未通过：{label} {score}/5")
        return errors
    except Exception as exc:
        print(f"  [audit-fallback] {brief.category}: {exc}")
        return []


def _remove_residual_numeric_precision(text: str) -> str:
    replacements = (
        (r"(?:19|20)\d{2}年", "本年度"), (r"\d{1,2}月\d{1,2}日", "近期"),
        (r"\d+(?:\.\d+)?%", "相关比例"), (r"\d+\s*(?:亿元|万元|元|美元|人民币)", "相关金额"),
        (r"\d+\s*[:：比-]\s*\d+", "具体比分"), (r"(?<![A-Za-z])\d{2,}(?![A-Za-z])", "相关数量"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text
