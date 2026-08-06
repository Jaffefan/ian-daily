from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path

from . import config
from .models import Article, ReadingEdition


def _save_webp(content: bytes, target: Path) -> bool:
    try:
        from PIL import Image
        with Image.open(BytesIO(content)) as image:
            image.load()
            if image.width < 320 or image.height < 180:
                return False
            image = image.convert("RGB")
            image.thumbnail((1600, 1200))
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, "WEBP", quality=84, method=6)
        return target.stat().st_size > 1000
    except Exception:
        return False


def _download(url: str, target: Path, referer: str = "") -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    try:
        import httpx
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        response = httpx.get(url, timeout=30, follow_redirects=True, headers=headers)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if content_type and not (content_type.startswith("image/") or "octet-stream" in content_type):
            return False
        if len(response.content) > 12_000_000:
            return False
        return _save_webp(response.content, target)
    except Exception:
        return False


def build_gimi_illustration_prompt(article: Article, category: str, article_text: str = "") -> str:
    """Translate an article into a Gimi-style editorial illustration brief."""
    styles = {
        "tech": (
            "产品方案式编辑插画",
            "用真实设备、工作场景和产业关系表现技术如何落地，结构清晰、理性克制",
        ),
        "education": (
            "暖调绘本式编辑插画",
            "用学校、家庭或学习现场中的具体人物关系表现影响，温和但不粉饰问题",
        ),
        "sports": (
            "怪诞手绘式动态编辑插画",
            "用关键动作、场地和战术关系形成清楚动线，明快有现场感但不虚构赛况",
        ),
    }
    style_name, style_direction = styles[category]
    source = re.sub(r"\s+", " ", " ".join((article.title, article.summary, article.full_body, article_text))).strip()
    source = source[:1800]
    return (
        "请根据下列新闻内容创作一张与事件直接相关的中文深度文章配图。"
        f"采用Gimi配图工作流的{style_name}，无固定IP角色，横向16:9构图。"
        f"视觉方向：{style_direction}。"
        "先确定一个能让读者立即理解事件的核心场景，再用二至三个真实可推导的物件或环境细节补充证据；"
        "画面需要有明确的前景、中景、背景和从主体到影响对象的阅读顺序。"
        "只能表现文章已经提供的事实与影响，不得杜撰人物身份、比赛结果、产品外观、校徽、机构标志或现场细节。"
        "不要使用无关图库意象，不要拼贴多个互不相干的场景。"
        "无文字、无字母、无数字、无Logo、无水印、无界面截图。自然色彩，适合公众号长文。"
        f"文章内容：{source}"
    )


def _generate(article: Article, category: str, target: Path, article_text: str = "") -> bool:
    if not config.SILICONFLOW_API_KEY:
        return False
    try:
        import httpx
        prompt = build_gimi_illustration_prompt(article, category, article_text)
        response = httpx.post(
            f"{config.SILICONFLOW_BASE_URL}/images/generations",
            headers={"Authorization": f"Bearer {config.SILICONFLOW_API_KEY}"},
            json={"model": config.IMAGE_MODEL, "prompt": prompt, "negative_prompt": "text, letters, logo, watermark, UI screenshot", "image_size": "1024x1024", "batch_size": 1},
            timeout=180,
        )
        response.raise_for_status()
        url = response.json().get("images", [{}])[0].get("url", "")
        return _download(url, target)
    except Exception as exc:
        print(f"  [image-ai-warning] {article.title[:30]}: {exc}")
        return False


def _phash(path: Path) -> str:
    from PIL import Image
    with Image.open(path) as image:
        reduced = image.convert("L").resize((8, 8))
        pixels = list(reduced.get_flattened_data() if hasattr(reduced, "get_flattened_data") else reduced.getdata())
    average = sum(pixels) / len(pixels)
    return f"{sum((1 << index) for index, value in enumerate(pixels) if value >= average):016x}"


def _distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _fallback(article: Article, category: str, target: Path, salt: int = 0) -> None:
    from PIL import Image, ImageDraw
    colors = {"tech": (0, 140, 122), "education": (58, 107, 53), "sports": (228, 87, 46)}
    accent = colors[category]
    image = Image.new("RGB", (1200, 760), (244, 241, 233))
    draw = ImageDraw.Draw(image)
    digest = hashlib.sha256(f"{article.title}|{salt}".encode("utf-8")).digest()
    for index in range(7):
        x = 45 + digest[index] * 4
        width = 90 + digest[index + 7] * 2
        shade = tuple(min(255, channel + index * 11) for channel in accent)
        draw.rectangle((x % 1020, 55 + index * 92, min(1170, x % 1020 + width), 105 + index * 92), fill=shade)
    radius = 90 + digest[15] % 100
    center_x = 220 + int.from_bytes(digest[16:18], "big") % 760
    center_y = 180 + int.from_bytes(digest[18:20], "big") % 400
    draw.ellipse((center_x - radius, center_y - radius, center_x + radius, center_y + radius), outline=accent, width=18)
    draw.line((70, 690, 1130, 690 - digest[20]), fill=accent, width=8)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "WEBP", quality=84, method=6)


def _usable_source_url(url: str) -> bool:
    return bool(
        url.startswith(("http://", "https://"))
        and "googleusercontent.com" not in url
        and "gstatic.com" not in url
    )


def resolve_story_images(
    category: str,
    articles: list[Article],
    reading: ReadingEdition,
    episode_dir: Path,
    only_story_ids: set[str] | None = None,
) -> None:
    from .sources import discover_article_images

    section_by_id = {section.story_id: section for section in reading.sections}
    only_story_ids = only_story_ids or {article.id for article in articles}
    seen_hashes = [
        section.image_phash
        for section in reading.sections
        if section.story_id not in only_story_ids and section.image_phash
    ]
    for article in articles:
        if article.id not in only_story_ids:
            continue
        section = section_by_id[article.id]
        filename = hashlib.sha256(article.id.encode("utf-8")).hexdigest()[:16] + ".webp"
        target = episode_dir / "images" / filename
        source_url = article.image_url if article.image_url.startswith(("http://", "https://")) else article.image_source_url
        candidates: list[tuple[str, str, str]] = []
        if _usable_source_url(source_url):
            candidates.append((source_url, article.source, article.url))
        candidates.extend(discover_article_images(article))
        downloaded = False
        credit = article.image_credit or article.source
        for candidate_url, candidate_credit, referer in candidates:
            if _download(candidate_url, target, referer):
                source_url = candidate_url
                credit = candidate_credit
                downloaded = True
                break
        kind = "source"
        status = "downloaded"
        if not downloaded:
            if _generate(article, category, target, f"{section.title} {section.dek} {section.body}"):
                credit = "AI 生成 · Gimi 配图工作流 · 伊恩每日"
                kind = "ai"
                status = "generated"
            else:
                _fallback(article, category, target)
                credit = "伊恩每日 · 本地题图"
                kind = "fallback"
                status = "source_unavailable"
        image_hash = _phash(target)
        if any(_distance(image_hash, existing) <= 4 for existing in seen_hashes):
            for salt in range(1, 6):
                _fallback(article, category, target, salt)
                image_hash = _phash(target)
                if all(_distance(image_hash, existing) > 4 for existing in seen_hashes):
                    break
            credit = "伊恩每日 · 本地事件题图"
            kind = "fallback"
            status = "deduplicated"
        seen_hashes.append(image_hash)
        relative = f"images/{filename}"
        article.image_url = relative
        article.image_credit = credit
        article.image_kind = kind
        article.image_source_url = source_url
        article.image_status = status
        article.image_phash = image_hash
        section.image_url = relative
        section.image_credit = credit
        section.image_kind = kind
        section.image_source_url = source_url
        section.image_status = status
        section.image_phash = image_hash


def backfill_story_images(store=None) -> dict[str, int]:
    from .storage import EpisodeStore

    store = store or EpisodeStore()
    result = {"episodes": 0, "attempted": 0, "replaced": 0}
    for bundle in store.list_bundles({"published"}):
        fallback_ids = {
            section.story_id
            for section in bundle.reading.sections
            if section.image_kind == "fallback"
        }
        if not fallback_ids:
            continue
        before = {
            section.story_id: section.image_kind
            for section in bundle.reading.sections
            if section.story_id in fallback_ids
        }
        resolve_story_images(
            bundle.category,
            bundle.story_set.articles,
            bundle.reading,
            store.episode_dir(bundle.episode_id),
            only_story_ids=fallback_ids,
        )
        store.save_bundle(bundle)
        result["episodes"] += 1
        result["attempted"] += len(fallback_ids)
        result["replaced"] += sum(
            before.get(section.story_id) == "fallback" and section.image_kind != "fallback"
            for section in bundle.reading.sections
        )
    return result
