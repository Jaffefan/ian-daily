const { test, expect } = require('@playwright/test');
const { pathToFileURL } = require('url');
const path = require('path');

const base = process.env.IAN_DAILY_SITE_TEST_URL || pathToFileURL(path.resolve('site', 'index.html')).href;

test('homepage and category archives remain separated', async ({ page }) => {
  await page.goto(base);
  await expect(page).toHaveTitle('伊恩每日');
  await expect(page.locator('.channel-card')).toHaveCount(3);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => innerWidth));
  await expect(page.locator('.channel-card img')).toHaveCount(3);
  expect(await page.locator('.channel-card img').evaluateAll(images => images.every(image => image.complete && image.naturalWidth > 0))).toBeTruthy();

  const techUrl = new URL('tech/', base).href;
  await page.goto(techUrl);
  await expect(page.locator('h1')).toHaveText('科技');
  const archiveLinks = await page.locator('.episode-row').evaluateAll(links => links.map(link => link.getAttribute('href')));
  expect(archiveLinks.every(link => link.includes('-tech/'))).toBeTruthy();
});

test('episode player is responsive, sticky and uses real chapters', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(base);
  const episodePath = await page.locator('.channel-card').first().locator('.primary-link').getAttribute('href');
  await page.goto(new URL(episodePath, base).href);
  await expect(page.locator('#play')).toBeVisible();
  await expect(page.locator('#mute')).toBeVisible();
  await expect(page.locator('#chapter-drawer')).not.toHaveAttribute('open', '');
  await page.evaluate(() => scrollTo(0, 1500));
  await expect.poll(() => page.locator('.player-shell').evaluate(element => Math.round(element.getBoundingClientRect().top))).toBe(54);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  expect(await page.locator('.player-shell').evaluate(element => element.getBoundingClientRect().height)).toBeLessThanOrEqual(190);
  const chapterTitles = await page.locator('.chapter').allTextContents();
  expect(chapterTitles.length).toBeGreaterThanOrEqual(3);
  expect(chapterTitles.some(title => /^事件\s*\d+$/.test(title))).toBeFalsy();
  expect(await page.locator('.story-image').evaluateAll(images => images.every(image => image.complete && image.naturalWidth > 0))).toBeTruthy();
  expect(await page.locator('.source-list').count()).toBeGreaterThan(0);
});
