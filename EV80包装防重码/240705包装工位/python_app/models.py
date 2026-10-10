from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


PACKAGE_SIZE = 12


class WorkflowState(str, Enum):
    STARTUP_CHECK = "STARTUP_CHECK"
    READY = "READY"
    VALIDATING = "VALIDATING"
    BOX_IN_PROGRESS = "BOX_IN_PROGRESS"
    FINALIZING = "FINALIZING"
    DUPLICATE_BLOCKED = "DUPLICATE_BLOCKED"
    ERROR_BLOCKED = "ERROR_BLOCKED"


@dataclass
class ColumnMap:
    """information 表的列名映射，现场表结构随产品变化时只改配置。"""
    code: str = "上线码"
    time: str = "测试时间"
    dry_result: str = "干检结果"
    helium_result: str = "氦检结果"
    tightening_result: str = "拧紧结果"
    vision_result: str = ""  # 视觉检测结果列名；空 = 现场表还没有这一列（灯显示“未接入”）
    box: str = "装箱码"
    model: str = "产品型号"


@dataclass
class CheckSwitches:
    """装箱审核开关。当前只激活干检核验，其余工序仅显示不阻断。"""
    dry_test: bool = True
    helium: bool = False
    tightening: bool = False
    vision: bool = False
    duplicate: bool = True



@dataclass
class CheryLabelConfig:
    """可选奇瑞 KD 标签二维码；默认关闭，不影响现有 BarTender 上线码文件。"""
    enabled: bool = False
    part_no: str = "30100351AA"
    batch: str = ""
    layers: str = ""
    qty_override: str = ""  # 空则用零件表默认包装数量
    qr_payload_file: str = r"D:\奇瑞二维码.txt"
    counters_file: str = r"%ProgramData%\PackagingStation\chery_counters.json"


@dataclass
class StationConfig:
    db_host: str = "192.168.3.100"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "test"
    scanner_mode: str = "tcp"
    scanner_host: str = "192.168.3.69"
    scanner_port: int = 9004
    scanner_com_port: str = "COM1"
    scanner_baudrate: int = 9600
    scanner_bytesize: int = 8
    scanner_parity: str = "N"
    scanner_stopbits: int = 1
    scanner_timeout: float = 5.0
    serial_length: int = 22
    pack_min_length: int = 26
    scanner_trigger: bytes = b"LON\r"
    bartend_exe: str = r"C:\Program Files\Seagull\BarTender Suite\bartend.exe"
    label_template: str = r"D:\Label.btw"
    quantity_file: str = r"D:\数量.txt"
    final_box_file: str = r"D:\最终装箱码.txt"
    box_sequence_file: str = r"D:\箱码.txt"
    laser_archive_dir: str = r"D:\装箱激光码"
    journal_file: str = r"%ProgramData%\PackagingStation\box_journal.json"
    session_file: str = r"%ProgramData%\PackagingStation\box_session.json"
    station_name: str = "包装工位"
    box_quantity: int = PACKAGE_SIZE
    chery: CheryLabelConfig = field(default_factory=CheryLabelConfig)
    admin_username: str = "admin"
    admin_password: str = "admin123"
    columns: ColumnMap = field(default_factory=ColumnMap)
    checks: CheckSwitches = field(default_factory=CheckSwitches)


@dataclass
class InspectionResult:
    scan_code: str
    mode: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    dry_test: str = ""
    helium_test: str = ""
    tightening_test: str = ""
    vision_test: str = ""
    box_code: str = ""
    online_count: int = 0
    already_boxed: bool = False
    is_duplicate: bool = False
    duplicate_source: str = ""
    can_package: bool = False
    reason: str = ""
    checked_at: datetime = field(default_factory=datetime.now)


@dataclass
class BoxSession:
    box_code: str
    products: list[str] = field(default_factory=list)
    target_quantity: int = PACKAGE_SIZE
    started_at: datetime = field(default_factory=datetime.now)

    @property
    def count(self) -> int:
        return len(self.products)

    @property
    def complete(self) -> bool:
        return self.target_quantity > 0 and self.count >= self.target_quantity


@dataclass
class FinalizationJournal:
    box_code: str
    products: list[str]
    phase: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
