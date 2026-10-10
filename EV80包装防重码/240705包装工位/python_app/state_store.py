from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import BoxSession, FinalizationJournal, PACKAGE_SIZE, StationConfig


class StateStoreError(RuntimeError):
    pass


class LegacyStateStore:
    def __init__(self, config: StationConfig):
        self.config = config
        self.journal = Path(os.path.expandvars(config.journal_file))
        self.session_path = Path(os.path.expandvars(config.session_file))

    @staticmethod
    def _read(path: str, default: str | None = None) -> str:
        try:
            return Path(path).read_text(encoding="mbcs").strip()
        except FileNotFoundError:
            if default is not None:
                return default
            raise StateStoreError(f"状态文件不存在: {path}")
        except (OSError, UnicodeError) as exc:
            raise StateStoreError(f"读取状态文件失败: {path}: {exc}") from exc

    @staticmethod
    def _atomic_write(path: str, value: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="mbcs", newline="") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        except Exception as exc:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise StateStoreError(f"写入状态文件失败: {path}: {exc}") from exc

    def target_quantity(self) -> int:
        """Return the fixed production contract; the legacy quantity file is ignored."""
        return PACKAGE_SIZE

    def next_box_code(self) -> str:
        sequence_text = self._read(self.config.box_sequence_file, "0")
        try:
            sequence = int(sequence_text)
        except ValueError as exc:
            raise StateStoreError("箱码序号不是有效整数") from exc
        from datetime import datetime
        return f"{datetime.now():%Y%m%d}{sequence:05d}"

    def advance_box_sequence(self) -> None:
        current = int(self._read(self.config.box_sequence_file, "0"))
        self._atomic_write(self.config.box_sequence_file, str(current + 1))

    def write_print_files(self, box_code: str, products: list[str]) -> None:
        """按旧系统约定写 BarTender 标签数据文件：装箱激光码0~11.txt + 数量 + 最终箱码。"""
        if len(products) != PACKAGE_SIZE:
            raise StateStoreError(f"打印前需要 {PACKAGE_SIZE} 个激光码，实际 {len(products)} 个")
        laser_root = Path(self.config.laser_archive_dir).parent
        for index, code in enumerate(products):
            self._atomic_write(str(laser_root / f"装箱激光码{index}.txt"), code)
        self._atomic_write(self.config.quantity_file, str(len(products)))
        self._atomic_write(self.config.final_box_file, box_code)

    def archive_products(self, box_code: str, products: list[str]) -> None:
        path = Path(self.config.laser_archive_dir) / f"{box_code}.txt"
        self._atomic_write(str(path), "\n".join(products) + "\n")

    def save_journal(self, journal: FinalizationJournal) -> None:
        self._atomic_write(str(self.journal), json.dumps(journal.__dict__, ensure_ascii=False, indent=2))

    def load_journal(self) -> FinalizationJournal | None:
        try:
            data = json.loads(self.journal.read_text(encoding="utf-8"))
            return FinalizationJournal(**data)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError) as exc:
            raise StateStoreError(f"恢复 journal 失败: {exc}") from exc

    def clear_journal(self) -> None:
        try:
            self.journal.unlink(missing_ok=True)
        except OSError as exc:
            raise StateStoreError(f"清理 journal 失败: {exc}") from exc

    def save_session(self, box: BoxSession) -> None:
        data = {"box_code": box.box_code, "products": list(box.products)}
        self._atomic_write(str(self.session_path), json.dumps(data, ensure_ascii=False, indent=2))

    def load_session(self) -> BoxSession | None:
        try:
            data = json.loads(self.session_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError) as exc:
            raise StateStoreError(f"读取装箱进度失败: {exc}") from exc
        return BoxSession(str(data.get("box_code", "")), [str(code) for code in data.get("products", [])])

    def clear_session(self) -> None:
        try:
            self.session_path.unlink(missing_ok=True)
        except OSError as exc:
            raise StateStoreError(f"清理装箱进度失败: {exc}") from exc
