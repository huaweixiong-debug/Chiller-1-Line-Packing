from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from .db import InspectionRepository
from .models import (BoxSession, FinalizationJournal, InspectionResult, PACKAGE_SIZE,
                     WorkflowState)
from .printer import LabelPrinter
from .state_store import LegacyStateStore

log = logging.getLogger(__name__)


class WorkflowError(RuntimeError):
    pass


@dataclass
class WorkflowSnapshot:
    state: WorkflowState
    current_box: str = ""
    box_count: int = 0
    target_quantity: int = 0
    last_result: InspectionResult | None = None
    message: str = ""
    products: list[str] | None = None
    box_completed: bool = False
    popup: str = ""


class PackagingWorkflow:
    def __init__(self, repository: InspectionRepository, store: LegacyStateStore,
                 printer: LabelPrinter, on_update: Callable[[WorkflowSnapshot], None] | None = None):
        self.repository, self.store, self.printer = repository, store, printer
        self.on_update = on_update or (lambda snapshot: None)
        self.chery_overrides: dict[str, str | None] = {
            "part_no": None, "batch": None, "layers": None, "qty": None,
        }
        self.state = WorkflowState.STARTUP_CHECK
        self.session: BoxSession | None = None
        self.last_result: InspectionResult | None = None

    def _emit(self, message: str = "", *, products: list[str] | None = None,
              current_box: str | None = None, box_completed: bool = False,
              popup: str = "") -> WorkflowSnapshot:
        visible_products = (list(self.session.products) if self.session else []) if products is None else list(products)
        visible_box = (self.session.box_code if self.session else "") if current_box is None else current_box
        snapshot = WorkflowSnapshot(self.state, visible_box, len(visible_products), PACKAGE_SIZE,
                                    self.last_result, message, visible_products, box_completed, popup)
        self.on_update(snapshot)
        return snapshot

    def startup_check(self) -> WorkflowSnapshot:
        try:
            pending = self.store.load_journal()
            if pending:
                self.state = WorkflowState.ERROR_BLOCKED
                return self._emit(f"检测到未完成箱码 {pending.box_code}，请先恢复或人工处理")
            session = self.store.load_session()
            if session is not None:
                self.store.clear_session()
            if session is not None and session.products:
                self.state = WorkflowState.READY
                codes = "\n".join(f"{index}. {code}" for index, code in enumerate(session.products, 1))
                return self._emit(
                    f"上次装箱未完成（{len(session.products)} 件，箱码 {session.box_code}），已清空，请重新扫码装箱",
                    popup=f"上次装箱未完成，不足 12 件，已全部清空，需要重新扫码装箱：\n{codes}")
            self.state = WorkflowState.READY
            return self._emit("系统就绪")
        except Exception as exc:
            self.state = WorkflowState.ERROR_BLOCKED
            return self._emit(str(exc))

    def inspect_serial(self, serial: str) -> InspectionResult:
        self._require_ready()
        self.state = WorkflowState.VALIDATING
        try:
            result = self.repository.inspect_serial(serial)
            self.last_result = result
            self.state = self._active_state()
            self._emit(result.reason)
            return result
        except Exception as exc:
            self.state = WorkflowState.ERROR_BLOCKED
            self._emit(str(exc))
            raise WorkflowError(str(exc)) from exc

    def inspect_customer(self, customer: str) -> InspectionResult:
        self._require_ready()
        self.state = WorkflowState.VALIDATING
        try:
            result = self.repository.inspect_customer(customer)
            self.last_result = result
            self.state = self._active_state()
            self._emit(result.reason)
            return result
        except Exception as exc:
            self.state = WorkflowState.ERROR_BLOCKED
            self._emit(str(exc))
            raise WorkflowError(str(exc)) from exc

    def process_customer_scan(self, customer: str) -> WorkflowSnapshot:
        """Validate and add one customer/laser code as one indivisible scan operation."""
        self._require_ready()
        self.state = WorkflowState.VALIDATING
        try:
            result = self.repository.inspect_customer(customer)
            self.last_result = result
            self.state = self._active_state()
            if result.is_duplicate or not result.can_package:
                return self._emit(result.reason)
            return self._add_product(customer)
        except Exception as exc:
            self.state = WorkflowState.ERROR_BLOCKED
            self._emit(str(exc))
            raise WorkflowError(str(exc)) from exc

    def add_product(self, laser_code: str) -> WorkflowSnapshot:
        self._require_ready()
        return self._add_product(laser_code)

    def _add_product(self, laser_code: str) -> WorkflowSnapshot:
        if not laser_code.strip():
            raise WorkflowError("激光码不能为空")
        if self.session is None:
            self.session = BoxSession(self.store.next_box_code())
        if laser_code in self.session.products:
            slot_number = self.session.products.index(laser_code) + 1
            result = self.last_result
            if result is None or result.scan_code != laser_code:
                result = InspectionResult(laser_code, "customer")
                self.last_result = result
            result.can_package = False
            result.is_duplicate = True
            result.duplicate_source = "current_box"
            result.reason = f"当前箱重复扫码，该产品已在第 {slot_number} 格"
            self.state = self._active_state()
            return self._emit(result.reason)
        self.session.products.append(laser_code)
        self.store.save_session(self.session)
        if self.session.complete:
            self.state = WorkflowState.FINALIZING
            self._emit("12 件产品已全部通过，正在完成箱码并打印")
            return self.finalize_box()
        self.state = WorkflowState.BOX_IN_PROGRESS
        return self._emit(f"第 {self.session.count}/12 件已加入当前箱：{laser_code}")


    def set_chery_fields(
        self,
        *,
        part_no: str | None = None,
        batch: str | None = None,
        layers: str | None = None,
        qty: str | None = None,
    ) -> None:
        """界面或外部设置奇瑞标签字段；None 表示沿用配置默认值。"""
        if part_no is not None:
            self.chery_overrides["part_no"] = part_no
        if batch is not None:
            self.chery_overrides["batch"] = batch
        if layers is not None:
            self.chery_overrides["layers"] = layers
        if qty is not None:
            self.chery_overrides["qty"] = qty

    def finalize_box(self) -> WorkflowSnapshot:
        if self.session is None or not self.session.complete:
            raise WorkflowError("当前箱尚未达到设定数量")
        self.state = WorkflowState.FINALIZING
        box = self.session
        journal = FinalizationJournal(box.box_code, list(box.products), "PREPARED")
        try:
            self.store.save_journal(journal)
            self.store.clear_session()
            self.store.archive_products(box.box_code, box.products)
            journal.phase = "ARCHIVED"
            self.store.save_journal(journal)
            self.store.write_print_files(box.box_code, box.products)
            self.store.advance_box_sequence()
            journal.phase = "FILES_READY"
            self.store.save_journal(journal)
            chery_cfg = getattr(getattr(self.store, "config", None), "chery", None)
            if chery_cfg is not None and chery_cfg.enabled:
                payload = self.store.write_chery_label_files(
                    part_no=self.chery_overrides.get("part_no"),
                    batch=self.chery_overrides.get("batch"),
                    layers=self.chery_overrides.get("layers"),
                    qty=self.chery_overrides.get("qty"),
                )
                log.info("奇瑞二维码已写入 %s: %s", chery_cfg.qr_payload_file, payload)
            self.repository.update_box_codes(box.box_code, box.products)
            journal.phase = "DB_UPDATED"
            self.store.save_journal(journal)
            self.printer.print_label()
            journal.phase = "PRINTED"
            self.store.save_journal(journal)
            self.store.clear_journal()
            self.session = None
            self.state = WorkflowState.READY
            return self._emit(f"箱码 {box.box_code} 已完成", products=box.products,
                              current_box=box.box_code, box_completed=True)
        except Exception as exc:
            self.state = WorkflowState.ERROR_BLOCKED
            log.exception("包装完成失败")
            self._emit(f"箱码 {box.box_code} 完成失败: {exc}")
            raise WorkflowError(str(exc)) from exc

    def rework_scan(self, customer: str) -> WorkflowSnapshot:
        """回退模式：已包装产品扫码后先解除原箱码，再按新品继续装箱。"""
        self._require_ready()
        self.state = WorkflowState.VALIDATING
        try:
            result = self.repository.inspect_customer(customer)
            self.last_result = result
            released_box = ""
            if result.is_duplicate and result.duplicate_source == "database":
                if not self.repository.release_from_box(customer, result.box_code):
                    self.state = self._active_state()
                    return self._emit("回退失败：原箱码已发生变化，请重新扫码确认")
                released_box = result.box_code
                self._emit(f"已解除原箱码 {released_box}，正在重新入箱…")
            self.state = self._active_state()
            snapshot = self.process_customer_scan(customer)
            if released_box:
                snapshot = self._emit(f"回退成功（原箱码 {released_box}）：{snapshot.message}")
            return snapshot
        except Exception as exc:
            self.state = WorkflowState.ERROR_BLOCKED
            self._emit(str(exc))
            raise WorkflowError(str(exc)) from exc

    def reset_box(self) -> WorkflowSnapshot:
        """复位本箱：清空当前箱已扫产品重新开始。未满箱的数据从未写入数据库。"""
        self._require_ready()
        cleared = len(self.session.products) if self.session else 0
        self.session = None
        self.last_result = None
        self.state = WorkflowState.READY
        self.store.clear_session()
        return self._emit(f"本箱已复位，已清除 {cleared} 件产品，请重新扫码",
                          products=[], current_box="")

    def retry_recovery(self) -> WorkflowSnapshot:
        journal = self.store.load_journal()
        if not journal:
            return self.startup_check()
        self.state = WorkflowState.ERROR_BLOCKED
        return self._emit(f"存在未完成箱码 {journal.box_code}（阶段 {journal.phase}），禁止自动重试")

    def _require_ready(self) -> None:
        if self.state not in (WorkflowState.READY, WorkflowState.BOX_IN_PROGRESS):
            raise WorkflowError(f"当前状态不允许操作: {self.state.value}")

    def _active_state(self) -> WorkflowState:
        return WorkflowState.BOX_IN_PROGRESS if self.session else WorkflowState.READY
