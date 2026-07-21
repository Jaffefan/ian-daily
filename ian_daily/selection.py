from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import Article
from .sources import event_fingerprint


BJT = timezone(timedelta(hours=8))


def _age_hours(article: Article, now: datetime) -> float:
    try:
        published = datetime.fromisoformat(article.published_at_bjt)
        if published.tzinfo is None:
            published = published.replace(tzinfo=BJT)
        return max(0.0, (now - published.astimezone(BJT)).total_seconds() / 3600)
    except ValueError:
        return 999.0


def score_article(article: Article, now: datetime) -> float:
    age = _age_hours(article, now)
    freshness = max(0.0, 72.0 - age) / 12.0
    authority = {1: 6.0, 2: 3.5, 3: 1.5}.get(article.authority_tier, 0.5)
    substance = min(len(article.summary), 600) / 200
    engagement = min(max(article.engagement, 0), 5000) / 1000
    return round(freshness + authority + substance + engagement, 3)


def select_articles(
    candidates: list[Article],
    category: str | None = None,
    history_ids: set[str] | None = None,
    claimed_ids: set[str] | None = None,
    now: datetime | None = None,
    target_count: int = 5,
) -> list[Article]:
    now = now or datetime.now(BJT)
    excluded = set(history_ids or ()) | set(claimed_ids or ())
    eligible = [
        article for article in candidates
        if article.id not in excluded
        and event_fingerprint(article.title) not in excluded
        and _age_hours(article, now) <= 72
    ]
    ranked = sorted(eligible, key=lambda a: score_article(a, now), reverse=True)
    recent = [a for a in ranked if _age_hours(a, now) <= 24]
    older = [a for a in ranked if 24 < _age_hours(a, now) <= 72]
    ordered = [*recent, *older]
    category = category or (ordered[0].category if ordered else "")
    if category not in {"education", "sports"}:
        return ordered[:target_count]

    domestic = [item for item in ordered if item.region == "domestic"]
    global_items = [item for item in ordered if item.region != "domestic"]
    if len(domestic) >= 3 and len(global_items) >= 2:
        return [*domestic[:3], *global_items[:2]]
    if len(domestic) >= 2 and len(global_items) >= 2:
        return [*domestic[:2], *global_items[:2]]
    return []


def is_72h_fill(article: Article, now: datetime | None = None) -> bool:
    now = now or datetime.now(BJT)
    return _age_hours(article, now) > 24
