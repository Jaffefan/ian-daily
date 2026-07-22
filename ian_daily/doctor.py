from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config
from .audio import _ffmpeg
from .model_api import deepseek_model_available, siliconflow_model_available, siliconflow_model_info
from .feishu import send_ops_card
from .operations import RunLedgerStore
from .storage import now_bjt


@dataclass(slots=True)
class CheckResult:
    name: str
    status: str
    detail: str
    blocking: bool = False
    fallback: str = ""


def _check(name: str, action, *, blocking: bool = False, fallback: str = "") -> CheckResult:
    try:
        detail = action()
        return CheckResult(name, "ok", str(detail or "available"), blocking, fallback)
    except Exception as exc:
        return CheckResult(name, "failed", str(exc)[:300], blocking, fallback)


def run_doctor(check_network: bool = True) -> dict:
    results: list[CheckResult] = []
    results.append(CheckResult("DEEPSEEK_API_KEY", "ok" if config.DEEPSEEK_API_KEY else "failed", "configured" if config.DEEPSEEK_API_KEY else "missing", True))
    results.append(CheckResult("SILICONFLOW_API_KEY", "ok" if config.SILICONFLOW_API_KEY else "fallback", "configured" if config.SILICONFLOW_API_KEY else "missing", False, "local FactPack, local event artwork, Edge TTS"))
    results.append(CheckResult("FEISHU_WEBHOOK", "ok" if config.FEISHU_WEBHOOK else "fallback", "configured" if config.FEISHU_WEBHOOK else "missing", False, "publishing continues without notification"))
    results.append(_check("ffmpeg", lambda: _ffmpeg(), blocking=True))

    def writable() -> str:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=config.DATA_DIR, delete=True):
            pass
        return str(config.DATA_DIR)

    results.append(_check("data_directory", writable, blocking=True))
    prices = (config.DEEPSEEK_CACHE_HIT_USD_PER_M, config.DEEPSEEK_CACHE_MISS_USD_PER_M, config.DEEPSEEK_OUTPUT_USD_PER_M)
    results.append(CheckResult("model_pricing", "ok" if all(value >= 0 for value in prices) else "failed", f"deepseek_usd_per_m={prices}", True))

    if check_network:
        if config.DEEPSEEK_API_KEY:
            results.append(_check("deepseek_writer", lambda: config.DEEPSEEK_MODEL if deepseek_model_available(config.DEEPSEEK_MODEL) else (_ for _ in ()).throw(RuntimeError(f"model unavailable: {config.DEEPSEEK_MODEL}")), blocking=True))
        if config.SILICONFLOW_API_KEY:
            for name, model, fallback in (
                ("qwen_prep", config.PREP_MODEL, "local FactPack"),
                ("kolors_image", config.IMAGE_MODEL, "local event artwork"),
                ("siliconflow_tts", config.SILICONFLOW_TTS_MODEL, "Edge TTS"),
            ):
                def model_detail(model=model) -> str:
                    if not siliconflow_model_available(model):
                        raise RuntimeError(f"model unavailable: {model}")
                    info = siliconflow_model_info(model)
                    pricing = info.get("pricing") or info.get("price") or "not exposed by model list"
                    return f"{model}; pricing={pricing}"
                results.append(_check(name, model_detail, fallback=fallback))
        try:
            import httpx
            response = httpx.head(config.PUBLIC_SITE_URL, timeout=20, follow_redirects=True)
            response.raise_for_status()
            results.append(CheckResult("public_pages", "ok", f"HTTP {response.status_code}"))
        except Exception as exc:
            results.append(CheckResult("public_pages", "failed", str(exc)[:300], False, "scheduled publish will retry"))

    payload = {"ok": not any(item.blocking and item.status == "failed" for item in results), "checks": [asdict(item) for item in results]}
    return payload


def notify_doctor_failure(report: dict) -> bool:
    if report.get("ok"):
        return False
    date_bjt = now_bjt().strftime("%Y-%m-%d")
    ledger = RunLedgerStore()
    key = "doctor:blocking"
    if not ledger.should_notify(date_bjt, key):
        return False
    failures = [item for item in report.get("checks", []) if item.get("blocking") and item.get("status") == "failed"]
    body = "\n".join(f"- {item['name']}: {item['detail']}" for item in failures) or "生产预检未通过"
    if send_ops_card("伊恩每日 · 生产预检失败", body, "red"):
        ledger.mark_notified(date_bjt, key)
        return True
    return False
