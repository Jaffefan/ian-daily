from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("IAN_DAILY_DATA_DIR", ROOT / "data"))
DRAFTS_DIR = DATA_DIR / "drafts"
EPISODES_DIR = DATA_DIR / "episodes"
USAGE_DIR = DATA_DIR / "usage"
SITE_DIR = Path(os.environ.get("IAN_DAILY_SITE_DIR", ROOT / "site"))
PUBLIC_BASE = os.environ.get("IAN_DAILY_PUBLIC_BASE", "/ian-daily/")
if not PUBLIC_BASE.startswith("/"):
    PUBLIC_BASE = "/" + PUBLIC_BASE
if not PUBLIC_BASE.endswith("/"):
    PUBLIC_BASE += "/"

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("IAN_DAILY_WRITER_MODEL", os.environ.get("IAN_DAILY_MODEL", "deepseek-v4-flash"))
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE_URL = os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
PREP_MODEL = os.environ.get("IAN_DAILY_PREP_MODEL", "Qwen/Qwen3.5-4B")
IMAGE_MODEL = os.environ.get("IAN_DAILY_IMAGE_MODEL", "Kwai-Kolors/Kolors")
SILICONFLOW_TTS_URL = os.environ.get("SILICONFLOW_TTS_URL", "https://api.siliconflow.cn/v1/audio/speech")
SILICONFLOW_TTS_MODEL = os.environ.get("SILICONFLOW_TTS_MODEL", "FunAudioLLM/CosyVoice2-0.5B")
SILICONFLOW_IAN_VOICE = os.environ.get("SILICONFLOW_IAN_VOICE", "FunAudioLLM/CosyVoice2-0.5B:diana")
SILICONFLOW_LISTENER_VOICE = os.environ.get("SILICONFLOW_LISTENER_VOICE", "FunAudioLLM/CosyVoice2-0.5B:anna")
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
PUBLIC_SITE_URL = os.environ.get("IAN_DAILY_PUBLIC_SITE_URL", "https://jaffefan.github.io/ian-daily/")

IAN_VOICE = os.environ.get("IAN_DAILY_IAN_VOICE", "zh-CN-XiaoyiNeural")
LISTENER_VOICE = os.environ.get("IAN_DAILY_LISTENER_VOICE", "zh-CN-YunxiNeural")
CHAPTER_PAUSE_SEC = float(os.environ.get("IAN_DAILY_CHAPTER_PAUSE_SEC", "1.2"))


@dataclass(frozen=True, slots=True)
class Feed:
    name: str
    url: str
    language: str
    region: str
    authority_tier: int = 2


@dataclass(frozen=True, slots=True)
class CategoryProfile:
    slug: str
    name: str
    color: str
    tts_rate: str
    selection_focus: str
    reading_lens: str
    podcast_lens: str
    tone: str
    exclusions: str
    feeds: tuple[Feed, ...]


def google_news(name: str, query: str, language: str, region: str) -> Feed:
    encoded = quote_plus(query)
    if language == "zh":
        url = f"https://news.google.com/rss/search?q={encoded}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    else:
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    return Feed(name, url, language, region, 2)


CATEGORIES: dict[str, CategoryProfile] = {
    "tech": CategoryProfile(
        "tech", "科技", "#008C7A", "+0%",
        "消费数码、半导体、新能源、航天、硬核技术、产业政策和企业技术迭代",
        "变化是什么 -> 新旧对比 -> 技术与成本门槛 -> 产业赢家与输家 -> 普通人影响",
        "从一个具体场景进入事件，讲清技术选择与商业博弈，再把当天事件串成产业趋势",
        "理性、克制、通俗硬核、有科技人文感",
        "参数堆砌、融资通稿、空泛AI炒作、生活鸡汤",
        (
            Feed("机器之心", "https://www.jiqizhixin.com/rss", "zh", "domestic", 1),
            Feed("量子位", "https://www.qbitai.com/feed", "zh", "domestic", 1),
            Feed("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/", "en", "global", 1),
            Feed("The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "en", "global", 1),
        ),
    ),
    "education": CategoryProfile(
        "education", "教育", "#3A6B35", "-4%",
        "K12政策、升学改革、家庭教育、成人学习、职场成长、学习科学和教育公平",
        "事件或政策 -> 谁受影响 -> 利弊与误区 -> 分层可执行方法 -> 长期成长与公平",
        "从真实困惑进入，用听众问题拆掉焦虑，把宏观规则变成学生、家长和职场人的行动",
        "温柔共情、方法落地、克制治愈",
        "说教、速成承诺、培训软文、焦虑营销",
        (
            google_news("国内教育", "教育政策 OR 升学 OR 家庭教育 OR 学校", "zh", "domestic"),
            Feed("The 74", "https://www.the74million.org/feed/", "en", "global", 1),
            Feed("eSchool News", "https://www.eschoolnews.com/feed/", "en", "global", 2),
            Feed("ScienceDaily Learning", "https://www.sciencedaily.com/rss/mind_brain/educational_psychology.xml", "en", "global", 2),
        ),
    ),
    "sports": CategoryProfile(
        "sports", "运动", "#E4572E", "+6%",
        "国内外赛事、运动员、战术、大众健身、运动健康和体育产业",
        "关键节点 -> 战术或误区 -> 人的表现 -> 胜负或效果原因 -> 后续看点与大众建议",
        "用现场感还原关键时刻，穿插听众对规则或健身误区的提问，再落到普通人的运动生活",
        "明快、热血、接地气、新手友好",
        "虚构赛况、饭圈站队、只报比分、生硬术语",
        (
            google_news("国内体育", "中国体育 OR 全运会 OR CBA OR 中超 OR 全民健身", "zh", "domestic"),
            Feed("ESPN", "https://www.espn.com/espn/rss/news", "en", "global", 1),
            Feed("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml", "en", "global", 1),
        ),
    ),
}


def require_deepseek_key() -> str:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is required")
    return DEEPSEEK_API_KEY
