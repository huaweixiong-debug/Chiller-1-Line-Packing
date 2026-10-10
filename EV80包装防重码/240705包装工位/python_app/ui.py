from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .db import InspectionRepository
from .models import PACKAGE_SIZE, StationConfig, WorkflowState
from .printer import LabelPrinter
from .scanner import ScanFrame, ScanGate, ScannerService
from .state_store import LegacyStateStore
from .workflow import PackagingWorkflow, WorkflowSnapshot

try:
    from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout,
                                   QFrame, QGridLayout, QHBoxLayout,
                                   QComboBox, QLabel, QLineEdit, QMainWindow, QMessageBox,
                                   QProgressBar, QPushButton, QVBoxLayout, QWidget)
except ImportError:
    QApplication = None

log = logging.getLogger(__name__)


def slot_grid_positions(size: int = PACKAGE_SIZE) -> list[tuple[int, int]]:
    """The legacy product panel is a single column of twelve touch rows."""
    return [(index, 0) for index in range(size)]


def classify_scan(code: str, config: StationConfig) -> str:
    """按条码长度区分类型：达到客户码最小长度按客户码包装，否则按流水码查询。"""
    return "customer" if len(code) >= config.pack_min_length else "serial"


if QApplication is not None:
    class WorkflowBridge(QObject):
        snapshot = Signal(object)
        failure = Signal(str)
        scan_frame = Signal(object)
        conn_status = Signal(str, bool)


    class AdminAuthDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("管理员验证")
            self.setMinimumWidth(320)
            layout = QVBoxLayout(self)
            form = QFormLayout()
            self.user_edit = QLineEdit()
            self.pass_edit = QLineEdit()
            self.pass_edit.setEchoMode(QLineEdit.Password)
            form.addRow("用户名", self.user_edit)
            form.addRow("密码", self.pass_edit)
            layout.addLayout(form)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            self.user_edit.setFocus()


    class ProductSlot(QFrame):
        EMPTY_STYLE = "background:#f8fafc; border:1px solid #cbd5e1; border-radius:7px;"
        FILLED_STYLE = "background:#dcfce7; border:2px solid #22c55e; border-radius:7px;"

        def __init__(self, number: int):
            super().__init__()
            self.number = number
            self.product_code = ""
            self.setMinimumHeight(24)
            layout = QHBoxLayout(self)
            layout.setContentsMargins(10, 1, 10, 1)
            self.number_label = QLabel(f"{number:02d}")
            self.number_label.setFixedWidth(34)
            self.code_label = QLabel("等待扫码")
            self.code_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.status_label = QLabel("")
            self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.addWidget(self.number_label)
            layout.addWidget(self.code_label, 1)
            layout.addWidget(self.status_label)
            self.clear_product()

        def set_product(self, code: str) -> None:
            self.product_code = code
            self.setStyleSheet(self.FILLED_STYLE)
            self.number_label.setStyleSheet("font-weight:700; color:#15803d;")
            self.code_label.setStyleSheet("font-weight:700; color:#166534;")
            self.status_label.setStyleSheet("font-weight:700; color:#15803d;")
            self.code_label.setText(code)
            self.status_label.setText("已扫码")

        def clear_product(self) -> None:
            self.product_code = ""
            self.setStyleSheet(self.EMPTY_STYLE)
            self.number_label.setStyleSheet("font-weight:700; color:#64748b;")
            self.code_label.setStyleSheet("color:#94a3b8;")
            self.status_label.setText("")
            self.code_label.setText("等待扫码")


    class StatusLamp(QFrame):
        def __init__(self, title: str):
            super().__init__()
            self.setMinimumSize(104, 78)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(6, 3, 6, 3)
            layout.setSpacing(2)
            self.title_label = QLabel(title)
            self.title_label.setAlignment(Qt.AlignCenter)
            self.lamp = QLabel()
            self.lamp.setFixedSize(38, 38)
            self.lamp.setAlignment(Qt.AlignCenter)
            self.value_label = QLabel("待查询")
            self.value_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.title_label)
            layout.addWidget(self.lamp, 0, Qt.AlignCenter)
            layout.addWidget(self.value_label)
            self.set_state("idle", "待查询")

        def set_state(self, state: str, value: str) -> None:
            colors = {"idle": "#94a3b8", "success": "#22c55e", "error": "#dc2626"}
            color = colors.get(state, colors["idle"])
            self.lamp.setStyleSheet(
                f"background:{color}; border:2px solid #ffffff; border-radius:21px;"
                " padding:0;"
            )
            self.value_label.setText(value)
            self.value_label.setStyleSheet(f"font-size:14px; font-weight:700; color:{color};")
            background = {"idle": "#f8fafc", "success": "#f0fdf4", "error": "#fef2f2"}[state]
            border = {"idle": "#e2e8f0", "success": "#86efac", "error": "#fca5a5"}[state]
            self.setStyleSheet(f"background:{background}; border:1px solid {border}; border-radius:12px;")


    class MainWindow(QMainWindow):
        def __init__(self, config: StationConfig):
            super().__init__()
            self.config = config
            self.bridge = WorkflowBridge()
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="packaging-worker")
            self.workflow = PackagingWorkflow(
                InspectionRepository(config), LegacyStateStore(config), LabelPrinter(config),
                self.bridge.snapshot.emit,
            )
            self.scanner = ScannerService(
                config.scanner_host, config.scanner_port, config.scanner_timeout,
                config.serial_length, config.scanner_trigger, mode=config.scanner_mode,
                com_port=config.scanner_com_port, baudrate=config.scanner_baudrate,
                bytesize=config.scanner_bytesize, parity=config.scanner_parity,
                stopbits=config.scanner_stopbits,
            )
            self.scanner_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scanner-worker")
            self.scanner_stop = threading.Event()
            self.scan_gate = ScanGate()
            self.check_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="conn-check")
            self.conn_states = {"db": None, "scanner": None, "printer": None}
            self.conn_timer = QTimer(self)
            self.conn_timer.setInterval(30000)
            self.conn_timer.timeout.connect(self._submit_conn_check)
            self._completion_hold = False
            self._last_snapshot: WorkflowSnapshot | None = None
            self._mode = "serial"
            self.rework_mode = False
            self._last_warned_at = None
            self.setWindowTitle(config.station_name)
            self.setMinimumSize(1024, 660)
            self._build_ui()
            self.completion_timer = QTimer(self)
            self.completion_timer.setSingleShot(True)
            self.completion_timer.timeout.connect(self._finish_completion_hold)
            self.bridge.snapshot.connect(self._render)
            self.bridge.failure.connect(self._show_error)
            self.bridge.scan_frame.connect(self._handle_frame)
            self.bridge.conn_status.connect(self._render_conn)
            self.scanner_executor.submit(self._scan_loop)
            QTimer.singleShot(0, self._startup)
            self.conn_timer.start()
            self._submit_conn_check()

        def _build_ui(self) -> None:
            self.setStyleSheet("""
                QWidget { background:#e9e9e9; color:#1f2937; font-family:'Segoe UI Variable','Microsoft YaHei'; font-size:16px; }
                QLabel { background:transparent; }
                QFrame#panel { background:#f4f4f4; border:1px solid #cbd5e1; border-radius:12px; }
                QLabel#title { font-size:24px; font-weight:700; padding:8px 14px; background:#f1f5f9; border:1px solid #cbd5e1; border-radius:8px; }
                QLabel#sectionTitle { font-size:16px; font-weight:700; }
                QLabel#status { font-size:21px; font-weight:700; padding:14px; border-radius:10px; background:#eaf2ff; }
                QLineEdit { min-height:42px; padding:0 10px; border:1px solid #b8c2cf; border-radius:7px; background:#ffffff; }
                QLineEdit:disabled { background:#e5e7eb; color:#94a3b8; }
                QPushButton { min-height:48px; padding:0 16px; border:1px solid #94a3b8; border-radius:8px; background:#f8fafc; color:#1f2937; font-weight:600; }
                QPushButton:hover { background:#dbeafe; }
                QPushButton:disabled { background:#d1d5db; color:#6b7280; }
                QPushButton#closeButton { background:#64748b; border:0; color:#ffffff; min-width:96px; }
                QPushButton#closeButton:hover { background:#475569; }
                QPushButton#reworkToggle { min-height:40px; }
                QPushButton#reworkToggle:checked { background:#f59e0b; border:0; color:#ffffff; }
                QPushButton#reworkToggle:checked:hover { background:#d97706; }
                QProgressBar { min-height:22px; border:1px solid #cbd5e1; border-radius:8px; background:#e5e7eb; text-align:center; font-weight:700; }
                QProgressBar::chunk { border-radius:7px; background:#22c55e; }
            """)
            root = QWidget()
            self.setCentralWidget(root)
            layout = QVBoxLayout(root)
            layout.setContentsMargins(26, 20, 26, 20)
            layout.setSpacing(12)

            title_row = QHBoxLayout()
            self.title = QLabel("协众国际热管理系统（江苏）股份有限公司 Chiller #2线包装工位")
            self.title.setObjectName("title")
            title_row.addWidget(self.title)
            title_row.addStretch()
            self.conn = QLabel("数据库 检查中  ·  扫码器 检查中  ·  BarTender 检查中")
            self.conn.setTextFormat(Qt.RichText)
            title_row.addWidget(self.conn)
            self.close_button = QPushButton("关闭")
            self.close_button.setObjectName("closeButton")
            self.close_button.clicked.connect(self._confirm_close)
            title_row.addWidget(self.close_button)
            layout.addLayout(title_row)

            top = QFrame()
            top.setObjectName("panel")
            top_grid = QGridLayout(top)
            top_grid.setContentsMargins(12, 8, 12, 8)
            top_grid.setHorizontalSpacing(10)
            top_grid.setVerticalSpacing(5)
            self.box_sequence = self._field("箱码序号", "—", read_only=True)
            self.pack_count = self._field("包装累计", "0", read_only=True)
            self.model_field = self._field("产品型号", "—", read_only=True)
            self.current_box = self._field("当前箱码", "—", read_only=True)
            self.online_count = self._field("检测记录数", "—", read_only=True)
            self.customer_scan = self._field("扫码结果（上线码）-包装用", "请输入 22 位上线码")
            self.serial_scan = self._field("扫码结果（流水码）-仅查询", "请输入 22 位流水码")
            top_grid.addWidget(self.box_sequence[0], 0, 0); top_grid.addWidget(self.box_sequence[1], 0, 1)
            top_grid.addWidget(self.pack_count[0], 0, 2); top_grid.addWidget(self.pack_count[1], 0, 3)
            top_grid.addWidget(self.model_field[0], 0, 4); top_grid.addWidget(self.model_field[1], 0, 5)
            top_grid.addWidget(self.customer_scan[0], 0, 6); top_grid.addWidget(self.customer_scan[1], 0, 7, 1, 3)
            top_grid.addWidget(self.current_box[0], 1, 0); top_grid.addWidget(self.current_box[1], 1, 1)
            top_grid.addWidget(self.online_count[0], 1, 2); top_grid.addWidget(self.online_count[1], 1, 3)
            top_grid.addWidget(self.serial_scan[0], 1, 6); top_grid.addWidget(self.serial_scan[1], 1, 7, 1, 3)
            top_grid.setColumnStretch(7, 2)
            layout.addWidget(top)
            self.customer_scan[1].returnPressed.connect(lambda: self._submit_scan("customer"))
            self.serial_scan[1].returnPressed.connect(lambda: self._submit_scan("serial"))
            self.scan = self.serial_scan[1]

            body = QGridLayout()
            body.setSpacing(12)
            layout.addLayout(body, 1)
            left = QFrame(); left.setObjectName("panel")
            left_layout = QVBoxLayout(left); left_layout.setContentsMargins(10, 8, 10, 8); left_layout.setSpacing(5)
            self.status = QLabel("系统启动中"); self.status.setObjectName("status"); self.status.setAlignment(Qt.AlignCenter); self.status.setWordWrap(True)
            left_layout.addWidget(self.status)
            self.status_lamps = {}
            lamp_grid = QGridLayout(); lamp_grid.setSpacing(6)
            for index, title in enumerate(("干检", "氦检", "拧紧", "视觉检测", "包装完成", "重复包装")):
                card = StatusLamp(title); self.status_lamps[title] = card
                lamp_grid.addWidget(card, index // 3, index % 3)
            left_layout.addLayout(lamp_grid, 1)
            alert_row = QHBoxLayout()
            self.alert_lamp = QLabel(); self.alert_lamp.setFixedSize(24, 24)
            self.alert_text = QLabel("扫码状态正常")
            alert_row.addWidget(self.alert_lamp); alert_row.addWidget(self.alert_text, 1)
            left_layout.addLayout(alert_row)
            progress_row = QHBoxLayout(); progress_row.setSpacing(8)
            self.details = QLabel("型号：—   箱码：—")
            progress_row.addWidget(self.details, 3)
            self.progress = QProgressBar(); self.progress.setRange(0, PACKAGE_SIZE); self.progress.setFormat("0 / 12")
            progress_row.addWidget(self.progress, 2)
            left_layout.addLayout(progress_row)
            control_row = QHBoxLayout(); control_row.setSpacing(8)
            self.retry = QPushButton("检查恢复"); self.retry.clicked.connect(self._recovery)
            self.rework_toggle = QPushButton("回退模式：关"); self.rework_toggle.setObjectName("reworkToggle")
            self.rework_toggle.setCheckable(True); self.rework_toggle.toggled.connect(self._toggle_rework)
            self.reset_button = QPushButton("复位本箱"); self.reset_button.clicked.connect(self._reset_box)
            control_row.addWidget(self.retry); control_row.addWidget(self.rework_toggle); control_row.addWidget(self.reset_button)
            left_layout.addLayout(control_row)
            body.addWidget(left, 0, 0)

            right = QFrame(); right.setObjectName("panel")
            right_layout = QVBoxLayout(right); right_layout.setContentsMargins(8, 8, 8, 8); right_layout.setSpacing(4)
            right_layout.addWidget(QLabel("装箱产品（固定 12 件）"))
            self.product_slots = [ProductSlot(index + 1) for index in range(PACKAGE_SIZE)]
            for slot, (row, column) in zip(self.product_slots, slot_grid_positions()):
                right_layout.addWidget(slot)
            body.addWidget(right, 0, 1)
            body.setColumnStretch(0, 4); body.setColumnStretch(1, 5)
            self.chery_part_combo = None
            self.chery_batch_edit = None
            self.chery_qty_edit = None
            self.chery_layers_edit = None
            if self.config.chery.enabled:
                from .chery_qr import PARTS, get_part
                chery_box = QFrame()
                chery_box.setObjectName("panel")
                chery_row = QHBoxLayout(chery_box)
                chery_row.setContentsMargins(8, 2, 8, 2)
                chery_row.setSpacing(6)
                chery_title = QLabel("奇瑞 KD")
                chery_title.setObjectName("sectionTitle")
                chery_row.addWidget(chery_title)
                self.chery_part_combo = QComboBox()
                for part in PARTS:
                    self.chery_part_combo.addItem(
                        f"{part['part_no']} · {part['name']}", part["part_no"])
                idx = self.chery_part_combo.findData(self.config.chery.part_no)
                if idx >= 0:
                    self.chery_part_combo.setCurrentIndex(idx)
                chery_row.addWidget(self.chery_part_combo)
                self.chery_batch_edit = QLineEdit(self.config.chery.batch)
                self.chery_batch_edit.setPlaceholderText("发运批次")
                chery_row.addWidget(QLabel("批次"))
                chery_row.addWidget(self.chery_batch_edit)
                current_part = self.chery_part_combo.currentData()
                try:
                    default_qty = str(get_part(current_part)["qty"])
                except (ValueError, TypeError):
                    default_qty = ""
                self.chery_qty_edit = QLineEdit(self.config.chery.qty_override or default_qty)
                self.chery_qty_edit.setPlaceholderText("数量")
                chery_row.addWidget(QLabel("数量"))
                chery_row.addWidget(self.chery_qty_edit)
                self.chery_layers_edit = QLineEdit(self.config.chery.layers)
                self.chery_layers_edit.setPlaceholderText("层数")
                chery_row.addWidget(QLabel("层数"))
                chery_row.addWidget(self.chery_layers_edit)
                chery_row.addStretch(1)
                self.chery_batch_edit.ensurePolished()
                metrics = self.chery_batch_edit.fontMetrics()
                char_width = metrics.horizontalAdvance("0")
                self.chery_part_combo.setFixedWidth(char_width * 12 + 30)
                self.chery_batch_edit.setFixedWidth(char_width * 16 + 24)
                self.chery_qty_edit.setFixedWidth(char_width * 5 + 18)
                self.chery_layers_edit.setFixedWidth(char_width * 5 + 18)
                self.chery_part_combo.setToolTip("奇瑞 KD 零件号（决定二维码载荷，选定后自动带出每箱默认数量）")
                self.chery_batch_edit.setToolTip("发运批次（手动输入，按 16 字符宽度）")
                self.chery_qty_edit.setToolTip("每箱包装数量（默认取零件表，可手动修改）")
                self.chery_part_combo.currentIndexChanged.connect(self._on_chery_part_changed)
                self.chery_batch_edit.textChanged.connect(self._sync_chery_fields)
                self.chery_qty_edit.textChanged.connect(self._sync_chery_fields)
                self.chery_layers_edit.textChanged.connect(self._sync_chery_fields)
                layout.addWidget(chery_box)
                self._sync_chery_fields()
            self.log_label = QLabel("状态：系统启动")
            layout.addWidget(self.log_label)
            self._set_alert("normal", "扫码状态正常")
            self._set_input_enabled(False)

        @staticmethod
        def _field(label: str, placeholder: str, read_only: bool = False):
            text = QLabel(label); text.setObjectName("sectionTitle")
            edit = QLineEdit(); edit.setPlaceholderText(placeholder); edit.setReadOnly(read_only)
            if read_only: edit.setText(placeholder)
            return text, edit


        def _on_chery_part_changed(self, *_args) -> None:
            """切换零件后自动带出该零件表里的每箱默认数量（仍可手动改）。"""
            if not self.config.chery.enabled or self.chery_qty_edit is None:
                return
            from .chery_qr import get_part
            try:
                default_qty = str(get_part(self.chery_part_combo.currentData())["qty"])
            except (ValueError, TypeError):
                default_qty = ""
            self.chery_qty_edit.setText(default_qty)
            self._sync_chery_fields()

        def _sync_chery_fields(self, *_args) -> None:
            if not self.config.chery.enabled:
                return
            part_no = self.chery_part_combo.currentData() if self.chery_part_combo else None
            batch = self.chery_batch_edit.text() if self.chery_batch_edit else ""
            layers = self.chery_layers_edit.text() if self.chery_layers_edit else ""
            qty = self.chery_qty_edit.text() if self.chery_qty_edit else ""
            self.workflow.set_chery_fields(part_no=part_no, batch=batch, layers=layers, qty=qty)

        def _set_mode(self, mode: str) -> None:
            self._mode = mode
            self.scan = self.customer_scan[1] if mode == "customer" else self.serial_scan[1]
            self.scan.setFocus()

        def _scan_loop(self) -> None:
            while not self.scanner_stop.is_set():
                if not self.scan_gate.wait(0.2): continue
                try:
                    raw = self.scanner.read_once()
                    mode = classify_scan(raw.code, self.config)
                    if self.scan_gate.begin(): self.bridge.scan_frame.emit(ScanFrame(raw.code, mode))
                except Exception:
                    time.sleep(1)
                finally:
                    self.bridge.conn_status.emit("scanner", self.scanner.last_online)

        @Slot(object)
        def _handle_frame(self, frame) -> None:
            self._set_mode(frame.mode)
            self.scan.setText(frame.code)
            self._submit_code(frame.code, gate_acquired=True)

        def _startup(self) -> None: self._run(self.workflow.startup_check)

        def _submit_scan(self, mode: str) -> None:
            self._set_mode(mode)
            code = self.scan.text().strip(); self.scan.clear()
            if code and self.scan_gate.begin(): self._submit_code(code, gate_acquired=True)

        def _submit_code(self, code: str, gate_acquired: bool = False) -> None:
            if not gate_acquired and not self.scan_gate.begin(): return
            self._set_input_enabled(False); self.status.setText("正在校验，请稍候…")
            if self._mode == "serial":
                operation = self.workflow.inspect_serial
            elif self.rework_mode:
                operation = self.workflow.rework_scan
            else:
                operation = self.workflow.process_customer_scan
            self._run(operation, code)

        def _recovery(self) -> None:
            self.scan_gate.pause(); self._set_input_enabled(False); self._run(self.workflow.retry_recovery)

        def _run(self, fn, *args) -> None:
            future = self.executor.submit(fn, *args); future.add_done_callback(self._complete)

        def _complete(self, future) -> None:
            try: future.result()
            except Exception as exc: self.bridge.failure.emit(str(exc))

        @Slot(object)
        def _render(self, snapshot: WorkflowSnapshot) -> None:
            self._last_snapshot = snapshot
            self.status.setText(snapshot.message or snapshot.state.value)
            duplicate_flag = bool(snapshot.last_result and snapshot.last_result.is_duplicate)
            if duplicate_flag or snapshot.state is WorkflowState.ERROR_BLOCKED:
                self.status.setStyleSheet("background:#dc2626; color:#ffffff;")
            elif snapshot.box_completed:
                self.status.setStyleSheet("background:#16a34a; color:#ffffff;")
            else:
                self.status.setStyleSheet("")
            if snapshot.popup:
                QMessageBox.warning(self, "装箱未完成", snapshot.popup)
            self.current_box[1].setText(snapshot.current_box or "—")
            self.pack_count[1].setText(str(snapshot.box_count))
            self.progress.setValue(snapshot.box_count); self.progress.setFormat(f"{snapshot.box_count} / {PACKAGE_SIZE}")
            self.log_label.setText(f"状态：{snapshot.state.value}  ·  {snapshot.message}")
            self._render_slots(snapshot.products or [])
            self._render_status_lamps(snapshot)
            scan_result = snapshot.last_result
            if (scan_result and scan_result.mode == "customer" and not scan_result.can_package
                    and not scan_result.is_duplicate
                    and scan_result.checked_at != self._last_warned_at):
                self._last_warned_at = scan_result.checked_at
                QMessageBox.warning(self, "不允许装箱", snapshot.message)
            if snapshot.last_result:
                result = snapshot.last_result
                self.model_field[1].setText(result.model or "—")
                self.online_count[1].setText(str(result.online_count or "—"))
                self.details.setText(f"型号：{result.model or '—'}   箱码：{result.box_code or '未包装'}")
            if snapshot.state is WorkflowState.ERROR_BLOCKED:
                self.scan_gate.resolve(False); self._set_input_enabled(False); self.retry.setEnabled(True); self._set_alert("error", snapshot.message); return
            if snapshot.box_completed:
                self._completion_hold = True; self.scan_gate.resolve(False); self._set_input_enabled(False); self._set_alert("success", "12 件全部完成，箱码已打印"); self.completion_timer.start(2000); return
            if snapshot.state in (WorkflowState.READY, WorkflowState.BOX_IN_PROGRESS):
                if duplicate_flag: self._set_alert("error", snapshot.message)
                else: self._set_alert("normal", "扫码状态正常")
                self.scan_gate.resolve(True); self._set_input_enabled(True); self.scan.setFocus()
            else:
                self.scan_gate.resolve(False); self._set_input_enabled(False)

        def _render_slots(self, products: list[str]) -> None:
            for index, slot in enumerate(self.product_slots):
                slot.set_product(products[index]) if index < len(products) else slot.clear_product()

        def _render_status_lamps(self, snapshot: WorkflowSnapshot) -> None:
            for lamp in self.status_lamps.values(): lamp.set_state("idle", "待查询")
            result = snapshot.last_result
            if result:
                self._set_result_lamp("干检", result.dry_test, active=self.config.checks.dry_test)
                self._set_result_lamp("氦检", result.helium_test, active=self.config.checks.helium)
                self._set_result_lamp("拧紧", result.tightening_test, active=self.config.checks.tightening)
                self._set_result_lamp("视觉检测", result.vision_test, active=self.config.checks.vision,
                                      unset=not self.config.columns.vision_result)
                if result.already_boxed: self.status_lamps["包装完成"].set_state("success", "已包装")
                if result.is_duplicate: self.status_lamps["重复包装"].set_state("error", "重码")
            if snapshot.box_completed: self.status_lamps["包装完成"].set_state("success", "已完成")

        def _set_result_lamp(self, title: str, value: str, active: bool = True, unset: bool = False) -> None:
            """active=True 的工序参与阻断核验（红色=拦截）；unset=True 表示该工序尚未接入数据列。"""
            if unset:
                self.status_lamps[title].set_state("idle", "未接入")
                return
            normalized = (value or "").strip().upper()
            if normalized == "OK":
                self.status_lamps[title].set_state("success", "通过")
            elif normalized:
                self.status_lamps[title].set_state("error" if active else "idle", value)
            else:
                self.status_lamps[title].set_state("idle", "无记录")

        def _set_alert(self, level: str, text: str) -> None:
            color = {"normal": "#94a3b8", "success": "#22c55e", "error": "#dc2626"}[level]
            self.alert_lamp.setStyleSheet(f"background:{color}; border-radius:12px;")
            self.alert_text.setText(text); self.alert_text.setStyleSheet("font-weight:700; color:#b91c1c;" if level == "error" else "font-weight:600; color:#334155;")

        def _set_input_enabled(self, enabled: bool) -> None:
            self.customer_scan[1].setEnabled(enabled); self.serial_scan[1].setEnabled(enabled)
            self.retry.setEnabled(enabled)

        def _finish_completion_hold(self) -> None:
            if not self._completion_hold or self.workflow.state is not WorkflowState.READY: return
            self._completion_hold = False; self._render_slots([]); self._render_status_lamps(WorkflowSnapshot(WorkflowState.READY)); self.progress.setValue(0); self.progress.setFormat("0 / 12"); self.current_box[1].setText("—"); self.status.setText("上一箱已完成，请扫描下一箱"); self._set_alert("normal", "扫码状态正常"); self.scan_gate.resolve(True); self._set_input_enabled(True); self.scan.setFocus()

        @Slot(str)
        def _show_error(self, message: str) -> None:
            self.status.setText(message); log.error("界面操作失败: %s", message)

        def _confirm_close(self) -> None:
            answer = QMessageBox.question(self, "关闭确认", "确定要关闭包装工位程序吗？",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                self.close()

        def _toggle_rework(self, checked: bool) -> None:
            if checked:
                dialog = AdminAuthDialog(self)
                while True:
                    if dialog.exec() != QDialog.Accepted:
                        self.rework_toggle.blockSignals(True)
                        self.rework_toggle.setChecked(False)
                        self.rework_toggle.blockSignals(False)
                        self._set_alert("normal", "管理员验证取消，回退模式未开启")
                        return
                    if (dialog.user_edit.text().strip() == self.config.admin_username
                            and dialog.pass_edit.text() == self.config.admin_password):
                        break
                    self._set_alert("error", "管理员用户名或密码错误，回退模式未开启")
                self.rework_mode = True
                self.rework_toggle.setText("回退模式：开")
                self._set_alert("normal", "回退模式已开启（管理员）：扫已包装产品将解除原箱码并重新装箱")
            else:
                self.rework_mode = False
                self.rework_toggle.setText("回退模式：关")
                self._set_alert("normal", "回退模式已关闭")

        def _reset_box(self) -> None:
            answer = QMessageBox.question(self, "复位确认", "确定清除本箱已扫的全部产品，重新开始装箱吗？",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                self.scan_gate.pause(); self._set_input_enabled(False); self.status.setText("正在复位，请稍候…")
                self._run(self.workflow.reset_box)

        def _submit_conn_check(self) -> None:
            self.check_executor.submit(self._conn_check_worker)

        def _conn_check_worker(self) -> None:
            self.bridge.conn_status.emit("db", self._check_db())
            self.bridge.conn_status.emit("printer", self._check_printer())

        def _check_db(self) -> bool:
            try:
                with self.workflow.repository.connection():
                    return True
            except Exception:
                return False

        def _check_printer(self) -> bool:
            return (Path(self.config.bartend_exe).exists()
                    and Path(self.config.label_template).exists())

        def _render_conn(self, name: str, ok: bool) -> None:
            self.conn_states[name] = ok
            titles = (("db", "数据库"), ("scanner", "扫码器"), ("printer", "BarTender"))
            parts = []
            for key, title in titles:
                state = self.conn_states[key]
                if state is None:
                    color, text = "#64748b", f"{title} 检查中"
                elif state:
                    color, text = "#16a34a", f"{title} 在线"
                else:
                    color, text = "#dc2626", f"{title} 离线"
                parts.append(f'<span style="color:{color}; font-weight:600;">{text}</span>')
            self.conn.setText(' &nbsp;·&nbsp; '.join(parts))

        def closeEvent(self, event) -> None:
            self.conn_timer.stop(); self.check_executor.shutdown(wait=False, cancel_futures=True)
            self.completion_timer.stop(); self.scan_gate.pause(); self.scanner_stop.set(); self.scanner.stop(); self.scanner_executor.shutdown(wait=False, cancel_futures=True); self.executor.shutdown(wait=False, cancel_futures=True); event.accept()


    def run_ui(config: StationConfig) -> int:
        app = QApplication.instance() or QApplication([]); app.setFont(QFont("Segoe UI Variable", 16)); window = MainWindow(config); window.showMaximized(); return app.exec()
else:
    def run_ui(config: StationConfig) -> int:
        raise ImportError("PySide6 is required")
