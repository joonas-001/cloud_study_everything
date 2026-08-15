from __future__ import annotations

import argparse
from pathlib import Path

from cloud_study_api.runner import RunnerProtocolError
from cloud_study_api.runner_broker import serve_runner_broker

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the isolated 云奕学 Docker broker."
    )
    parser.add_argument(
        "--socket",
        type=Path,
        default=Path("/run/cloud-study-runner/runner.sock"),
    )
    parser.add_argument("--data-root", type=Path, default=Path("/var/lib/docker"))
    parser.add_argument("--disk-root", type=Path, default=Path("/"))
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        serve_runner_broker(
            REPOSITORY_ROOT,
            arguments.socket,
            data_root=arguments.data_root,
            disk_root=arguments.disk_root,
        )
    except RunnerProtocolError as error:
        print(f"Runner broker failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
