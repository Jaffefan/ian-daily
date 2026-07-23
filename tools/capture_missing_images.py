from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from PIL import Image
from playwright.async_api import Page, async_playwright

from ian_daily.images import _phash
from ian_daily.site import build_site
from ian_daily.storage import EpisodeStore


EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


@dataclass(frozen=True)
class Capture:
    episode_id: str
    story_id: str
    url: str
    link_text: str = ""


CAPTURES = (
    Capture("2026-07-21-education", "c2dea02ee40929414363", "http://www.sx.xinhuanet.com/20260721/4fffc5dda9d8426981f2d549b344a6c7/c.html"),
    Capture("2026-07-21-education", "ac3e920f69fc25c38db2", "https://huacheng.gz-cmc.com/pages/2026/07/21/8ec28c8f052e4f08bdb9c448cb6d342a.html"),
    Capture("2026-07-21-education", "cb5b52c2d655d2055794", "https://news.scut.edu.cn/", "联合推动化学化工领域拔尖人才培养"),
    Capture("2026-07-22-education", "6343cfdc6a74496fe900", "https://news.bjtu.edu.cn/", "学校召开第十二届纪律检查委员会第十八次全体会议"),
    Capture("2026-07-23-education", "9f8b3dfd28c1b015b2ca", "https://www.ebiotrade.com/newsf/2026-7/20260723000624375.htm"),
    Capture("2026-07-23-education", "367a41f72c158a3409a4", "https://www.chinanews.com.cn/sh/shipin/cns-d/2026/07-23/news1062949.shtml"),
    Capture("2026-07-23-education", "587672abca3b9a4568b9", "https://www.ebiotrade.com/newsf/2026-7/20260723000754393.htm"),
    Capture("2026-07-23-sports", "b5455f4495dc26541026", "https://www.ebiotrade.com/newsf/2026-7/20260723001030893.htm"),
)


async def _open_story(page: Page, item: Capture) -> str:
    await page.goto(item.url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(3_000)
    for label in ("关闭", "关闭广告"):
        close = page.get_by_text(label, exact=True).first
        if await close.count():
            try:
                await close.click(timeout=2_000)
            except Exception:
                pass
    if item.link_text:
        link = page.get_by_text(item.link_text, exact=False).first
        if await link.count():
            href = await link.get_attribute("href")
            if href:
                await page.goto(urljoin(page.url, href), wait_until="domcontentloaded", timeout=60_000)
            else:
                await link.click()
                await page.wait_for_load_state("domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(3_000)
    return page.url


async def _capture(page: Page, target: Path, title: str) -> str:
    title_text = title.split(" - ")[0].strip()
    title_locator = page.get_by_text(title_text, exact=False).first
    if not await title_locator.count():
        title_locator = page.get_by_text(title_text[:18], exact=False).first
    title_box = await title_locator.bounding_box() if await title_locator.count() else None
    title_y = title_box["y"] if title_box else 0

    candidates = await page.locator("img, video").all()
    ranked: list[tuple[float, object]] = []
    for locator in candidates:
        try:
            info = await locator.evaluate(
                """element => {
                    const rect = element.getBoundingClientRect();
                    const source = (element.currentSrc || element.poster || element.src || '').toLowerCase();
                    const alt = (element.alt || '').toLowerCase();
                    return {
                        width: element.naturalWidth || element.videoWidth || rect.width,
                        height: element.naturalHeight || element.videoHeight || rect.height,
                        rectWidth: rect.width,
                        rectHeight: rect.height,
                        y: rect.top + window.scrollY,
                        visible: rect.width > 0 && rect.height > 0,
                        rejected: /logo|icon|avatar|qrcode|二维码|sprite|advert|banner/.test(
                            source + ' ' + alt + ' ' + (element.closest('[class]')?.className || '')
                        )
                    };
                }"""
            )
            near_article = not title_y or title_y - 180 <= info["y"] <= title_y + 2200
            large_on_page = info["rectWidth"] >= 420 and info["rectHeight"] >= 220
            aspect = info["rectWidth"] / max(1, info["rectHeight"])
            editorial_aspect = 0.5 <= aspect <= 3
            if near_article and large_on_page and editorial_aspect and info["visible"] and not info["rejected"]:
                ranked.append((float(info["width"] * info["height"]), locator))
        except Exception:
            continue
    if ranked:
        locator = max(ranked, key=lambda item: item[0])[1]
        await locator.scroll_into_view_if_needed()
        await locator.screenshot(path=str(target))
        return "原文图片"

    if title_box:
        await title_locator.scroll_into_view_if_needed()
        await page.evaluate(
            """() => document.querySelectorAll('img, iframe').forEach(element => {
                element.style.visibility = 'hidden';
            })"""
        )
        document_height = await page.evaluate("document.documentElement.scrollHeight")
        viewport = page.viewport_size or {"width": 1360, "height": 900}
        x = max(0, title_box["x"] - 45)
        y = max(0, title_box["y"] - 35)
        clip = {
            "x": x,
            "y": y,
            "width": min(880, viewport["width"] - x),
            "height": min(760, document_height - y),
        }
        await page.screenshot(path=str(target), clip=clip)
        return "原文资料截图"

    content = page.locator("main, article, body").first
    box = await content.bounding_box() if await content.count() else None
    if not box:
        raise RuntimeError("原文页面没有可截图区域")
    clip = {
        "x": max(0, box["x"]),
        "y": max(0, box["y"]),
        "width": min(1200, box["width"]),
        "height": min(760, box["height"]),
    }
    await page.screenshot(path=str(target), clip=clip)
    return "原文资料截图"


def _to_webp(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        image.convert("RGB").save(target, "WEBP", quality=86, method=6)


async def main() -> None:
    store = EpisodeStore()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=EDGE, headless=True)
        context = await browser.new_context(viewport={"width": 1360, "height": 900}, locale="zh-CN")
        for item in CAPTURES:
            bundle = store.load_bundle(item.episode_id)
            article = next(article for article in bundle.story_set.articles if article.id == item.story_id)
            section = next(section for section in bundle.reading.sections if section.story_id == item.story_id)
            page = await context.new_page()
            try:
                final_url = await _open_story(page, item)
                image_dir = store.episode_dir(item.episode_id) / "images"
                image_dir.mkdir(parents=True, exist_ok=True)
                png = image_dir / f"{item.story_id}.capture.png"
                target = image_dir / Path(section.image_url).name
                label = await _capture(page, png, article.title)
                _to_webp(png, target)
                png.unlink(missing_ok=True)
                image_hash = _phash(target)
                for record in (article, section):
                    record.image_url = f"images/{target.name}"
                    record.image_credit = f"{article.source} · {label}"
                    record.image_kind = "source" if label == "原文图片" else "reference"
                    record.image_source_url = final_url
                    record.image_status = "captured"
                    record.image_phash = image_hash
                store.save_bundle(bundle)
                print(json.dumps({"episode": item.episode_id, "title": section.title, "label": label, "url": final_url}, ensure_ascii=False))
            except Exception as exc:
                print(json.dumps({"episode": item.episode_id, "title": section.title, "error": str(exc)}, ensure_ascii=False))
            finally:
                await page.close()
        await browser.close()
    build_site(store)


if __name__ == "__main__":
    asyncio.run(main())
