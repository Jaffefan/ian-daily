# 伊恩每日运维手册

## 正常日程

所有时间均为北京时间。

| 时间 | 动作 | 通知策略 |
|---|---|---|
| 06:30 | 生成科技、教育、运动三频道 | 内部失败只记台账 |
| 06:50 | 仅重试失败或缺失频道 | 静默 |
| 07:10 | 最终生成重试 | 仍失败才发送频道异常 |
| 09:01-09:51 | 每十分钟检查并发布 | 验证成功才发送节目卡片 |
| 10:05 | Pages 宽限重试与最终检查 | 仍未上线才发送发布异常 |

生成任务使用 `ian-daily-generate` concurrency group，发布任务使用 `ian-daily-publish` concurrency group。重复定时任务会串行进入关键区，不得重复生成、部署或发送飞书。

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

这些命令具有每日幂等保护。日常运行由 Workflow 在最终检查时调用，不应在前两次内部重试后手动触发。

## 告警判定

### 生成失败

只有 07:10 最终重试后仍为 `failed`、`skipped` 或缺失的频道才通知。暂时的模型、抓取、图片或 TTS 错误不会提前推给用户。

### 发布失败

只有 10:05 宽限重试后仍处于 `quality_passed`、且公网验证未完成的频道才通知。Pages 排队期间不视为最终失败。

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
