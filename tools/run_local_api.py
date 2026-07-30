from __future__ import annotations

import os
from pathlib import Path

import uvicorn


def main() -> None:
    pid_path = Path(os.environ["CLOUD_STUDY_LOCAL_API_PID_PATH"])
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = pid_path.with_suffix(".tmp")
    temporary_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    temporary_path.replace(pid_path)
    uvicorn.run(
        "cloud_study_api.main:app",
        app_dir="apps/api/src",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
