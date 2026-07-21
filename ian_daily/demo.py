from __future__ import annotations

from datetime import datetime
import shutil
import subprocess

from . import config
from .models import Article, AudioBlock, Chapter, DailyStorySet, EpisodeBundle, FactPack, PodcastEpisode, QualityReport, ReadingEdition, ReadingSection, SourceRef
from .site import build_site
from .storage import EpisodeStore, now_bjt_iso
from .audio import _ffmpeg


def create_demo_site() -> None:
    """Create non-publishable layout fixtures. Never used by scheduled workflows."""
    store = EpisodeStore(config.DATA_DIR / "preview-fixtures")
    today = datetime.now().strftime("%Y-%m-%d")
    shared_audio = store.root / "preview-silence.mp3"
    shared_audio.parent.mkdir(parents=True, exist_ok=True)
    if not shared_audio.exists():
        subprocess.run([
            _ffmpeg(), "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
            "-t", "900", "-b:a", "16k", str(shared_audio),
        ], capture_output=True, text=True, timeout=90, check=True)
    for category, profile in config.CATEGORIES.items():
        episode_id = f"preview-{category}"
        articles = []
        packs = []
        sections = []
        blocks = [AudioBlock("opening", "ian", "opening", "这是伊恩每日的开发预览。这里检查完整播客播放器与图文阅读布局，不代表真实新闻。")]
        chapters = [Chapter("opening", "开场", 0)]
        for index in range(1, 5):
            story_id = f"{category}-{index}"
            source = SourceRef(story_id, f"开发预览素材 {index}", "界面测试来源", "https://example.com", now_bjt_iso(), 1)
            article = Article(story_id, category, f"{profile.name}频道的事件呈现示例 {index}", "仅用于页面布局测试。", "https://example.com", "界面测试来源", now_bjt_iso(), "zh", "domestic" if index <= 2 else "global", 1)
            articles.append(article)
            packs.append(FactPack(story_id, article.title, ["这是开发预览事实占位，不是新闻。"], [source]))
            sections.append(ReadingSection(story_id, article.title, "这一段展示公众号式导读、分析与行动建议的层次。", ("图文版和播客版共享事件，但不共享正文。这里用足够长的占位内容测试中文长文的字号、行距、段落宽度和移动端换行。" * 8), "正式内容会在这里给出可执行建议或后续观察。", "", "", [story_id], [source]))
            start = index * 150.0
            chapters.append(Chapter(f"story-{index}", f"事件 {index}", start, story_id))
            blocks.append(AudioBlock(f"story-{index}", "ian", "story", "播客会用声音自己的叙事方式讨论同一件事，而不是朗读上方文章。" * 12, story_id, start_sec=start, duration_sec=120))
            if index in {1, 3}:
                blocks.append(AudioBlock(f"question-{index}", "listener", "question", "这件事对普通人的真实影响是什么？", story_id, start_sec=start + 120, duration_sec=15))
        chapters.append(Chapter("synthesis", "主题复盘", 660))
        blocks.append(AudioBlock("synthesis", "ian", "synthesis", "最后把四个事件放在一起，寻找今天真正值得带走的共同线索。", start_sec=660, duration_sec=90))
        blocks.append(AudioBlock("closing", "ian", "closing", "这里是开发预览的收束。", start_sec=750, duration_sec=30))
        reading = ReadingEdition(f"{profile.name}开发预览", "这不是新闻节目，而是新站的交互与排版预览。", sections, "图文版在结尾形成自己的跨事件复盘。")
        episode_dir = store.episode_dir(episode_id)
        episode_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shared_audio, episode_dir / "full.mp3")
        podcast = PodcastEpisode(f"{profile.name}频道：播客与图文如何并行", "同一组事件，两种独立创作。先听完整节目，再按自己的节奏阅读图文分析。测试音频为静音，仅用于验证播放、续播和章节跳转。", blocks, chapters, "full.mp3", 900, "preview")
        stamp = now_bjt_iso()
        bundle = EpisodeBundle(episode_id, 2, category, profile.name, today, DailyStorySet(category, today, articles, packs), reading, podcast, "published", stamp, stamp)
        store.save_bundle(bundle)
        store.save_quality(QualityReport(episode_id, False, 4, 4, 2, 4200, 3600, 900, 1, 0.05, ["开发预览不可发布"], []))
    build_site(store)
