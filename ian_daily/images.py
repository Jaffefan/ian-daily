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


def resolve_story_images(category: str, articles: list[Article], reading: ReadingEdition, episode_dir: Path) -> None:
    from .sources import discover_article_image

    section_by_id = {section.story_id: section for section in reading.sections}
    seen_hashes: list[str] = []
    for article in articles:
        section = section_by_id[article.id]
        filename = hashlib.sha256(article.id.encode("utf-8")).hexdigest()[:16] + ".webp"
        target = episode_dir / "images" / filename
        source_url = article.image_url if article.image_url.startswith(("http://", "https://")) else article.image_source_url
        if not source_url:
            source_url = discover_article_image(article)
        credit = article.source if source_url else (article.image_credit or article.source)
        kind = "source"
        status = "downloaded"
        if not _download(source_url, target, article.url):
            if _generate(article, category, target):
                credit = "AI 生成 · 伊恩每日"
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
