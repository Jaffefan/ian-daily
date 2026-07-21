from __future__ import annotations

from . import config
from .models import EpisodeBundle, QualityReport


def send_channel_card(bundle: EpisodeBundle | None, report: QualityReport | None, category: str, error: str = "") -> None:
    if not config.FEISHU_WEBHOOK:
        return
    try:
        import httpx
        name = config.CATEGORIES[category].name
        if bundle and report and report.publishable:
            link = f"{config.PUBLIC_SITE_URL}{category}/{bundle.episode_id}/"
            title = f"伊恩每日·{name} 已发布"
            body = f"{bundle.podcast.description}\n\n时长：{report.audio_duration_sec / 60:.1f} 分钟\n[打开节目]({link})"
            color = "green"
        else:
            title = f"伊恩每日·{name} 发布失败"
            body = f"失败环节：{error or '质量门禁'}\n系统已阻止公开上线，请查看运行日志后重试。"
            color = "red"
        response = httpx.post(config.FEISHU_WEBHOOK, json={
            "msg_type": "interactive",
            "card": {"header": {"title": {"tag": "plain_text", "content": title}, "template": color},
                     "elements": [{"tag": "markdown", "content": body}]},
        }, timeout=20)
        response.raise_for_status()
    except Exception as exc:
        print(f"  [feishu-warning] {category}: {exc}")
