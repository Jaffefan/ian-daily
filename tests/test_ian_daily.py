from __future__ import annotations

import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ian_daily.models import Article, AudioBlock, DailyStorySet, EpisodeBundle, FactPack, PodcastEpisode, ReadingEdition, ReadingSection, SourceRef
from ian_daily.quality import evaluate_bundle
from ian_daily.selection import select_articles
from ian_daily.audio import generate_podcast_audio_async

BJT = timezone(timedelta(hours=8))


def article(index: int, region: str, category: str = "education") -> Article:
    return Article(str(index), category, f"事件 {index}", "摘要" * 100, f"https://example.com/{index}", f"来源{index}", datetime.now(BJT).isoformat(), "zh", region, 1)


class SelectionTests(unittest.TestCase):
    def test_domestic_global_target(self):
        items = [article(i, "domestic") for i in range(3)] + [article(i + 10, "global") for i in range(2)]
        selected = select_articles(items, "education")
        self.assertEqual(5, len(selected))
        self.assertEqual(3, sum(item.region == "domestic" for item in selected))

    def test_four_story_fallback(self):
        items = [article(i, "domestic") for i in range(2)] + [article(i + 10, "global") for i in range(2)]
        self.assertEqual(4, len(select_articles(items, "sports")))

    def test_stops_below_quota(self):
        items = [article(1, "domestic"), article(2, "global"), article(3, "global"), article(4, "global")]
        self.assertEqual([], select_articles(items, "education"))


class QualityTests(unittest.TestCase):
    def test_blocks_article_narration_and_missing_audio(self):
        articles = [article(i, "domestic" if i < 2 else "global") for i in range(4)]
        refs = [SourceRef(a.id, a.title, a.source, a.url, a.published_at_bjt, 1) for a in articles]
        packs = [FactPack(a.id, a.title, [a.summary], [refs[i]]) for i, a in enumerate(articles)]
        repeated = "这是同一段被直接复用的内容。" * 60
        reading = ReadingEdition("标题", "导语" * 50, [ReadingSection(a.id, a.title, "导读", repeated, "观察", "", "", [a.id], [refs[i]]) for i, a in enumerate(articles)], "复盘")
        blocks = [AudioBlock("open", "ian", "opening", "开场" * 50)]
        for a in articles:
            blocks.append(AudioBlock(f"s-{a.id}", "ian", "story", repeated, a.id))
        blocks += [AudioBlock("q1", "listener", "question", "这对普通人意味着什么？"), AudioBlock("q2", "listener", "question", "我们会不会高估它？")]
        podcast = PodcastEpisode("标题", "简介", blocks)
        bundle = EpisodeBundle("2026-01-01-education", 2, "education", "教育", "2026-01-01", DailyStorySet("education", "2026-01-01", articles, packs), reading, podcast)
        report = evaluate_bundle(bundle)
        self.assertFalse(report.publishable)
        self.assertTrue(any("大段复用" in error for error in report.errors))
        self.assertTrue(any("音频" in error for error in report.errors))


class AudioFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_edge_failure_regenerates_whole_episode(self):
        podcast = PodcastEpisode("标题", "简介", [AudioBlock("a", "ian", "opening", "开场"), AudioBlock("b", "listener", "question", "问题")])
        calls = []

        async def render(podcast, category, root, provider):
            calls.append(provider)
            if provider == "edge":
                podcast.blocks[0].audio_file = "edge/partial.mp3"
                raise RuntimeError("edge down")
            self.assertTrue(all(not block.audio_file for block in podcast.blocks))
            podcast.tts_provider = provider
            return podcast

        with tempfile.TemporaryDirectory() as temp, patch("ian_daily.audio.config.SILICONFLOW_API_KEY", "configured"), patch("ian_daily.audio._render_provider", side_effect=render):
            result = await generate_podcast_audio_async(podcast, "tech", Path(temp))
        self.assertEqual(["edge", "siliconflow"], calls)
        self.assertEqual("siliconflow", result.tts_provider)


if __name__ == "__main__":
    unittest.main()
