from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from .config import load_config


def _configure_logging() -> None:
    log_dir = Path(os.path.expandvars(r"%ProgramData%\PackagingStation\logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_dir / "station.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s", encoding="utf-8")


def main() -> int:
    _configure_logging()
    try:
        from .ui import run_ui
        return run_ui(load_config())
    except ImportError as exc:
        print(f"未安装 PySide6，无法启动界面: {exc}", file=sys.stderr)
        return 2
