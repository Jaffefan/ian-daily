# 伊恩每日 - 项目约定

## 项目边界

`ian-daily` 是科技、教育、运动三频道的独立生产项目。它拥有自己的代码、数据、GitHub Actions、Secrets 和 Pages 网站。

- 不读取、导入、修改或发布「伊恩 AI 小报」的生产模块和网站文件。
- 所有公开产物只写入本仓库的 `site/`。
- 所有节目数据只写入 `data/episodes/<category>/<episode_id>/`。
- Secrets 只通过环境变量或 `Jaffefan/ian-daily` 的 GitHub Secrets 注入，禁止写入仓库。

## 生产状态

节目状态固定为：

`generated -> review_required/quality_passed -> published/failed`

- 只有页面、图片和 MP3 公网验证通过后才能标记 `published`。
- 飞书成功卡片只能在发布验证通过后发送。
- 重复生成、发布和通知必须幂等。
- 已成功频道不得在后续重试中重新生成。
- 没有失败频道时，`retry-failed` 必须成功退出，不能制造空任务失败。

## 告警规则

- 自动生成与发布 schedule 已暂停，两个 Workflow 只允许 `workflow_dispatch`。
- 未经用户明确要求，不得恢复 cron、push 自动生成或其他后台触发入口。
- 手动运行时，只有最终生成失败或公网验证失败才发送异常卡片。
- 同一日期、频道和故障类型最多通知一次。
- 模型用量只在最终生成完成后检查一次；单频道超过保护阈值，或 token 超过有效历史基线两倍才告警。

## 硬规则

- 所有日期、期号和运行台账使用北京时间 UTC+8。
- 图文版和播客版共享事件、来源和事实边界，但不得共享大段正文。
- 社区评论只能作为明确标注的观点样本，不能作为事实证据。
- 每个正式事件必须有来源；数字、争议和重大判断需要独立佐证。
- 图片必须本地缓存并记录来源，页面不得引用会过期的临时图片 URL。
- TTS 分块先统一为 PCM/WAV，再一次编码最终 MP3；章节时间从样本偏移计算。
- GitHub Actions 写回数据前必须 `git pull --rebase origin main`。
- 不提交完整原文、完整 Prompt、缓存、临时音频或密钥。

## 关键入口

| 路径 | 职责 |
|---|---|
| `ian_daily/pipeline.py` | 三频道生成、失败重试和状态推进 |
| `ian_daily/agents.py` | ContentBrief、图文、播客与合并审校 |
| `ian_daily/audio.py` | 双声音频、PCM 母带与章节时间 |
| `ian_daily/images.py` | RSS/OG、AI 题图和本地兜底 |
| `ian_daily/publisher.py` | 两阶段发布、飞书与最终异常通知 |
| `ian_daily/operations.py` | RunLedger、通知幂等和失败频道选择 |
| `ian_daily/model_api.py` | 模型调用、用量记录和异常判断 |
| `.github/workflows/generate.yml` | 生成与最终生成告警 |
| `.github/workflows/publish.yml` | Pages 发布、公网验证和宽限告警 |

使用与部署入口见 `README.md`，日常排障见 `docs/runbook.md`。
