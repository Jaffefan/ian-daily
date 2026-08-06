# 伊恩每日运维手册

## 运行状态

自动定时任务自 2026-08-06 最后一期发布后暂停。`generate.yml` 与 `publish.yml` 只保留 `workflow_dispatch`，不会每日自动生成、发布或发送飞书。现有 Pages 网站和历史节目保持在线。

需要临时生成或恢复项目时，从 GitHub Actions 手动运行对应 Workflow。恢复自动日更必须获得用户明确确认，并同步更新 Workflow、README、AGENTS.md 和本手册。

## 状态检查

```powershell
python -m ian_daily doctor
python -m ian_daily run-status --date YYYY-MM-DD
python -m ian_daily usage --date YYYY-MM-DD
```

重点查看：

- `data/runs/YYYY-MM-DD.json`：每个频道当前状态、阶段、尝试次数和通知记录。
- `data/usage/YYYY-MM-DD.json`：模型、阶段、token、缓存命中、延迟和估算费用。
- `data/last_generation.json`：最后一次生成或重试的结果。
- `data/release_manifest.json`：本次待发布节目。

`errors` 表示当前尚未恢复的问题。频道达到 `quality_passed` 或 `published` 后会清空当前错误；各阶段记录仍保留用于排查。

## 手动恢复

### 只重试失败频道

```powershell
python -m ian_daily retry-failed --date YYYY-MM-DD
```

已经通过质量门禁或已经发布的频道不会重跑。没有失败频道时命令正常退出。

### 恢复发布

```powershell
python -m ian_daily prepare-release --date YYYY-MM-DD
python -m ian_daily verify-release
python -m ian_daily finalize-release
```

`prepare-release` 只构建待发布产物，不改变节目状态、不发送飞书。`verify-release` 检查公网首页、单期页面、图片和 MP3。只有验证通过后才能执行 `finalize-release`。

需要重建已经发布的页面时：

```powershell
python -m ian_daily prepare-release --date YYYY-MM-DD --rebuild
```

重建不得重复发送节目卡片。

### 单独检查告警

```powershell
python -m ian_daily notify-failures
python -m ian_daily notify-usage-anomaly
python -m ian_daily notify-overdue
```

这些命令具有每日幂等保护。暂停期间只在人工恢复流程的最终检查时调用。

## 告警判定

### 生成失败

手动生成完成后仍为 `failed`、`skipped` 或缺失的频道才通知。暂时的模型、抓取、图片或 TTS 错误不会提前推给用户。

### 发布失败

手动发布完成后仍处于 `quality_passed`、且公网验证未完成的频道才通知。Pages 排队期间不视为最终失败。

### 模型用量

默认单频道调用保护阈值为 24 次，可通过 `IAN_DAILY_MODEL_CALL_ALERT_LIMIT_PER_CATEGORY` 调整。另有 token 趋势检查：至少具备三个有效历史日期后，当日总 token 超过近七日有效日均值两倍才告警。

用量告警每天最多发送一次。正常修复调用、空重试和其他频道的调用不能合并误判为单频道失控。

## 发布成功标准

一个频道同时满足以下条件才算完成：

1. `QualityReport.publishable` 为真。
2. Pages 部署成功。
3. 公网单期页面返回成功。
4. 页面引用的图片可访问。
5. 完整 MP3 可访问。
6. 状态已写为 `published`。
7. `feishu_notified_at_bjt` 已记录。

飞书失败不会伪造通知成功；下一次发布检查会继续补发未完成的节目卡片。

## 常见现象

| 现象 | 判断 | 处理 |
|---|---|---|
| 第一次生成失败、后续成功 | 内部波动 | 无需人工处理 |
| `retry-failed` 没有输出节目 | 没有失败频道 | 正常空操作 |
| Actions 仍在运行 | 可能正在安装浏览器或等待 Pages | 等待宽限检查 |
| 节目为 `quality_passed` | 内容完成但尚未验证上线 | 等待发布 Workflow |
| 节目为 `published` 但未收到卡片 | 飞书通知未完成 | 下一轮发布检查补发 |
| 单频道调用超过 24 次 | 可能发生重复生成或修复循环 | 查看 usage 的 category 和 stage |

## Secrets 与权限

仓库必须配置：

- `DEEPSEEK_API_KEY`
- `SILICONFLOW_API_KEY`
- `FEISHU_WEBHOOK`

Pages Source 使用 GitHub Actions。Workflow 只允许写入 `Jaffefan/ian-daily`，不得配置「伊恩 AI 小报」仓库的写权限。
