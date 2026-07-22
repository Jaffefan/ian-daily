# 伊恩每日

独立的三频道深度资讯项目。每天为科技、教育、运动分别生成共享事实简报，并独立创作公众号式图文版与完整播客版。

本仓库不导入、不修改、不发布「伊恩 AI 小报」的任何生产模块或网站文件。目标站点为 <https://jaffefan.github.io/ian-daily/>。

## 内容结构

- 图文版：按当天实际收集到的 1—5 个合格事件生成，每章包含背景、变化、分析、普通人影响、建议和来源。
- 播客版：完整栏目结构，不朗读图文稿；伊恩使用 `zh-CN-XiaoyiNeural`，听众问题使用 `zh-CN-YunxiNeural`。
- 教育和运动优先 3 条国内 + 2 条全球；不足时按当天实际收集到的合格事件数量生成短一期，不凑数、不停更。
- Edge TTS 连续失败时整期切换 SiliconFlow，不混用主持声音。
- Qwen 负责事实压缩与合并审校，DeepSeek V4 Flash 只负责图文和播客终稿；所有调用记录 token、缓存命中与估算费用。
- RSS/OG 原图优先，缺图时使用 Kolors AI 题图，最终仍有本地 WebP 兜底。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
$env:DEEPSEEK_API_KEY="..."
python -m ian_daily generate
python -m ian_daily prepare-release
python -m ian_daily verify-release
python -m ian_daily finalize-release
python -m ian_daily usage --days 14
python -m ian_daily review --port 5211
```

节目按频道保存在 `data/episodes/<category>/<episode_id>/`，公开站点只生成到本仓库的 `site/`。旧 `data/drafts/` 可通过 `python -m ian_daily migrate-storage` 幂等迁移。

GitHub Actions 每天北京时间 06:30 生成；09:01—09:51 每十分钟执行一次幂等发布。只有 Pages 页面、图片和 MP3 验证通过后才标记发布并发送飞书。

## GitHub Secrets

在 `Jaffefan/ian-daily` 中单独设置 `DEEPSEEK_API_KEY`、`SILICONFLOW_API_KEY`、`FEISHU_WEBHOOK`，并将 Pages Source 设为 GitHub Actions。仓库权限不得包含旧项目。
