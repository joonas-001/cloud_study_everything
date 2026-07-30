from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    base_temp = REPOSITORY_ROOT / ".tmp" / f"pytest-{uuid4().hex}"
    return pytest.main([*sys.argv[1:], "--basetemp", str(base_temp)])


if __name__ == "__main__":
    raise SystemExit(main())
