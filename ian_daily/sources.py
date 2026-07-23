from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote, quote_plus, urljoin, urlsplit, urlunsplit

from .config import CATEGORIES, Feed
from .models import Article, CommunitySignal


BJT = timezone(timedelta(hours=8))
USER_AGENT = "IanDaily/2.0 (+https://github.com/Jaffefan/ian-daily)"


def canonical_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
    except ValueError:
        return url.strip()


def story_fingerprint(title: str, url: str = "") -> str:
    clean_url = canonical_url(url)
    if clean_url:
        material = clean_url
    else:
        material = re.sub(r"[^\w\u4e00-\u9fff]+", "", title.lower())[:80]
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def event_fingerprint(title: str) -> str:
    tokens = sorted(_title_tokens(title))
    material = "|".join(tokens[:24]) or re.sub(r"\W+", "", title.lower())[:60]
    return "event-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _published_at(entry: object) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        value = getattr(entry, key, None)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc).astimezone(BJT)
    for key in ("published", "updated"):
        value = getattr(entry, key, "")
        if value:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(BJT)
            except (TypeError, ValueError, OverflowError):
                continue
    return datetime.now(BJT)


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def _image_url(entry: object) -> str:
    thumbnails = getattr(entry, "media_thumbnail", None) or []
    if thumbnails and thumbnails[0].get("url"):
        return thumbnails[0]["url"]
    content = getattr(entry, "media_content", None) or []
    for item in content:
        if item.get("url") and str(item.get("medium", "")).lower() in {"", "image"}:
            return item["url"]
    summary = getattr(entry, "summary", "") or ""
    match = re.search(r'<img[^>]+src=["\']([^"\']+)', summary, re.I)
    return match.group(1) if match else ""


class _ImageMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag.lower() == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"}:
                self.candidates.append(values.get("content", ""))
        elif tag.lower() == "link" and "image_src" in values.get("rel", "").lower():
            self.candidates.append(values.get("href", ""))


def _meta_image(value: str, base_url: str = "") -> str:
    parser = _ImageMetadataParser()
    try:
        parser.feed(value)
    except Exception:
        pass
    for candidate in parser.candidates:
        resolved = urljoin(base_url, html.unescape(candidate).strip())
        if resolved.startswith(("http://", "https://")):
            return resolved
    return ""


def discover_article_image(article: Article) -> str:
    try:
        import httpx
        response = httpx.get(article.url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
        response.raise_for_status()
        return _meta_image(response.text, str(response.url))
    except Exception:
        return ""


def discover_article_images(article: Article, limit: int = 6) -> list[tuple[str, str, str]]:
    """Return image URL, credit and referer candidates for a story."""
    candidates: list[tuple[str, str, str]] = []
    direct = discover_article_image(article)
    if direct:
        candidates.append((direct, article.source, article.url))

    try:
        from ddgs import DDGS

        results = DDGS().news(article.title, max_results=limit)
        for item in results:
            page_url = canonical_url(item.get("url", ""))
            if not page_url:
                continue
            credit = item.get("source") or urlsplit(page_url).netloc
            image_url = item.get("image") or ""
            if image_url:
                candidates.append((image_url, credit, page_url))
            discovered = discover_article_image(Article(
                id=article.id,
                category=article.category,
                title=item.get("title") or article.title,
                summary="",
                url=page_url,
                source=credit,
                published_at_bjt=article.published_at_bjt,
                language=article.language,
                region=article.region,
                authority_tier=article.authority_tier,
            ))
            if discovered:
                candidates.append((discovered, credit, page_url))
    except Exception:
        pass

    unique: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for image_url, credit, referer in candidates:
        if image_url and image_url not in seen:
            seen.add(image_url)
            unique.append((image_url, credit, referer))
    return unique


def fetch_feed(category: str, feed: Feed) -> list[Article]:
    try:
        import feedparser
    except ImportError as exc:
        raise RuntimeError("The feedparser package is required for RSS collection") from exc
    parsed = feedparser.parse(feed.url, request_headers={"User-Agent": USER_AGENT})
    articles: list[Article] = []
    for entry in parsed.entries[:20]:
        title = _strip_html(entry.get("title", ""))
        url = entry.get("link", "").strip()
        if not title or not url:
            continue
        summary = _strip_html(entry.get("summary", "") or entry.get("description", ""))[:1000]
        published = _published_at(entry)
        entry_source = entry.get("source") or {}
        source_name = entry_source.get("title") if isinstance(entry_source, dict) else ""
        articles.append(Article(
            id=story_fingerprint(title, url),
            category=category,
            title=title,
            summary=summary,
            url=canonical_url(url),
            source=source_name or feed.name,
            published_at_bjt=published.isoformat(timespec="seconds"),
            language=feed.language,
            region=feed.region,
            authority_tier=feed.authority_tier,
            image_url=_image_url(entry),
            image_credit=source_name or feed.name,
        ))
    return articles


def fetch_category(category: str) -> list[Article]:
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category: {category}")
    articles: list[Article] = []
    for feed in CATEGORIES[category].feeds:
        try:
            articles.extend(fetch_feed(category, feed))
        except Exception as exc:
            print(f"  [source] {category}/{feed.name}: {exc}")
    unique: dict[str, Article] = {}
    for article in articles:
        existing = unique.get(article.id)
        if existing is None or article.authority_tier < existing.authority_tier:
            unique[article.id] = article
    return list(unique.values())


def fetch_corroborating_articles(article: Article, limit: int = 5) -> list[Article]:
    query_text = " ".join(article.title.split()[:14])
    try:
        from ddgs import DDGS

        results = DDGS().news(query_text, max_results=limit)
        articles = []
        for item in results:
            title = _strip_html(item.get("title", ""))
            url = canonical_url(item.get("url", ""))
            if not title or not url or url == article.url:
                continue
            try:
                published = datetime.fromisoformat(item.get("date", "").replace("Z", "+00:00")).astimezone(BJT)
            except (TypeError, ValueError):
                published = datetime.now(BJT)
            articles.append(Article(
                id=story_fingerprint(title, url),
                category=article.category,
                title=title,
                summary=_strip_html(item.get("body", ""))[:1000],
                url=url,
                source=item.get("source") or urlsplit(url).netloc,
                published_at_bjt=published.isoformat(timespec="seconds"),
                language=article.language,
                region=article.region,
                authority_tier=2,
                image_url=item.get("image") or "",
                image_credit=item.get("source") or urlsplit(url).netloc,
            ))
        if articles:
            return articles[:limit]
    except Exception:
        pass

    query = quote_plus(query_text)
    if article.language == "zh":
        url = f"https://news.google.com/rss/search?q={query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    else:
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    feed = Feed("Google News corroboration", url, article.language, article.region, 2)
    matches = fetch_feed(article.category, feed)
    related = related_articles(article, matches, limit=limit)
    return related or matches[:limit]


def enrich_article(article: Article, max_chars: int = 7000) -> Article:
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("The httpx package is required for article enrichment") from exc
    headers = {"User-Agent": USER_AGENT}
    body = ""
    try:
        response = httpx.get(f"https://r.jina.ai/{article.url}", headers=headers, timeout=20, follow_redirects=True)
        if response.status_code == 200 and len(response.text) >= 300:
            body = response.text[:max_chars]
    except httpx.HTTPError:
        pass
    try:
        response = httpx.get(article.url, headers=headers, timeout=20, follow_redirects=True)
        if response.status_code == 200 and len(response.text) >= 300:
            if not article.image_url:
                article.image_url = _meta_image(response.text, str(response.url))
                if article.image_url:
                    article.image_credit = article.source
            if not body:
                body = _strip_html(response.text)[:max_chars]
    except httpx.HTTPError:
        pass
    if body:
        article.full_body = body
        return article
    article.full_body = article.summary
    return article


def fetch_community_signals(article: Article, limit: int = 2) -> list[CommunitySignal]:
    try:
        import httpx
    except ImportError:
        return []
    query = quote(" ".join(article.title.split()[:10]))
    url = f"https://www.reddit.com/search.json?q={query}&sort=relevance&t=month&limit={limit}"
    try:
        response = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=12, follow_redirects=True)
        if response.status_code != 200:
            return []
        signals = []
        for child in response.json().get("data", {}).get("children", []):
            data = child.get("data", {})
            text = (data.get("title") or "").strip()
            permalink = data.get("permalink") or ""
            if text and permalink:
                signals.append(CommunitySignal(
                    platform="Reddit",
                    text=text[:300],
                    url=f"https://www.reddit.com{permalink}",
                    engagement=int(data.get("score") or 0),
                ))
        return signals[:limit]
    except (httpx.HTTPError, ValueError, TypeError):
        return []


def _title_tokens(title: str) -> set[str]:
    latin = set(re.findall(r"[a-z0-9]{3,}", title.lower()))
    chinese = re.sub(r"[^\u4e00-\u9fff]", "", title)
    bigrams = {chinese[i:i + 2] for i in range(max(0, len(chinese) - 1))}
    return latin | bigrams


def related_articles(target: Article, candidates: list[Article], limit: int = 2) -> list[Article]:
    target_tokens = _title_tokens(target.title)
    scored: list[tuple[float, Article]] = []
    for candidate in candidates:
        if candidate.id == target.id or candidate.source == target.source:
            continue
        other = _title_tokens(candidate.title)
        union = target_tokens | other
        score = len(target_tokens & other) / len(union) if union else 0.0
        if score >= 0.12:
            scored.append((score, candidate))
    return [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[:limit]]
