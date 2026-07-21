from __future__ import annotations

import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ian_daily.models import Article, AudioBlock, DailyStorySet, EpisodeBundle, FactPack, PodcastEpisode, ReadingEdition, ReadingSection, SourceRef
from ian_daily.quality import evaluate_bundle
from ian_daily.selection import select_articles
from ian_daily.audio import generate_podcast_audio_async
from ian_daily.agents import build_fact_packs, generate_podcast, generate_reading
from ian_daily.publisher import notify_generation_failures

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

    def test_direct_corroboration_is_kept_in_fact_pack(self):
        primary = article(1, "global", "tech")
        corroboration = article(2, "global", "tech")
        corroboration.source = "独立来源"
        packs = build_fact_packs([primary], [primary, corroboration], {primary.id: [corroboration]})
        self.assertEqual(2, len(packs[0].sources))
        self.assertEqual({"来源1", "独立来源"}, {source.source for source in packs[0].sources})

    def test_reading_exposes_all_fact_pack_sources(self):
        primary = article(1, "global", "tech")
        corroboration = article(2, "global", "tech")
        corroboration.source = "独立来源"
        pack = build_fact_packs([primary], [primary, corroboration], {primary.id: [corroboration]})[0]
        generated = {"title": "标题", "lead": "导语", "synthesis": "复盘", "sections": [{
            "story_id": primary.id, "title": "事件", "dek": "导读", "body": "分析" * 500,
            "takeaway": "观察", "source_ids": [primary.id]
        }]}
        with patch("ian_daily.agents._generate", return_value=generated):
            edition = generate_reading("tech", [primary], [pack])
        self.assertEqual(2, len(edition.sections[0].source_refs))


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


class AgentRepairTests(unittest.TestCase):
    def test_podcast_restores_invalid_story_ids_in_order(self):
        refs = [SourceRef(str(i), f"事件{i}", f"来源{i}", f"https://example.com/{i}", "2026-01-01T08:00:00+08:00", 1) for i in range(5)]
        packs = [FactPack(str(i), f"事件{i}", ["可核对事实" * 20], [refs[i]]) for i in range(5)]
        first = {"title": "运动测试", "description": "测试", "blocks": [
            {"block_id": "open", "speaker": "ian", "role": "opening", "text": "开场", "story_id": ""},
            *[{"block_id": f"story-{i}", "speaker": "ian", "role": "story", "text": "短稿", "story_id": f"bad-{i}"} for i in range(5)],
            {"block_id": "q1", "speaker": "listener", "role": "question", "text": "问题一", "story_id": ""},
            {"block_id": "q2", "speaker": "listener", "role": "question", "text": "问题二", "story_id": ""},
            {"block_id": "end", "speaker": "ian", "role": "closing", "text": "收束", "story_id": ""},
        ]}
        second = {"stories": [{"story_id": str(i), "text": "声音叙事" * 220} for i in range(5)], "opening": "开场" * 60, "synthesis": "复盘" * 120, "closing": "收束" * 50}
        with patch("ian_daily.agents._generate", side_effect=[first, second]):
            episode = generate_podcast("sports", packs)
        self.assertEqual([str(i) for i in range(5)], [block.story_id for block in episode.blocks if block.role == "story"])
        self.assertTrue(all(len(block.text) >= 650 for block in episode.blocks if block.role == "story"))

    def test_extra_story_block_becomes_answer(self):
        refs = [SourceRef(str(i), f"事件{i}", f"来源{i}", f"https://example.com/{i}", "2026-01-01T08:00:00+08:00", 1) for i in range(4)]
        packs = [FactPack(str(i), f"事件{i}", ["事实" * 30], [refs[i]]) for i in range(4)]
        blocks = [{"block_id": f"s{i}", "speaker": "ian", "role": "story", "text": "声音叙事" * 180, "story_id": "bad"} for i in range(5)]
        first = {"title": "测试", "description": "测试", "blocks": blocks}
        second = {"stories": [{"story_id": str(i), "text": "声音叙事" * 180} for i in range(4)]}
        with patch("ian_daily.agents._generate", side_effect=[first, second]):
            episode = generate_podcast("tech", packs)
        self.assertEqual(4, sum(block.role == "story" for block in episode.blocks))
        self.assertEqual("answer", episode.blocks[-1].role)


class NotificationTests(unittest.TestCase):
    def test_quality_blocked_episode_sends_failure_card(self):
        with tempfile.TemporaryDirectory() as temp:
            data_dir = Path(temp)
            (data_dir / "last_generation.json").write_text(json.dumps({
                "failures": {}, "episodes": ["2026-01-01-sports"]
            }), encoding="utf-8")
            bundle = unittest.mock.Mock(status="failed", category="sports", episode_id="2026-01-01-sports")
            report = unittest.mock.Mock(errors=["音频时长不足"])
            with patch("ian_daily.publisher.config.DATA_DIR", data_dir), \
                 patch("ian_daily.publisher.EpisodeStore") as store_type, \
                 patch("ian_daily.publisher.send_channel_card") as send:
                store_type.return_value.load_bundle.return_value = bundle
                store_type.return_value.load_quality.return_value = report
                notify_generation_failures()
            send.assert_called_once_with(None, report, "sports", "音频时长不足")


if __name__ == "__main__":
    unittest.main()
