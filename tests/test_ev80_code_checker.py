#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EV80 防重码扫码工具 - 单元测试"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# 确保能导入主模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ev80_code_checker import (
    BOX_CODE_PATTERN,
    CAMERA_REARM_EMPTY_CYCLES,
    CameraDecoder,
    LASER_CODE_PATTERN,
    cell_to_str,
    classify_scan,
    export_csv,
    is_suspect_numeric_cell,
    is_valid_box_code,
    is_valid_laser_code,
    load_workbook_codes,
    normalize_code,
)


class TestCellToStr(unittest.TestCase):
    """单元格值转字符串测试。"""

    def test_none_returns_empty(self):
        self.assertEqual(cell_to_str(None), "")

    def test_float_integer(self):
        self.assertEqual(cell_to_str(1.0), "1")
        self.assertEqual(cell_to_str(100.0), "100")

    def test_float_non_integer(self):
        self.assertEqual(cell_to_str(3.14), "3.14")

    def test_int(self):
        self.assertEqual(cell_to_str(42), "42")

    def test_string(self):
        self.assertEqual(cell_to_str("hello"), "hello")

    def test_string_with_spaces(self):
        self.assertEqual(cell_to_str("  abc  "), "abc")

    def test_string_with_leading_zeros(self):
        self.assertEqual(cell_to_str("001234"), "001234")

    def test_xlrd_text_cell_type(self):
        self.assertEqual(cell_to_str("001234", cell_type=1), "001234")

    def test_xlrd_text_cell_preserves_leading_zeros(self):
        self.assertEqual(cell_to_str("007", cell_type=1), "007")

    def test_xlrd_numeric_cell_type(self):
        self.assertEqual(cell_to_str(123.0, cell_type=2), "123")


class TestNumericCellSafety(unittest.TestCase):
    """防止浮点型长码精度丢失后被误加入主表。"""

    def test_long_numeric_cell_is_rejected(self):
        self.assertTrue(is_suspect_numeric_cell(1.006700111110926e25, cell_type=2))

    def test_short_numeric_cell_is_not_rejected(self):
        self.assertFalse(is_suspect_numeric_cell(123.0, cell_type=2))

    def test_text_long_code_is_not_numeric_candidate(self):
        self.assertFalse(is_suspect_numeric_cell("10067001111109260820000111", cell_type=1))


class TestCameraHandoff(unittest.TestCase):
    """摄像头帧和扫码结果不应在后台线程直接触碰 Tk。"""

    def test_latest_frame_round_trip(self):
        decoder = CameraDecoder()
        marker = object()
        decoder._latest_frame = marker
        self.assertIs(decoder.get_latest_frame(), marker)

    def test_pending_codes_are_drained(self):
        decoder = CameraDecoder()
        decoder._pending_codes.put("10067001111109260820000111")
        decoder._pending_codes.put("10067001111109260820000222")
        self.assertEqual(
            decoder.get_pending_codes(),
            ["10067001111109260820000111", "10067001111109260820000222"],
        )
        self.assertEqual(decoder.get_pending_codes(), [])

    def test_same_code_is_delivered_again_after_rearm(self):
        decoder = CameraDecoder()
        code = "10067001111109260820000111"

        decoder._handle_decoded_codes([code])
        self.assertEqual(decoder.get_pending_codes(), [code])

        for _ in range(CAMERA_REARM_EMPTY_CYCLES):
            decoder._handle_decoded_codes([])

        decoder._handle_decoded_codes([code])
        self.assertEqual(decoder.get_pending_codes(), [code])


class TestNormalizeCode(unittest.TestCase):
    """码值归一化测试。"""

    def test_basic(self):
        self.assertEqual(normalize_code("12345678901234567890123456"), "12345678901234567890123456")

    def test_strip_whitespace(self):
        self.assertEqual(normalize_code("  12345678901234567890123456  "), "12345678901234567890123456")

    def test_remove_quotes(self):
        self.assertEqual(normalize_code('"12345678901234567890123456"'), "12345678901234567890123456")
        self.assertEqual(normalize_code("'12345678901234567890123456'"), "12345678901234567890123456")

    def test_remove_spaces(self):
        self.assertEqual(normalize_code("123456 7890123456 7890123456"), "12345678901234567890123456")


class TestIsValidLaserCode(unittest.TestCase):
    """激光码格式验证测试。"""

    def test_valid(self):
        self.assertTrue(is_valid_laser_code("10067001111109260820000111"))

    def test_valid_all_zeros(self):
        self.assertTrue(is_valid_laser_code("00000000000000000000000000"))

    def test_too_short(self):
        self.assertFalse(is_valid_laser_code("12345"))

    def test_too_long(self):
        self.assertFalse(is_valid_laser_code("123456789012345678901234567"))

    def test_non_digit(self):
        self.assertFalse(is_valid_laser_code("1234567890123456789012345a"))

    def test_empty(self):
        self.assertFalse(is_valid_laser_code(""))


class TestIsValidBoxCode(unittest.TestCase):
    """箱码格式验证测试。"""

    def test_valid(self):
        self.assertTrue(is_valid_box_code("2026082225398"))

    def test_too_short(self):
        self.assertFalse(is_valid_box_code("12345"))


class TestClassifyScan(unittest.TestCase):
    """扫码分类测试。"""

    def setUp(self):
        self.master_set = {"10067001111109260820000111", "10067001111109260820000222"}
        self.scanned_set = set()

    def test_first_scan_normal(self):
        status, msg = classify_scan("10067001111109260820000111", self.master_set, self.scanned_set)
        self.assertEqual(status, "normal")
        self.assertIn("无重码", msg)

    def test_duplicate_scan(self):
        self.scanned_set.add("10067001111109260820000111")
        status, msg = classify_scan("10067001111109260820000111", self.master_set, self.scanned_set)
        self.assertEqual(status, "duplicate")
        self.assertIn("重码", msg)

    def test_unknown_code(self):
        status, msg = classify_scan("00000000000000000000000000", self.master_set, self.scanned_set)
        self.assertEqual(status, "unknown")
        self.assertIn("未知码", msg)

    def test_format_error(self):
        status, msg = classify_scan("abc123", self.master_set, self.scanned_set)
        self.assertEqual(status, "format_error")
        self.assertIn("格式异常", msg)

    def test_format_error_too_short(self):
        status, msg = classify_scan("12345", self.master_set, self.scanned_set)
        self.assertEqual(status, "format_error")

    def test_normal_then_duplicate(self):
        code = "10067001111109260820000111"
        s1, _ = classify_scan(code, self.master_set, self.scanned_set)
        self.assertEqual(s1, "normal")
        self.scanned_set.add(normalize_code(code))
        s2, _ = classify_scan(code, self.master_set, self.scanned_set)
        self.assertEqual(s2, "duplicate")

    def test_unknown_does_not_enter_normal(self):
        code = "00000000000000000000000000"
        status, _ = classify_scan(code, self.master_set, self.scanned_set)
        self.assertEqual(status, "unknown")
        # 未知码不应加入 scanned_set（由调用者控制）
        self.assertNotIn(code, self.scanned_set)

    def test_batch_independence(self):
        """跨表重复不影响批次判定 - 新批次清空 scanned_set 后，之前扫过的码应为 normal。"""
        code = "10067001111109260820000111"
        self.scanned_set.add(code)
        status, _ = classify_scan(code, self.master_set, self.scanned_set)
        self.assertEqual(status, "duplicate")
        # 模拟新批次
        self.scanned_set.clear()
        status, _ = classify_scan(code, self.master_set, self.scanned_set)
        self.assertEqual(status, "normal")


class TestExportCsv(unittest.TestCase):
    """CSV 导出测试。"""

    def test_export(self):
        import tempfile

        records = [
            {"时间": "2026-08-29 10:00:00", "码值": "12345678901234567890123456", "状态": "normal", "消息": "无重码"},
            {"时间": "2026-08-29 10:01:00", "码值": "12345678901234567890123456", "状态": "duplicate", "消息": "重码"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            filepath = f.name
        try:
            export_csv(records, filepath)
            with open(filepath, "r", encoding="utf-8-sig") as f:
                content = f.read()
            self.assertIn("时间", content)
            self.assertIn("码值", content)
            self.assertIn("12345678901234567890123456", content)
            self.assertIn("normal", content)
            self.assertIn("duplicate", content)
        finally:
            os.unlink(filepath)


class TestLoadWorkbookCodes(unittest.TestCase):
    """真实工作簿读取集成测试。"""

    @classmethod
    def setUpClass(cls):
        xls_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ev80 06(1).xls",
        )
        cls.xls_path = xls_path
        cls.xls_exists = os.path.exists(xls_path)

        if cls.xls_exists:
            try:
                cls.master_set, cls.sheet_info, cls.warnings = load_workbook_codes(xls_path)
                cls.load_ok = True
            except Exception:
                cls.load_ok = False
        else:
            cls.load_ok = False

    def test_file_loads(self):
        if not self.xls_exists:
            self.skipTest("真实 .xls 文件不存在")
        self.assertTrue(self.load_ok)

    def test_master_set_nonempty(self):
        if not self.xls_exists or not self.load_ok:
            self.skipTest("真实 .xls 文件未加载")
        self.assertGreater(len(self.master_set), 0)

    def test_sheet_counts(self):
        if not self.xls_exists or not self.load_ok:
            self.skipTest("真实 .xls 文件未加载")
        self.assertIsInstance(self.sheet_info, dict)
        total_count = sum(self.sheet_info.values())
        self.assertGreater(total_count, 0)

    def test_sample_code_hit(self):
        if not self.xls_exists or not self.load_ok:
            self.skipTest("真实 .xls 文件未加载")
        sample = list(self.master_set)[0]
        status, _ = classify_scan(sample, self.master_set, set())
        self.assertEqual(status, "normal")

    def test_sample_code_duplicate(self):
        if not self.xls_exists or not self.load_ok:
            self.skipTest("真实 .xls 文件未加载")
        sample = list(self.master_set)[0]
        scanned = {sample}
        status, _ = classify_scan(sample, self.master_set, scanned)
        self.assertEqual(status, "duplicate")

    def test_xls_not_modified(self):
        if not self.xls_exists:
            self.skipTest("真实 .xls 文件不存在")
        import hashlib

        mtime = os.path.getmtime(self.xls_path)
        with open(self.xls_path, "rb") as f:
            content = f.read()
        hash_after = hashlib.md5(content).hexdigest()
        # 再读一次确认不变
        with open(self.xls_path, "rb") as f:
            content2 = f.read()
        hash_after2 = hashlib.md5(content2).hexdigest()
        self.assertEqual(hash_after, hash_after2)


if __name__ == "__main__":
    unittest.main()
