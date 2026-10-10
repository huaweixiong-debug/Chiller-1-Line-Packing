from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import BoxSession, FinalizationJournal, PACKAGE_SIZE, StationConfig


class StateStoreError(RuntimeError):
    pass

def _text_encoding() -> str:
    """现场 Windows 用 mbcs；非 Windows 回退 gbk，便于 Linux 测试。"""
    try:
        import codecs
        codecs.lookup("mbcs")
        return "mbcs"
    except LookupError:
        return "gbk"




class LegacyStateStore:
    def __init__(self, config: StationConfig):
        self.config = config
        self.journal = Path(os.path.expandvars(config.journal_file))
        self.session_path = Path(os.path.expandvars(config.session_file))

    @staticmethod
    def _read(path: str, default: str | None = None) -> str:
        try:
            return Path(path).read_text(encoding=_text_encoding()).strip()
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
            with os.fdopen(fd, "w", encoding=_text_encoding(), newline="") as handle:
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
        """按现场约定写 BarTender 标签数据文件：装箱上线码0~11.txt + 数量 + 最终箱码。"""
        if len(products) != PACKAGE_SIZE:
            raise StateStoreError(f"打印前需要 {PACKAGE_SIZE} 个上线码，实际 {len(products)} 个")
        laser_root = Path(self.config.laser_archive_dir).parent
        for index, code in enumerate(products):
            self._atomic_write(str(laser_root / f"装箱上线码{index}.txt"), code)
        self._atomic_write(self.config.quantity_file, str(len(products)))
        self._atomic_write(self.config.final_box_file, box_code)


    def write_chery_label_files(
        self,
        *,
        part_no: str | None = None,
        batch: str | None = None,
        layers: str | None = None,
        qty: str | None = None,
        prod_date: str | None = None,
    ) -> str:
        """写入奇瑞二维码载荷文本；仅在 [chery_label].enabled 时由 workflow 调用。"""
        from . import chery_qr

        cfg = self.config.chery
        chosen_part = (part_no if part_no is not None else cfg.part_no).strip()
        chosen_batch = (batch if batch is not None else cfg.batch).strip()
        chosen_layers = (layers if layers is not None else cfg.layers).strip()
        if not chosen_part:
            raise StateStoreError("奇瑞标签零件号未配置")
        if not chosen_batch:
            raise StateStoreError("奇瑞标签发运批次未填写")
        if not chosen_layers:
            raise StateStoreError("奇瑞标签码放层数未填写")
        part = chery_qr.get_part(chosen_part)
        qty_text = (qty if qty is not None else cfg.qty_override).strip()
        if not qty_text:
            qty_text = str(part["qty"])
        counters_path = cfg.counters_file
        counters = chery_qr.load_counters(counters_path)
        unique_code = chery_qr.next_unique_code(part["unique_prefix"], counters)
        date_text = (prod_date or chery_qr.today_yyyymmdd()).strip()
        payload = chery_qr.build_payload(
            part["part_no"], qty_text, chosen_batch, chosen_layers,
            date_text, unique_code, part["box_no"],
        )
        self._atomic_write(cfg.qr_payload_file, payload)
        chery_qr.commit_unique_code(unique_code, counters, counters_path)
        return payload

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
