from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config
from .storage import write_json

BJT = timezone(timedelta(hours=8))
_SILICONFLOW_MODELS: set[str] | None = None


def _value(usage: object, name: str) -> int:
    return int(getattr(usage, name, 0) or 0)


def _record(provider: str, model: str, category: str, stage: str, usage: object, elapsed: float) -> None:
    now = datetime.now(BJT)
    prompt = _value(usage, "prompt_tokens")
    completion = _value(usage, "completion_tokens")
    details = getattr(usage, "prompt_tokens_details", None)
    hit = _value(usage, "prompt_cache_hit_tokens") or _value(details, "cached_tokens")
    miss = _value(usage, "prompt_cache_miss_tokens") or max(0, prompt - hit)
    usd = hit / 1_000_000 * 0.0028 + miss / 1_000_000 * 0.14 + completion / 1_000_000 * 0.28 if provider == "deepseek" else 0.0
    path = config.USAGE_DIR / f"{now:%Y-%m-%d}.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, ValueError, TypeError):
        rows = []
    rows.append({
        "at_bjt": now.isoformat(timespec="seconds"), "provider": provider, "model": model,
        "category": category, "stage": stage, "prompt_tokens": prompt,
        "cache_hit_tokens": hit, "cache_miss_tokens": miss, "completion_tokens": completion,
        "estimated_usd": round(usd, 6), "estimated_cny": round(usd * 7.2, 6),
        "latency_sec": round(elapsed, 3),
    })
    write_json(path, rows)


def _parse(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(line for line in cleaned.splitlines() if not line.strip().startswith("```"))
    start, end = cleaned.find("{"), cleaned.rfind("}")
    candidate = cleaned[start:end + 1] if start >= 0 and end > start else cleaned
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        from json_repair import repair_json
        repaired = repair_json(candidate, return_objects=True)
        if not isinstance(repaired, dict):
            raise ValueError("模型输出不是 JSON 对象")
        return repaired


def generate_json(provider: str, model: str, system: str, payload: dict[str, Any], *, category: str, stage: str, max_tokens: int, temperature: float) -> dict[str, Any]:
    from openai import OpenAI

    if provider == "deepseek":
        key, base, extra = config.require_deepseek_key(), config.DEEPSEEK_BASE_URL, {"thinking": {"type": "disabled"}}
    elif provider == "siliconflow":
        if not config.SILICONFLOW_API_KEY:
            raise RuntimeError("SILICONFLOW_API_KEY is required")
        key, base, extra = config.SILICONFLOW_API_KEY, config.SILICONFLOW_BASE_URL, {"enable_thinking": False}
    else:
        raise ValueError(f"未知模型供应商：{provider}")
    started = time.perf_counter()
    response = OpenAI(api_key=key, base_url=base).chat.completions.create(
        model=model, max_tokens=max_tokens, temperature=temperature,
        response_format={"type": "json_object"}, extra_body=extra,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    _record(provider, model, category, stage, response.usage, time.perf_counter() - started)
    return _parse(response.choices[0].message.content)


def usage_report(date: str | None = None, days: int = 1) -> dict[str, Any]:
    end = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=BJT) if date else datetime.now(BJT)
    rows: list[dict[str, Any]] = []
    for offset in range(max(1, days)):
        path = config.USAGE_DIR / f"{end - timedelta(days=offset):%Y-%m-%d}.json"
        if path.exists():
            rows.extend(json.loads(path.read_text(encoding="utf-8")))
    return {
        "calls": len(rows), "prompt_tokens": sum(row.get("prompt_tokens", 0) for row in rows),
        "cache_hit_tokens": sum(row.get("cache_hit_tokens", 0) for row in rows),
        "completion_tokens": sum(row.get("completion_tokens", 0) for row in rows),
        "estimated_cny": round(sum(row.get("estimated_cny", 0) for row in rows), 4), "entries": rows,
    }


def siliconflow_model_available(model: str) -> bool:
    global _SILICONFLOW_MODELS
    if not config.SILICONFLOW_API_KEY:
        return False
    if _SILICONFLOW_MODELS is not None:
        return model in _SILICONFLOW_MODELS
    import httpx
    response = httpx.get(f"{config.SILICONFLOW_BASE_URL}/models", headers={"Authorization": f"Bearer {config.SILICONFLOW_API_KEY}"}, timeout=20)
    response.raise_for_status()
    _SILICONFLOW_MODELS = {item.get("id") for item in response.json().get("data", []) if item.get("id")}
    return model in _SILICONFLOW_MODELS


def usage_anomaly(date: str | None = None) -> str:
    today = usage_report(date, 1)
    history = usage_report((datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d") if date else (datetime.now(BJT) - timedelta(days=1)).strftime("%Y-%m-%d"), 7)
    if not history["calls"]:
        return "" if today["calls"] <= 15 else f"模型调用异常：今天 {today['calls']} 次，超过正常上限 15 次"
    average_tokens = (history["prompt_tokens"] + history["completion_tokens"]) / 7
    today_tokens = today["prompt_tokens"] + today["completion_tokens"]
    if average_tokens and today_tokens > average_tokens * 2:
        return f"模型 token 异常：今天 {today_tokens}，近 7 日均值 {average_tokens:.0f}"
    return ""
