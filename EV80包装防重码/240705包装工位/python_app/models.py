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


@dataclass(frozen=True)
class FieldMap:
    dry_test: int = 3
    nitrogen_test: int = 7
    package_gate: int = 9
    station: int = 22
    customer_code: int = 23
    box_code: int = 24
    drying_date: int = 17


@dataclass
class StationConfig:
    db_host: str = "192.168.3.140"
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
    customer_min_length: int = 26
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
    admin_username: str = "admin"
    admin_password: str = "admin123"
    field_map: FieldMap = field(default_factory=FieldMap)


@dataclass
class InspectionResult:
    scan_code: str
    mode: str
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    station: str = ""
    dry_test: str = ""
    nitrogen_test: str = ""
    customer_code: str = ""
    box_code: str = ""
    package_gate: str = ""
    online_count: int = 0
    customer_count: int = 0
    has_customer_code: bool = False
    already_boxed: bool = False
    is_duplicate: bool = False
    duplicate_source: str = ""
    can_package: bool = False
    reason: str = ""
    checked_at: datetime = field(default_factory=datetime.now)
    drying_status: str = ""
    helium_test: str = ""
    cleaning_status: str = ""


@dataclass
class BoxSession:
    box_code: str
    target_quantity: int = field(default=PACKAGE_SIZE, init=False)
    products: list[str] = field(default_factory=list)
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
