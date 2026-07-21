from __future__ import annotations

import argparse
import sys

from . import config
from .pipeline import generate_all, generate_category
from .publisher import notify_generation_failures, publish_ready
from .review import run_review_server
from .site import build_site


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m ian_daily", description="伊恩每日三频道生产工具")
    commands = root.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="生成三频道或指定频道")
    generate.add_argument("--category", choices=tuple(config.CATEGORIES))
    generate.add_argument("--force", action="store_true")
    generate.add_argument("--skip-audio", action="store_true", help="仅用于开发检查")
    publish = commands.add_parser("publish", help="发布全部质量通过的节目")
    publish.add_argument("--date")
    review = commands.add_parser("review", help="启动仅限本机的预览站")
    review.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"))
    review.add_argument("--port", type=int, default=5211)
    review.add_argument("--token", default="")
    commands.add_parser("build-site", help="重新构建静态站")
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
        elif args.command == "publish":
            print("已发布：", ", ".join(publish_ready(args.date)) or "无")
        elif args.command == "review":
            run_review_server(args.host, args.port, args.token)
        elif args.command == "build-site":
            print(build_site())
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
