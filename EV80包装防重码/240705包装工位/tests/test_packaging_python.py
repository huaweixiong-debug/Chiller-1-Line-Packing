from pathlib import Path

import pytest

from python_app.models import (BoxSession, FinalizationJournal, InspectionResult, PACKAGE_SIZE,
                               StationConfig, WorkflowState)
from python_app.db import InspectionRepository
from python_app.printer import LabelPrinter, PrinterError
from python_app.state_store import LegacyStateStore
from python_app.workflow import PackagingWorkflow, WorkflowError
from python_app.scanner import ScanGate, ScannerService
import socket
import threading
import time


class FakeCursor:
    def __init__(self, rows=()): self.rows = list(rows); self.executed = []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, args=()): self.executed.append((sql, args)); self.rowcount = 1
    def fetchall(self): return self.rows


class FakeConn:
    def __init__(self, rows=()): self.cursor_obj = FakeCursor(rows); self.committed = False
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def cursor(self): return self.cursor_obj
    def commit(self): self.committed = True
    def close(self): pass


def test_inspection_uses_parameterized_query():
    conn = FakeConn([("x", "", "", "OK", "", "", "", "OK", "", "laser", *([""] * 12), "station", "customer", "")])
    repo = InspectionRepository(StationConfig(), connector=lambda **kwargs: conn)
    result = repo.inspect_serial("a' OR 1=1")
    assert result.can_package is True
    assert conn.cursor_obj.executed[0][1] == ("a' OR 1=1",)


def test_inspection_marks_existing_box_as_database_duplicate():
    row = [""] * 25
    row[3], row[7], row[9] = "OK", "OK", "gate"
    row[22], row[23], row[24] = "station", "CUSTOMER-CODE", "OLD-BOX-001"
    conn = FakeConn([tuple(row)])
    result = InspectionRepository(StationConfig(), connector=lambda **kwargs: conn).inspect_customer("LASER")
    assert result.can_package is False
    assert result.is_duplicate is True
    assert result.duplicate_source == "database"
    assert "OLD-BOX-001" in result.reason


def test_inspect_customer_blocks_missing_drying_or_checks():
    def make_repo(row):
        return InspectionRepository(StationConfig(), connector=lambda **kwargs: FakeConn([tuple(row)]))

    row = [""] * 25
    row[3], row[7] = "OK", "OK"
    row[17] = "2026-09-09 05:10:38"
    row[23] = "CUSTOMER-CODE"
    ok_result = make_repo(row).inspect_customer("LASER")
    assert ok_result.can_package is True
    assert ok_result.reason == "客户码校验通过"

    row[17] = ""
    no_drying = make_repo(row).inspect_customer("LASER")
    assert no_drying.can_package is False
    assert "无烘干记录" in no_drying.reason

    row[17] = "2026-09-09 05:10:38"
    row[3] = "NG"
    bad_dry = make_repo(row).inspect_customer("LASER")
    assert bad_dry.can_package is False
    assert "干检未通过（NG）" in bad_dry.reason

    row[3] = ""
    no_dry_check = make_repo(row).inspect_customer("LASER")
    assert no_dry_check.can_package is False
    assert "干检未完成（无记录）" in no_dry_check.reason

    row[3] = "OK"
    row[7] = ""
    bad_helium = make_repo(row).inspect_customer("LASER")
    assert bad_helium.can_package is False
    assert "氦检未完成（无记录）" in bad_helium.reason


def test_config_loads_admin_credentials(tmp_path):
    from python_app.config import load_config
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[admin]\nusername = "boss"\npassword = "secret"\n', encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.admin_username == "boss"
    assert cfg.admin_password == "secret"


def test_state_store_box_code_and_atomic_archive(tmp_path):
    cfg = StationConfig(quantity_file=str(tmp_path / "数量.txt"), final_box_file=str(tmp_path / "最终.txt"), box_sequence_file=str(tmp_path / "序号.txt"), laser_archive_dir=str(tmp_path / "archive"), journal_file=str(tmp_path / "journal.json"))
    (tmp_path / "数量.txt").write_text("not-a-number", encoding="utf-8")
    (tmp_path / "最终.txt").write_text("BOX", encoding="utf-8")
    (tmp_path / "序号.txt").write_text("7", encoding="utf-8")
    store = LegacyStateStore(cfg)
    assert store.target_quantity() == PACKAGE_SIZE
    box_code = store.next_box_code()
    assert box_code.endswith("00007")
    assert len(box_code) == 13
    store.archive_products("BOX20260831007", ["a", "b"])
    assert (tmp_path / "archive" / "BOX20260831007.txt").read_text(encoding="mbcs").splitlines() == ["a", "b"]


def test_state_store_writes_print_files_for_bartender(tmp_path):
    cfg = StationConfig(quantity_file=str(tmp_path / "数量.txt"), final_box_file=str(tmp_path / "最终.txt"), box_sequence_file=str(tmp_path / "序号.txt"), laser_archive_dir=str(tmp_path / "archive"), journal_file=str(tmp_path / "journal.json"))
    (tmp_path / "序号.txt").write_text("25810", encoding="utf-8")
    store = LegacyStateStore(cfg)
    products = [f"LASER-{index:02d}" for index in range(PACKAGE_SIZE)]
    store.write_print_files("2026090925810", products)
    root = tmp_path
    for index in range(PACKAGE_SIZE):
        assert (root / f"装箱激光码{index}.txt").read_text(encoding="mbcs") == f"LASER-{index:02d}"
    assert not (root / "装箱激光码12.txt").exists()
    assert (root / "数量.txt").read_text(encoding="mbcs") == "12"
    assert (root / "最终.txt").read_text(encoding="mbcs") == "2026090925810"
    store.advance_box_sequence()
    assert (root / "序号.txt").read_text(encoding="mbcs") == "25811"
    with pytest.raises(Exception):
        store.write_print_files("2026090925811", products[:11])


def test_workflow_blocks_pending_journal(tmp_path):
    cfg = StationConfig(quantity_file=str(tmp_path / "q"), journal_file=str(tmp_path / "j"))
    Path(cfg.quantity_file).write_text("1", encoding="utf-8")
    store = LegacyStateStore(cfg); store.save_journal(FinalizationJournal("BOX", ["laser"], "DB_UPDATED"))
    flow = PackagingWorkflow(None, store, None)
    snapshot = flow.startup_check()
    assert snapshot.state is WorkflowState.ERROR_BLOCKED
    with pytest.raises(WorkflowError):
        flow.process_customer_scan("LASER-A")


def test_printer_rejects_nonzero_exit():
    cfg = StationConfig()
    def runner(*args, **kwargs): return type("R", (), {"returncode": 3})()
    with pytest.raises(PrinterError): LabelPrinter(cfg, runner).print_label()


def test_scanner_reads_fragmented_serial_frame():
    ready = threading.Event()
    received = []
    server = socket.socket(); server.bind(("127.0.0.1", 0)); server.listen(1)
    def serve():
        ready.set()
        conn, _ = server.accept()
        with conn:
            received.append(conn.recv(32)); conn.sendall(b"ABC"); conn.sendall(b"1234567890123456789")
        server.close()
    thread = threading.Thread(target=serve, daemon=True); thread.start(); ready.wait(1)
    host, port = server.getsockname()
    service = ScannerService(host, port, timeout=1, serial_length=22, trigger_command=b"T")
    assert service.last_online is False
    frame = service.read_once()
    thread.join(1)
    assert frame.code == "ABC1234567890123456789"
    assert service.last_online is True
    assert received == [b"T"]


def test_scanner_returns_on_terminator_without_connection_close():
    ready = threading.Event()
    server = socket.socket(); server.bind(("127.0.0.1", 0)); server.listen(1)
    def serve():
        ready.set()
        conn, _ = server.accept()
        with conn:
            conn.sendall(b"10067057111109260908000215\r\n")
            conn.settimeout(3)
            try:
                conn.recv(32)
            except OSError:
                pass
        server.close()
    thread = threading.Thread(target=serve, daemon=True); thread.start(); ready.wait(1)
    host, port = server.getsockname()
    start = time.monotonic()
    frame = ScannerService(host, port, timeout=2, trigger_command=b"T").read_once()
    elapsed = time.monotonic() - start
    assert frame.code == "10067057111109260908000215"
    assert elapsed < 1.5
    assert frame.mode == "serial"


class MemoryStore:
    def __init__(self):
        self.journal = None
        self.archived = []
        self.sequence_updates = 0
        self.print_files = None
        self.saved_session = None
        self.session_cleared = 0

    def load_journal(self): return self.journal
    def next_box_code(self): return "BOX20260831001"
    def save_journal(self, journal): self.journal = journal
    def archive_products(self, box_code, products): self.archived.append((box_code, list(products)))
    def write_print_files(self, box_code, products): self.print_files = (box_code, list(products))
    def advance_box_sequence(self): self.sequence_updates += 1
    def clear_journal(self): self.journal = None
    def save_session(self, box): self.saved_session = list(box.products)
    def load_session(self): return None
    def clear_session(self): self.session_cleared += 1; self.saved_session = None


class MemoryRepository:
    def __init__(self): self.updates = []; self.released = []; self.release_ok = True
    def inspect_customer(self, code):
        if code == "HISTORY" and code not in [r[0] for r in self.released]:
            return InspectionResult(code, "customer", box_code="OLD001", already_boxed=True,
                                    is_duplicate=True, duplicate_source="database",
                                    reason="该产品已经包装，原箱码：OLD001")
        if code == "INVALID":
            return InspectionResult(code, "customer", reason="工序未通过")
        return InspectionResult(code, "customer", dry_test="OK", nitrogen_test="OK",
                                customer_code="CUSTOMER-CODE", has_customer_code=True,
                                can_package=True, reason="客户码校验通过")
    def update_box_codes(self, box_code, products): self.updates.append((box_code, list(products)))
    def release_from_box(self, code, expected_box):
        self.released.append((code, expected_box))
        return self.release_ok


class MemoryPrinter:
    def __init__(self): self.calls = 0
    def print_label(self): self.calls += 1


class FailingPrinter(MemoryPrinter):
    def print_label(self):
        self.calls += 1
        raise PrinterError("打印失败")


def make_workflow():
    repository, store, printer = MemoryRepository(), MemoryStore(), MemoryPrinter()
    flow = PackagingWorkflow(repository, store, printer)
    assert flow.startup_check().state is WorkflowState.READY
    return flow, repository, store, printer


def test_database_duplicate_is_rejected_without_acknowledgement():
    flow, _, _, _ = make_workflow()
    snapshot = flow.process_customer_scan("HISTORY")
    assert snapshot.state is WorkflowState.READY
    assert snapshot.box_count == 0
    assert snapshot.last_result.is_duplicate is True
    assert "OLD001" in snapshot.message
    assert flow.process_customer_scan("LASER-A").box_count == 1


def test_current_box_duplicate_is_rejected_and_keeps_slots():
    flow, _, _, _ = make_workflow()
    assert flow.process_customer_scan("LASER-A").box_count == 1
    duplicate = flow.process_customer_scan("LASER-A")
    assert duplicate.state is WorkflowState.BOX_IN_PROGRESS
    assert duplicate.products == ["LASER-A"]
    assert "第 1 格" in duplicate.message
    assert duplicate.last_result.duplicate_source == "current_box"
    assert flow.process_customer_scan("LASER-B").products == ["LASER-A", "LASER-B"]


def test_normal_rejection_does_not_require_duplicate_acknowledgement():
    flow, _, _, _ = make_workflow()
    flow.process_customer_scan("LASER-A")
    rejected = flow.process_customer_scan("INVALID")
    assert rejected.state is WorkflowState.BOX_IN_PROGRESS
    assert rejected.box_count == 1
    assert rejected.last_result.is_duplicate is False
    assert flow.process_customer_scan("LASER-B").box_count == 2


def test_rework_mode_releases_boxed_product_and_packs_again():
    flow, repository, _, _ = make_workflow()
    snapshot = flow.rework_scan("HISTORY")
    assert snapshot.state is WorkflowState.BOX_IN_PROGRESS
    assert snapshot.box_count == 1
    assert repository.released == [("HISTORY", "OLD001")]
    assert "OLD001" in snapshot.message


def test_rework_scan_keeps_product_unboxed_and_blocks_when_release_fails():
    flow, repository, _, _ = make_workflow()
    repository.release_ok = False
    snapshot = flow.rework_scan("HISTORY")
    assert snapshot.state is WorkflowState.READY
    assert snapshot.box_count == 0
    assert "回退失败" in snapshot.message
    assert snapshot.last_result.is_duplicate is True


def test_rework_mode_passes_unboxed_products_through_normally():
    flow, repository, _, _ = make_workflow()
    assert flow.rework_scan("LASER-A").box_count == 1
    assert repository.released == []


def test_reset_box_clears_session_and_allows_repacking():
    flow, _, _, _ = make_workflow()
    flow.process_customer_scan("LASER-A")
    flow.process_customer_scan("LASER-B")
    snapshot = flow.reset_box()
    assert snapshot.state is WorkflowState.READY
    assert snapshot.box_count == 0
    assert snapshot.products == []
    assert flow.session is None
    assert flow.process_customer_scan("LASER-C").box_count == 1


def test_fixed_twelve_products_finalize_exactly_once():
    flow, repository, store, printer = make_workflow()
    snapshots = [flow.process_customer_scan(f"LASER-{index:02d}") for index in range(PACKAGE_SIZE)]
    assert all(snapshot.box_completed is False for snapshot in snapshots[:-1])
    completed = snapshots[-1]
    assert completed.state is WorkflowState.READY
    assert completed.box_completed is True
    assert completed.box_count == PACKAGE_SIZE
    assert len(completed.products) == PACKAGE_SIZE
    assert len(repository.updates) == 1
    assert len(store.archived) == 1
    assert store.sequence_updates == 1
    assert printer.calls == 1
    assert store.print_files == ("BOX20260831001", [f"LASER-{index:02d}" for index in range(PACKAGE_SIZE)])


def test_finalization_failure_keeps_all_twelve_slots_and_cannot_be_acknowledged():
    repository, store, printer = MemoryRepository(), MemoryStore(), FailingPrinter()
    flow = PackagingWorkflow(repository, store, printer)
    flow.startup_check()
    for index in range(PACKAGE_SIZE - 1):
        flow.process_customer_scan(f"LASER-{index:02d}")
    with pytest.raises(WorkflowError):
        flow.process_customer_scan("LASER-11")
    assert flow.state is WorkflowState.ERROR_BLOCKED
    assert flow.session.count == PACKAGE_SIZE
    assert store.journal.phase == "DB_UPDATED"


def test_scan_saves_session_progress_and_reset_clears_it():
    store = MemoryStore()
    flow = PackagingWorkflow(MemoryRepository(), store, MemoryPrinter())
    flow.startup_check()
    flow.process_customer_scan("LASER-A")
    assert store.saved_session == ["LASER-A"]
    flow.reset_box()
    assert store.saved_session is None
    assert store.session_cleared == 1


def test_startup_clears_unfinished_box_and_pops_up():
    store = MemoryStore()
    unfinished = BoxSession("2026090925813", ["LASER-00", "LASER-01"])
    store.load_session = lambda: unfinished
    flow = PackagingWorkflow(MemoryRepository(), store, MemoryPrinter())
    snapshot = flow.startup_check()
    assert snapshot.state is WorkflowState.READY
    assert snapshot.popup and "2 件" in snapshot.popup and "重新扫码" in snapshot.popup
    assert "LASER-00" in snapshot.popup
    assert store.session_cleared == 1
    assert flow.session is None


def test_state_store_session_roundtrip(tmp_path):
    cfg = StationConfig(session_file=str(tmp_path / "session.json"), journal_file=str(tmp_path / "journal.json"))
    store = LegacyStateStore(cfg)
    assert store.load_session() is None
    store.save_session(BoxSession("2026090925813", ["LASER-00", "LASER-01"]))
    session = store.load_session()
    assert session.box_code == "2026090925813"
    assert session.products == ["LASER-00", "LASER-01"]
    store.clear_session()
    assert store.load_session() is None


def test_scan_gate_allows_only_one_scan_until_resolved():
    gate = ScanGate()
    gate.resolve(True)
    barrier = threading.Barrier(9)
    results = []
    def attempt_scan():
        barrier.wait()
        results.append(gate.begin())
    workers = [threading.Thread(target=attempt_scan) for _ in range(8)]
    for worker in workers: worker.start()
    barrier.wait()
    for worker in workers: worker.join(1)
    assert results.count(True) == 1
    assert results.count(False) == 7
    gate.resolve(False)
    assert gate.is_open is False
    assert gate.begin() is False
    gate.resolve(True)
    assert gate.begin() is True
