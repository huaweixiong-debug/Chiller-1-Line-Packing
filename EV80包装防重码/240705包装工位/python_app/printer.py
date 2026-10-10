from __future__ import annotations

import subprocess

from .models import StationConfig


class PrinterError(RuntimeError):
    pass


class LabelPrinter:
    def __init__(self, config: StationConfig, runner=subprocess.run):
        self.config, self.runner = config, runner

    def print_label(self) -> None:
        command = [self.config.bartend_exe, self.config.label_template, "/P", "/X"]
        try:
            result = self.runner(command, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PrinterError(f"BarTender 打印失败: {exc}") from exc
        if result.returncode != 0:
            raise PrinterError(f"BarTender 返回错误码: {result.returncode}")
