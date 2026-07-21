# 项目隔离与恢复记录

`ian-daily` 是独立项目，不读取或写入旧仓库 `Jaffefan/fan01--studio` 的生产目录、Workflow、Pages 或密钥。

迁移前于 2026-07-21 执行旧项目 `python -m ian_daily baseline-check`，结果通过。基线清单位于旧项目 `archive/ian-ai-digest-2026-07-21/baseline.sha256`，覆盖 `main.py`、采集/写稿/TTS/页面/发布核心程序、`requirements.txt`、`.github/workflows/daily.yml` 与架构部署文档。迁移完成后必须在旧项目再次运行同一命令。

恢复本项目只需重新克隆 `Jaffefan/ian-daily`，配置本仓库自己的三个 Secrets，并由 GitHub Actions 重新构建 Pages。恢复旧小报不需要本项目的任何文件。
