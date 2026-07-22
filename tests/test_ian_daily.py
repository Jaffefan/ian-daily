from __future__ import annotations

import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import json
import wave
from array import array
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ian_daily.models import Article, AudioBlock, Chapter, DailyStorySet, EpisodeBundle, FactPack, PodcastEpisode, QualityReport, ReadingEdition, ReadingSection, SourceRef
from ian_daily.quality import evaluate_bundle
from ian_daily.selection import select_articles
from ian_daily.audio import _render_provider, generate_podcast_audio_async
from ian_daily.agents import _remove_residual_numeric_precision, audit_editions, build_content_brief, build_fact_packs, generate_podcast, generate_reading
from ian_daily.images import resolve_story_images
from ian_daily.publisher import finalize_release, notify_generation_failures, prepare_release
from ian_daily.site import build_site
from ian_daily.storage import EpisodeStore

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

    def test_publishes_available_items_below_old_quota(self):
        items = [article(1, "domestic"), article(2, "global"), article(3, "global"), article(4, "global")]
        self.assertEqual(4, len(select_articles(items, "education")))

    def test_single_eligible_item_is_selected(self):
        self.assertEqual(1, len(select_articles([article(1, "global")], "sports")))

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
        with patch("ian_daily.agents._writer", return_value=generated):
            edition = generate_reading("tech", [primary], [pack])
        self.assertEqual(2, len(edition.sections[0].source_refs))


class QualityTests(unittest.TestCase):
    def test_single_story_short_episode_can_publish(self):
        item = article(1, "domestic")
        ref = SourceRef(item.id, item.title, item.source, item.url, item.published_at_bjt, 1)
        pack = FactPack(item.id, item.title, ["可核对事实" * 30], [ref])
        reading = ReadingEdition(
            "单主题", "导语" * 40,
            [ReadingSection(item.id, item.title, "导读", "教育机制与现实影响" * 80, "继续观察", "images/test.webp", "测试", [item.id], [ref])],
            "复盘" * 30,
        )
        podcast = PodcastEpisode(
            "单主题播客", "简介",
            [
                AudioBlock("open", "ian", "opening", "声音开场" * 35),
                AudioBlock("story", "ian", "story", "现场叙事与人物处境" * 120, item.id),
                AudioBlock("question", "listener", "question", "这件事和普通人有什么关系？", item.id),
                AudioBlock("answer", "ian", "answer", "具体回答与行动建议" * 35, item.id),
                AudioBlock("close", "ian", "closing", "声音收束" * 30),
            ],
            [Chapter("story-1", "事件一", 20, item.id)], "episode.mp3", 300,
        )
        bundle = EpisodeBundle("2026-01-01-education", 2, "education", "教育", "2026-01-01", DailyStorySet("education", "2026-01-01", [item], [pack]), reading, podcast)
        report = evaluate_bundle(bundle)
        self.assertTrue(report.publishable, report.errors)

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

        async def render(podcast, category, root, provider, story_titles=None):
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
    def test_single_source_numeric_precision_fallback(self):
        body = "官方宣布2026年安排，投入1200万元，目标覆盖85%的参与者，比分为102：98。"
        corrected = _remove_residual_numeric_precision(body)
        self.assertNotRegex(corrected, r"(?<![A-Za-z])\d{2,}(?![A-Za-z])")
        self.assertIn("本年度", corrected)

    def test_podcast_covers_story_ids_in_order(self):
        refs = [SourceRef(str(i), f"事件{i}", f"来源{i}", f"https://example.com/{i}", "2026-01-01T08:00:00+08:00", 1) for i in range(5)]
        packs = [FactPack(str(i), f"事件{i}", ["可核对事实" * 20], [refs[i]]) for i in range(5)]
        generated = {"title": "运动测试", "description": "测试", "blocks": [
            {"block_id": "open", "speaker": "ian", "role": "opening", "text": "开场", "story_id": ""},
            *[{"block_id": f"story-{i}", "speaker": "ian", "role": "story", "text": "声音叙事" * 220, "story_id": str(i)} for i in range(5)],
            {"block_id": "q1", "speaker": "listener", "role": "question", "text": "问题一", "story_id": ""},
            {"block_id": "q2", "speaker": "listener", "role": "question", "text": "问题二", "story_id": ""},
            {"block_id": "end", "speaker": "ian", "role": "closing", "text": "收束", "story_id": ""},
        ]}
        with patch("ian_daily.agents._writer", return_value=generated):
            episode = generate_podcast("sports", packs)
        self.assertEqual([str(i) for i in range(5)], [block.story_id for block in episode.blocks if block.role == "story"])
        self.assertTrue(all(len(block.text) >= 650 for block in episode.blocks if block.role == "story"))

    def test_invalid_story_coverage_is_rejected(self):
        refs = [SourceRef(str(i), f"事件{i}", f"来源{i}", f"https://example.com/{i}", "2026-01-01T08:00:00+08:00", 1) for i in range(4)]
        packs = [FactPack(str(i), f"事件{i}", ["事实" * 30], [refs[i]]) for i in range(4)]
        generated = {"title": "测试", "description": "测试", "blocks": [{"block_id": "s0", "speaker": "ian", "role": "story", "text": "声音叙事" * 180, "story_id": "0"}]}
        with patch("ian_daily.agents._writer", return_value=generated):
            with self.assertRaisesRegex(ValueError, "完整覆盖"):
                generate_podcast("tech", packs)


class LowCostPipelineTests(unittest.TestCase):
    def test_normal_path_uses_two_prep_and_two_writer_calls(self):
        item = article(1, "domestic", "tech")
        ref = SourceRef(item.id, item.title, item.source, item.url, item.published_at_bjt, 1)
        pack = FactPack(item.id, item.title, ["可核对事实" * 30], [ref])
        calls = []

        def generated(provider, model, system, payload, **kwargs):
            calls.append((provider, kwargs["stage"]))
            stage = kwargs["stage"]
            if stage == "content_brief":
                return {"stories": [{"story_id": item.id, "facts": pack.facts, "impact_angles": ["普通人影响"]}]}
            if stage == "reading":
                return {"title": "标题", "lead": "导语", "synthesis": "复盘", "sections": [{"story_id": item.id, "title": "事件", "dek": "导读", "body": "机制分析与现实影响" * 80, "takeaway": "继续观察"}]}
            if stage == "podcast":
                return {"title": "播客", "description": "简介", "blocks": [
                    {"block_id": "open", "speaker": "ian", "role": "opening", "text": "开场", "story_id": ""},
                    {"block_id": "story", "speaker": "ian", "role": "story", "text": "声音叙事" * 220, "story_id": item.id},
                    {"block_id": "q", "speaker": "listener", "role": "question", "text": "这意味着什么？", "story_id": item.id},
                    {"block_id": "answer", "speaker": "ian", "role": "answer", "text": "回答" * 80, "story_id": item.id},
                    {"block_id": "end", "speaker": "ian", "role": "closing", "text": "收束", "story_id": ""},
                ]}
            return {"blocking_errors": [], "rubric_scores": {"facts": 5, "viewpoint": 5, "category_identity": 5, "clarity": 5, "tone": 5}}

        with patch("ian_daily.agents.siliconflow_model_available", return_value=True), patch("ian_daily.agents.generate_json", side_effect=generated):
            brief = build_content_brief("tech", "2026-01-01", [pack])
            reading = generate_reading("tech", [item], [pack], brief)
            podcast = generate_podcast("tech", [pack], brief)
            self.assertEqual([], audit_editions(reading, podcast, [pack], brief))
        self.assertEqual([("siliconflow", "content_brief"), ("deepseek", "reading"), ("deepseek", "podcast"), ("siliconflow", "audit")], calls)


class MediaPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_pcm_master_uses_sample_accurate_chapter_start(self):
        podcast = PodcastEpisode("标题", "简介", [AudioBlock("open", "ian", "opening", "开场"), AudioBlock("story", "ian", "story", "正文", "story")])

        async def fake_tts(text, output, voice, rate):
            with wave.open(str(output), "wb") as target:
                target.setnchannels(1); target.setsampwidth(2); target.setframerate(24000)
                target.writeframes(array("h", [0] * 24000).tobytes())

        with tempfile.TemporaryDirectory() as temp, patch("ian_daily.audio._edge_text", side_effect=fake_tts):
            result = await _render_provider(podcast, "tech", Path(temp) / "audio", "edge", {"story": "真实标题"})
            chapter = next(item for item in result.chapters if item.story_id == "story")
            self.assertAlmostEqual(1 + 1.2, chapter.start_sec, delta=0.01)
            self.assertEqual("真实标题", chapter.title)
            self.assertTrue(result.waveform_peaks)

    def test_image_pipeline_always_creates_local_webp(self):
        item = article(1, "global", "tech")
        reading = ReadingEdition("标题", "导语", [ReadingSection(item.id, item.title, "导读", "正文" * 200, "观察", "", "", [], [])], "复盘")
        with tempfile.TemporaryDirectory() as temp, patch("ian_daily.images._download", return_value=False), patch("ian_daily.images._generate", return_value=False):
            resolve_story_images("tech", [item], reading, Path(temp))
            self.assertTrue((Path(temp) / reading.sections[0].image_url).exists())
            self.assertTrue(reading.sections[0].image_url.endswith(".webp"))


class StorageAndReleaseTests(unittest.TestCase):
    def _bundle(self, status="quality_passed"):
        item = article(1, "domestic", "tech")
        ref = SourceRef(item.id, item.title, item.source, item.url, item.published_at_bjt, 1)
        pack = FactPack(item.id, item.title, [item.summary], [ref])
        reading = ReadingEdition("标题", "导语", [ReadingSection(item.id, item.title, "导读", "正文" * 200, "观察", "images/a.webp", "来源", [item.id], [ref])], "复盘")
        podcast = PodcastEpisode("播客", "简介", [AudioBlock("story", "ian", "story", "声音" * 400, item.id)], [Chapter("story-1", item.title, 0, item.id)], "episode.mp3", 300)
        return EpisodeBundle("2026-01-01-tech", 3, "tech", "科技", "2026-01-01", DailyStorySet("tech", "2026-01-01", [item], [pack]), reading, podcast, status=status)

    def test_legacy_storage_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); legacy = root / "drafts"; episodes = root / "episodes"
            source = legacy / "2026-01-01-tech"; source.mkdir(parents=True)
            (source / "bundle.json").write_text(json.dumps(self._bundle().to_dict(), ensure_ascii=False), encoding="utf-8")
            store = EpisodeStore(episodes, legacy)
            self.assertEqual(["2026-01-01-tech"], store.migrate_legacy_layout())
            self.assertEqual([], store.migrate_legacy_layout())
            self.assertTrue((episodes / "tech" / "2026-01-01-tech" / "bundle.json").exists())

    def test_finalize_is_idempotent_and_notifies_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); store = EpisodeStore(root / "episodes", root / "drafts")
            bundle = self._bundle(); episode_dir = store.episode_dir(bundle.episode_id); episode_dir.mkdir(parents=True)
            store.save_bundle(bundle)
            store.save_quality(QualityReport(bundle.episode_id, True, 1, 1, 1, 800, 1200, 300, 1, 0, [], []))
            (episode_dir / "episode.mp3").write_bytes(b"audio")
            manifest = root / "manifest.json"; manifest.write_text(json.dumps({"episode_ids": [bundle.episode_id]}), encoding="utf-8")
            with patch("ian_daily.publisher.send_channel_card", return_value=True) as send, patch("ian_daily.publisher.RunLedgerStore"):
                finalize_release(manifest, store); finalize_release(manifest, store)
            self.assertEqual(1, send.call_count)
            self.assertEqual("published", store.load_bundle(bundle.episode_id).status)

    def test_prepare_retries_missing_feishu_notification(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); store = EpisodeStore(root / "episodes", root / "drafts")
            bundle = self._bundle(status="published")
            store.save_bundle(bundle)
            store.save_quality(QualityReport(bundle.episode_id, True, 1, 1, 1, 800, 1200, 300, 1, 0, [], []))
            manifest = root / "manifest.json"
            with patch("ian_daily.publisher.MANIFEST", manifest), patch("ian_daily.publisher.build_site"), patch("ian_daily.publisher.RunLedgerStore"):
                ids = prepare_release("2026-01-01", store)
            self.assertEqual([bundle.episode_id], ids)

    def test_legacy_published_bundle_is_not_renotified(self):
        payload = self._bundle(status="published").to_dict()
        payload["schema_version"] = 2
        payload.pop("published_at_bjt", None)
        payload.pop("feishu_notified_at_bjt", None)
        migrated = EpisodeBundle.from_dict(payload)
        self.assertTrue(migrated.feishu_notified_at_bjt)

    def test_manual_rebuild_includes_notified_published_episode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); store = EpisodeStore(root / "episodes", root / "drafts")
            bundle = self._bundle(status="published")
            bundle.feishu_notified_at_bjt = "2026-01-01T09:00:00+08:00"
            store.save_bundle(bundle)
            store.save_quality(QualityReport(bundle.episode_id, True, 1, 1, 1, 800, 1200, 300, 1, 0, [], []))
            with patch("ian_daily.publisher.MANIFEST", root / "manifest.json"), patch("ian_daily.publisher.build_site"), patch("ian_daily.publisher.RunLedgerStore"):
                self.assertEqual([], prepare_release("2026-01-01", store))
                self.assertEqual([bundle.episode_id], prepare_release("2026-01-01", store, rebuild=True))


class NotificationTests(unittest.TestCase):
    def test_quality_blocked_episode_sends_failure_card(self):
        with tempfile.TemporaryDirectory() as temp:
            data_dir = Path(temp)
            (data_dir / "last_generation.json").write_text(json.dumps({
                "failures": {}, "episodes": ["2026-01-01-sports"]
            }), encoding="utf-8")
            bundle = unittest.mock.Mock(status="failed", category="sports", episode_id="2026-01-01-sports")
            report = unittest.mock.Mock(errors=["音频时长不足"])
            with patch("ian_daily.publisher.config.DATA_DIR", data_dir), patch("ian_daily.publisher.config.RUNS_DIR", data_dir / "runs"), \
                 patch("ian_daily.publisher.EpisodeStore") as store_type, \
                 patch("ian_daily.publisher.send_channel_card") as send:
                store_type.return_value.load_bundle.return_value = bundle
                store_type.return_value.load_quality.return_value = report
                notify_generation_failures()
                notify_generation_failures()
            send.assert_called_once_with(None, report, "sports", "音频时长不足")


class SiteTests(unittest.TestCase):
    def test_empty_channels_do_not_expose_internal_status(self):
        with tempfile.TemporaryDirectory() as temp, patch("ian_daily.site.config.SITE_DIR", Path(temp)):
            store = unittest.mock.Mock()
            store.list_bundles.return_value = []
            build_site(store)
            homepage = (Path(temp) / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("今天尚无通过质量门禁的节目", homepage)


if __name__ == "__main__":
    unittest.main()
