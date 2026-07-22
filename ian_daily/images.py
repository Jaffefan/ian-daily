from __future__ import annotations

import hashlib
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


def _download(url: str, target: Path) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    try:
        import httpx
        response = httpx.get(url, timeout=30, follow_redirects=True, headers={"User-Agent": "IanDaily/3.0"})
        response.raise_for_status()
        if len(response.content) > 12_000_000:
            return False
        return _save_webp(response.content, target)
    except Exception:
        return False


def _generate(article: Article, category: str, target: Path) -> bool:
    if not config.SILICONFLOW_API_KEY:
        return False
    try:
        import httpx
        prompt = (
            f"Editorial documentary illustration for a Chinese {category} analysis article about: {article.title}. "
            "Specific real-world scene, human scale, restrained magazine photography, natural colors, no text, no logo, no watermark."
        )
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


def _fallback(category: str, target: Path) -> None:
    from PIL import Image, ImageDraw
    colors = {"tech": (0, 140, 122), "education": (58, 107, 53), "sports": (228, 87, 46)}
    accent = colors[category]
    image = Image.new("RGB", (1200, 760), (244, 241, 233))
    draw = ImageDraw.Draw(image)
    for index in range(9):
        inset = 55 + index * 34
        color = tuple(min(255, channel + index * 10) for channel in accent)
        draw.rectangle((inset, inset, 1200 - inset, 760 - inset), outline=color, width=5)
    draw.ellipse((470, 250, 730, 510), fill=accent)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "WEBP", quality=84, method=6)


def resolve_story_images(category: str, articles: list[Article], reading: ReadingEdition, episode_dir: Path) -> None:
    section_by_id = {section.story_id: section for section in reading.sections}
    for article in articles:
        section = section_by_id[article.id]
        filename = hashlib.sha256(article.id.encode("utf-8")).hexdigest()[:16] + ".webp"
        target = episode_dir / "images" / filename
        credit = article.image_credit or article.source
        if not _download(article.image_url, target):
            if _generate(article, category, target):
                credit = "AI 生成 · 伊恩每日"
            else:
                _fallback(category, target)
                credit = "伊恩每日 · 本地题图"
        relative = f"images/{filename}"
        article.image_url = relative
        article.image_credit = credit
        section.image_url = relative
        section.image_credit = credit
