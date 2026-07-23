from __future__ import annotations

import argparse
import sys

from . import config
from .pipeline import generate_all, generate_category, retry_failed
from .model_api import usage_report
from .publisher import finalize_release, notify_generation_failures, notify_release_overdue, prepare_release, publish_ready, verify_release
from .review import run_review_server
from .site import build_site
from .doctor import notify_doctor_failure, run_doctor
from .operations import run_status
from .benchmark import cost_benchmark
from .calibration import calibration_status


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m ian_daily", description="伊恩每日三频道生产工具")
    commands = root.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="生成三频道或指定频道")
    generate.add_argument("--category", choices=tuple(config.CATEGORIES))
    generate.add_argument("--force", action="store_true")
    generate.add_argument("--skip-audio", action="store_true", help="仅用于开发检查")
    retry = commands.add_parser("retry-failed", help="仅重试今天失败或缺失的频道")
    retry.add_argument("--date")
    retry.add_argument("--skip-audio", action="store_true")
    publish = commands.add_parser("publish", help="发布全部质量通过的节目")
    publish.add_argument("--date")
    review = commands.add_parser("review", help="启动仅限本机的预览站")
    review.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"))
    review.add_argument("--port", type=int, default=5211)
    review.add_argument("--token", default="")
    commands.add_parser("build-site", help="重新构建静态站")
    commands.add_parser("backfill-images", help="重新抓取历史节目中的本地占位题图")
    prepare = commands.add_parser("prepare-release", help="构建待发布 Pages 产物")
    prepare.add_argument("--date")
    prepare.add_argument("--rebuild", action="store_true", help="重建当天已发布页面但不重复通知")
    commands.add_parser("verify-release", help="验证 Pages 和音频已经上线")
    commands.add_parser("finalize-release", help="完成发布状态并发送飞书")
    commands.add_parser("notify-overdue", help="通知九点发布逾期")
    commands.add_parser("migrate-storage", help="迁移为按频道分层的数据目录")
    usage = commands.add_parser("usage", help="查看模型 token 与费用")
    usage.add_argument("--date")
    usage.add_argument("--days", type=int, default=1)
    status = commands.add_parser("run-status", help="查看每日生产与发布台账")
    status.add_argument("--date")
    doctor = commands.add_parser("doctor", help="检查模型、密钥、音频、数据目录与公网状态")
    doctor.add_argument("--offline", action="store_true")
    doctor.add_argument("--notify", action="store_true", help="阻断项失败时发送一次幂等运维通知")
    benchmark = commands.add_parser("benchmark-cost", help="对比旧版估算输入与新版真实模型用量")
    benchmark.add_argument("--date")
    commands.add_parser("calibration-status", help="查看三频道固定样本与评分门槛")
    commands.add_parser("notify-failures", help="发送三个频道各自的异常卡片")
    commands.add_parser("demo-site", help="生成不可发布的界面预览数据")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "generate":
            if args.category:
                generate_category(args.category, force=args.force, skip_audio=args.skip_audio)
            else:
                generate_all(force=args.force, skip_audio=args.skip_audio)
        elif args.command == "retry-failed":
            print("已重试：", ", ".join(item.episode_id for item in retry_failed(args.date, skip_audio=args.skip_audio)) or "无")
        elif args.command == "publish":
            print("已发布：", ", ".join(publish_ready(args.date)) or "无")
        elif args.command == "review":
            run_review_server(args.host, args.port, args.token)
        elif args.command == "build-site":
            print(build_site())
        elif args.command == "backfill-images":
            import json
            from .images import backfill_story_images
            print(json.dumps(backfill_story_images(), ensure_ascii=False, indent=2))
            print(build_site())
        elif args.command == "prepare-release":
            print("待发布：", ", ".join(prepare_release(args.date, rebuild=args.rebuild)) or "无")
        elif args.command == "verify-release":
            verify_release(); print("Pages 验证通过")
        elif args.command == "finalize-release":
            print("已发布：", ", ".join(finalize_release()) or "无")
        elif args.command == "notify-overdue":
            notify_release_overdue()
        elif args.command == "migrate-storage":
            from .storage import EpisodeStore
            print("已迁移：", ", ".join(EpisodeStore().migrate_legacy_layout()) or "无")
        elif args.command == "usage":
            import json
            print(json.dumps(usage_report(args.date, args.days), ensure_ascii=False, indent=2))
        elif args.command == "run-status":
            import json
            print(json.dumps(run_status(args.date), ensure_ascii=False, indent=2))
        elif args.command == "doctor":
            import json
            report = run_doctor(check_network=not args.offline)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if args.notify:
                notify_doctor_failure(report)
            return 0 if report["ok"] else 1
        elif args.command == "benchmark-cost":
            import json
            print(json.dumps(cost_benchmark(args.date), ensure_ascii=False, indent=2))
        elif args.command == "calibration-status":
            import json
            print(json.dumps(calibration_status(), ensure_ascii=False, indent=2))
        elif args.command == "notify-failures":
            notify_generation_failures()
        elif args.command == "demo-site":
            from .demo import create_demo_site
            create_demo_site()
            print(config.SITE_DIR)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
