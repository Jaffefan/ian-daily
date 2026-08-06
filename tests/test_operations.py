from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ian_daily import config
from ian_daily.agents import audit_editions
from ian_daily.calibration import CALIBRATION_CASES, calibration_status
from ian_daily.doctor import run_doctor
from ian_daily.images import build_gimi_illustration_prompt, resolve_story_images
from ian_daily.model_api import _record, usage_anomaly, usage_report
from ian_daily.models import Article, AudioBlock, BriefStory, ContentBrief, FactPack, PodcastEpisode, ReadingEdition, ReadingSection, SourceRef
from ian_daily.operations import RunLedgerStore
from ian_daily.pipeline import generate_all
from ian_daily.sources import _meta_image


def _article(index: int) -> Article:
    return Article(str(index), "tech", f"Event-specific topic {index}", "summary" * 30, f"https://example.com/{index}", "source", "2026-01-01T08:00:00+08:00", "en")


class RunLedgerTests(unittest.TestCase):
    def test_attempts_retry_selection_and_notifications_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RunLedgerStore(Path(temp))
            store.begin_attempt("2026-01-01", "tech")
            store.stage("2026-01-01", "tech", "collection", "failed", "network")
            store.finish("2026-01-01", "tech", "failed", error="network")
            self.assertIn("tech", store.retry_categories("2026-01-01"))
            self.assertTrue(store.should_notify("2026-01-01", "generation:tech"))
            store.mark_notified("2026-01-01", "generation:tech")
            self.assertFalse(store.should_notify("2026-01-01", "generation:tech"))
            self.assertEqual(1, store.load("2026-01-01").channels["tech"].attempts)

    def test_successful_retry_clears_current_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RunLedgerStore(Path(temp))
            store.stage("2026-01-01", "sports", "quality", "failed", "temporary failure")
            store.finish("2026-01-01", "sports", "failed", error="temporary failure")
            store.finish("2026-01-01", "sports", "quality_passed", "2026-01-01-sports")
            channel = store.load("2026-01-01").channels["sports"]
            self.assertEqual([], channel.errors)
            self.assertEqual("failed", channel.stages["quality"]["status"])

    def test_retry_with_no_failed_channels_is_a_successful_noop(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(config, "DATA_DIR", Path(temp)), \
             patch("ian_daily.pipeline.RunLedgerStore") as ledger_type:
            ledger_type.return_value.retry_categories.return_value = []
            self.assertEqual([], generate_all(retry_failed_only=True))
            payload = json.loads((Path(temp) / "last_generation.json").read_text(encoding="utf-8"))
            self.assertEqual({}, payload["failures"])


class DoctorAndUsageTests(unittest.TestCase):
    def test_offline_doctor_never_exposes_secret_values(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(config, "DATA_DIR", Path(temp)), \
             patch.object(config, "DEEPSEEK_API_KEY", "deep-secret"), \
             patch.object(config, "SILICONFLOW_API_KEY", "sf-secret"), \
             patch.object(config, "FEISHU_WEBHOOK", "hook-secret"), \
             patch("ian_daily.doctor._ffmpeg", return_value="ffmpeg"):
            report = run_doctor(check_network=False)
        serialized = json.dumps(report)
        self.assertTrue(report["ok"])
        self.assertNotIn("deep-secret", serialized)
        self.assertNotIn("sf-secret", serialized)
        self.assertNotIn("hook-secret", serialized)

    def test_usage_records_hash_and_counts_but_not_prompt(self):
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20, prompt_cache_hit_tokens=40, prompt_cache_miss_tokens=60)
        with tempfile.TemporaryDirectory() as temp, patch.object(config, "USAGE_DIR", Path(temp)):
            _record("deepseek", "writer", "tech", "reading", usage, 1.25, "private prompt", 500)
            report = usage_report("2026-07-22", 1)
            rows = list(Path(temp).glob("*.json"))
            self.assertEqual(1, len(rows))
            raw = rows[0].read_text(encoding="utf-8")
            self.assertNotIn("private prompt", raw)
            payload = json.loads(raw)[0]
            self.assertEqual(14, payload["input_chars"])
            self.assertEqual(64, len(payload["input_sha256"]))
            self.assertEqual(500, payload["max_tokens"])

    def test_usage_call_alert_is_per_channel_and_allows_expected_repairs(self):
        row = {
            "at_bjt": "2026-07-27T07:00:00+08:00", "provider": "deepseek",
            "model": "writer", "stage": "repair", "prompt_tokens": 100,
            "completion_tokens": 20, "estimated_cny": 0.01,
        }
        with tempfile.TemporaryDirectory() as temp, patch.object(config, "USAGE_DIR", Path(temp)), \
             patch.object(config, "MODEL_CALL_ALERT_LIMIT_PER_CATEGORY", 12):
            rows = [{**row, "category": category} for category in config.CATEGORIES for _ in range(9)]
            (Path(temp) / "2026-07-27.json").write_text(json.dumps(rows), encoding="utf-8")
            self.assertEqual("", usage_anomaly("2026-07-27"))
            rows.extend([{**row, "category": "tech"} for _ in range(4)])
            (Path(temp) / "2026-07-27.json").write_text(json.dumps(rows), encoding="utf-8")
            self.assertIn("13", usage_anomaly("2026-07-27"))


class CalibrationAndImageTests(unittest.TestCase):
    def test_gimi_prompt_is_grounded_in_article_and_category(self):
        article = _article(1)
        article.full_body = "芯片工厂调整产线，工程师正在评估成本与交付影响。"

        prompt = build_gimi_illustration_prompt(article, "tech", "普通用户需要关注设备价格与兼容性。")

        self.assertIn(article.title, prompt)
        self.assertIn("产品方案式编辑插画", prompt)
        self.assertIn("设备价格与兼容性", prompt)
        self.assertIn("不得杜撰", prompt)
        self.assertIn("无文字", prompt)

    def test_meta_image_resolves_relative_url(self):
        markup = '<meta content="/media/cover.jpg" property="og:image">'
        self.assertEqual("https://news.example/media/cover.jpg", _meta_image(markup, "https://news.example/story/1"))

    def test_meta_image_reads_lazy_article_image(self):
        markup = '<img src="/assets/logo.png"><img data-original="/uploads/story.webp">'
        self.assertEqual("https://news.example/uploads/story.webp", _meta_image(markup, "https://news.example/story/1"))

    def test_google_placeholder_is_not_treated_as_source_image(self):
        from ian_daily.images import _usable_source_url

        self.assertFalse(_usable_source_url("https://lh3.googleusercontent.com/placeholder=s0-w300"))
        self.assertTrue(_usable_source_url("https://publisher.example/images/story.jpg"))

    def test_each_category_has_ten_fixed_calibration_cases(self):
        self.assertEqual({"tech": 10, "education": 10, "sports": 10}, {key: len(value) for key, value in CALIBRATION_CASES.items()})
        self.assertTrue(all(item["minimum_score"] == 4 for item in calibration_status().values()))

    def test_low_agent_score_blocks_release(self):
        article = _article(1)
        ref = SourceRef(article.id, article.title, article.source, article.url, article.published_at_bjt, 1)
        pack = FactPack(article.id, article.title, [article.summary], [ref])
        brief = ContentBrief("tech", "2026-01-01", [BriefStory(article.id, article.title, [article.summary], [], [], [], [ref])])
        reading = ReadingEdition("title", "lead", [ReadingSection(article.id, article.title, "dek", "body" * 100, "takeaway", "", "", [article.id], [ref])], "end")
        podcast = PodcastEpisode("title", "description", [AudioBlock("story", "ian", "story", "audio" * 100, article.id)])
        result = {"blocking_errors": [], "rubric_scores": {"facts": 5, "viewpoint": 3, "category_identity": 5, "clarity": 5, "tone": 5}}
        with patch("ian_daily.agents.siliconflow_model_available", return_value=True), patch("ian_daily.agents.generate_json", return_value=result):
            errors = audit_editions(reading, podcast, [pack], brief)
        self.assertTrue(any("观点质量 3/5" in item for item in errors))

    def test_local_event_artwork_is_unique_and_has_provenance(self):
        articles = [_article(1), _article(2)]
        sections = [ReadingSection(item.id, item.title, "dek", "body" * 100, "takeaway", "", "", [], []) for item in articles]
        reading = ReadingEdition("title", "lead", sections, "end")
        with tempfile.TemporaryDirectory() as temp, patch("ian_daily.sources.discover_article_image", return_value=""), patch("ian_daily.images._download", return_value=False), patch("ian_daily.images._generate", return_value=False):
            resolve_story_images("tech", articles, reading, Path(temp))
            self.assertNotEqual(articles[0].image_phash, articles[1].image_phash)
            self.assertTrue(all(item.image_kind == "fallback" for item in articles))
            self.assertTrue(all((Path(temp) / item.image_url).exists() for item in articles))

    def test_missing_feed_image_is_discovered_from_article_page(self):
        article = _article(1)
        section = ReadingSection(article.id, article.title, "dek", "body" * 100, "takeaway", "", "", [], [])
        reading = ReadingEdition("title", "lead", [section], "end")

        def download(_url, target, _referer=""):
            from ian_daily.images import _fallback
            _fallback(article, "tech", target)
            return True

        discovered = "https://news.example/media/cover.jpg"
        with tempfile.TemporaryDirectory() as temp, patch("ian_daily.sources.discover_article_image", return_value=discovered), patch("ian_daily.images._download", side_effect=download):
            resolve_story_images("tech", [article], reading, Path(temp))
        self.assertEqual("source", article.image_kind)
        self.assertEqual(discovered, article.image_source_url)
        self.assertEqual("downloaded", article.image_status)

    def test_missing_source_uses_gimi_illustration_before_local_fallback(self):
        article = _article(1)
        section = ReadingSection(article.id, article.title, "dek", "article analysis" * 100, "takeaway", "", "", [], [])
        reading = ReadingEdition("title", "lead", [section], "end")

        def generate(_article, _category, target, article_text=""):
            from ian_daily.images import _fallback
            self.assertIn("article analysis", article_text)
            _fallback(article, "tech", target)
            return True

        with tempfile.TemporaryDirectory() as temp, patch("ian_daily.sources.discover_article_images", return_value=[]), patch("ian_daily.images._download", return_value=False), patch("ian_daily.images._generate", side_effect=generate):
            resolve_story_images("tech", [article], reading, Path(temp))

        self.assertEqual("ai", article.image_kind)
        self.assertEqual("generated", article.image_status)
        self.assertIn("Gimi", article.image_credit)


class WorkflowTests(unittest.TestCase):
    def test_generate_workflow_is_manual_only_while_paused(self):
        workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "generate.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("push:", workflow)

    def test_publish_workflow_has_no_schedule_while_paused(self):
        workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("push:", workflow)


if __name__ == "__main__":
    unittest.main()
