from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import config
from .model_api import usage_report
from .storage import EpisodeStore

BJT = timezone(timedelta(hours=8))


def _chars(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True))


def estimate_legacy_input_chars(date_bjt: str, store: EpisodeStore | None = None) -> dict[str, int]:
    """Reproduce the cdd2d59 payload shape without making legacy API calls."""
    store = store or EpisodeStore()
    result: dict[str, int] = {}
    for bundle in store.list_bundles():
        if bundle.date_bjt != date_bjt:
            continue
        packs = [item.to_dict() for item in bundle.story_set.fact_packs]
        reading = [section.body for section in bundle.reading.sections]
        podcast = [block.text for block in bundle.podcast.blocks]
        base = _chars(packs)
        # cdd2d59: reading, optional whole-reading deepening, podcast, merged audit,
        # plus numeric sanitation for each single-source chapter.
        total = base * 3 + _chars({"reading": reading, "podcast": podcast})
        if any(len("".join(section.body.split())) < 480 for section in bundle.reading.sections):
            total += base + _chars(reading)
        for section in bundle.reading.sections:
            if len({source.source for source in section.source_refs}) < 2 and any(char.isdigit() for char in section.body):
                total += base + len(section.body)
        result[bundle.category] = total
    return result


def cost_benchmark(date_bjt: str | None = None, store: EpisodeStore | None = None) -> dict:
    date_bjt = date_bjt or datetime.now(BJT).strftime("%Y-%m-%d")
    usage = usage_report(date_bjt, 1)
    legacy = estimate_legacy_input_chars(date_bjt, store)
    current_by_category = {
        category: sum(row.get("input_chars", 0) for row in usage["entries"] if row.get("category") == category)
        for category in config.CATEGORIES
    }
    categories = {}
    for category in config.CATEGORIES:
        old_chars = legacy.get(category, 0)
        new_chars = current_by_category.get(category, 0)
        categories[category] = {
            "legacy_estimated_input_chars": old_chars,
            "new_actual_input_chars": new_chars,
            "estimated_reduction": round(1 - new_chars / old_chars, 4) if old_chars and new_chars else None,
            "new_calls": usage["by_category"][category]["calls"],
            "new_actual_tokens": usage["by_category"][category]["tokens"],
        }
    valid = [item["estimated_reduction"] for item in categories.values() if item["estimated_reduction"] is not None]
    return {
        "date_bjt": date_bjt,
        "baseline_commit": "cdd2d59",
        "method": "legacy payload-shape estimate compared with actual new usage; no legacy API calls",
        "categories": categories,
        "target_reduction": 0.70,
        "passes_target": bool(valid) and all(value >= 0.70 for value in valid),
    }
