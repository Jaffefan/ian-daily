# 伊恩每日

独立的三频道深度资讯项目。每天为科技、教育、运动分别生成一组共享事实素材，并独立创作公众号式图文版与约 15 分钟播客版。

本仓库不导入、不修改、不发布「伊恩 AI 小报」的任何生产模块或网站文件。目标站点为 <https://jaffefan.github.io/ian-daily/>。

## 内容结构

- 图文版：4—5 个事件，每章包含背景、变化、分析、普通人影响、建议和来源。
- 播客版：完整栏目结构，不朗读图文稿；伊恩使用 `zh-CN-XiaoyiNeural`，听众问题使用 `zh-CN-YunxiNeural`。
- 教育和运动优先 3 条国内 + 2 条全球；不足时采用 2+2 深挖；再不足则停更。
- Edge TTS 连续失败时整期切换 SiliconFlow，不混用主持声音。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
$env:DEEPSEEK_API_KEY="..."
python -m ian_daily generate
python -m ian_daily publish
python -m ian_daily review --port 5211
```

草稿保存在 `data/drafts/`，公开站点只生成到本仓库的 `site/`。

## GitHub Secrets

在 `Jaffefan/ian-daily` 中单独设置 `DEEPSEEK_API_KEY`、`SILICONFLOW_API_KEY`、`FEISHU_WEBHOOK`，并将 Pages Source 设为 GitHub Actions。仓库权限不得包含旧项目。
