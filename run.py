#!/usr/bin/env python3
"""Command-line entry point for the Gigapixel + Bloom automation.

Leslie's workflow is two phases with a human review in between:

    Phase 1 — Bloom:
        python run.py bloom "C:/path/to/folder" --output out
        # then open  out/review/  and check the *__bloom.png results

    Phase 2 — Finish approved (Gigapixel + print prep):
        python run.py finish --output out                 # finish everything
        python run.py finish --output out --only img1,img2 # finish some

    Testing / trust-the-AI (both phases, auto-approve all):
        python run.py auto "C:/path/to/folder" --output out
        python run.py auto "C:/path" --output out --dry-run   # no API calls
"""

from __future__ import annotations

import argparse
import sys

from src.config import load_config
from src.pipeline import Pipeline

# Windows consoles default to cp1252; make sure any Unicode in logs/errors is safe.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _log(msg: str) -> None:
    print(msg, flush=True)


def _load(args):
    # In dry-run we don't need real keys, so skip loading the environment.
    return load_config(getattr(args, "config", None), load_env=not getattr(args, "dry_run", False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gigapixel + Bloom print automation.")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-o", "--output", default="output", help="Output folder (default: ./output).")
    common.add_argument("-c", "--config", default=None, help="Path to config.yaml.")
    common.add_argument("--dry-run", action="store_true", help="No Topaz API calls; plan only.")

    p_bloom = sub.add_parser("bloom", parents=[common], help="Phase 1: run Bloom for review.")
    p_bloom.add_argument("input", help="Image file or folder.")

    p_finish = sub.add_parser("finish", parents=[common], help="Phase 2: finish approved images.")
    p_finish.add_argument("--only", default=None, help="Comma-separated image names to finish.")

    p_auto = sub.add_parser("auto", parents=[common], help="Both phases, auto-approve all.")
    p_auto.add_argument("input", help="Image file or folder.")

    args = parser.parse_args(argv)

    try:
        config = _load(args)
    except Exception as exc:  # noqa: BLE001
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    pipeline = Pipeline(config, logger=_log, dry_run=args.dry_run)

    try:
        if args.command == "bloom":
            results = pipeline.run_bloom_phase(args.input, args.output)
            _log(f"\nNext: review {args.output}/review, then run:  python run.py finish -o {args.output}")
            return 1 if any(not r.ok for r in results) else 0
        if args.command == "finish":
            only = [s.strip() for s in args.only.split(",")] if args.only else None
            results = pipeline.run_finish_phase(args.output, only=only)
            return 1 if any(not r.ok for r in results) else 0
        if args.command == "auto":
            results = pipeline.run_auto(args.input, args.output)
            return 1 if any(not r.ok for r in results) else 0
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
