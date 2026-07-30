from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def prepare_base_temp(repository_root: Path = REPOSITORY_ROOT) -> Path:
    temporary_root = repository_root / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    return temporary_root / f"pytest-{uuid4().hex}"


def main() -> int:
    base_temp = prepare_base_temp()
    return pytest.main([*sys.argv[1:], "--basetemp", str(base_temp)])


if __name__ == "__main__":
    raise SystemExit(main())
