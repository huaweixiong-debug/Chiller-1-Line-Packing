#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EV80 防重码扫码工具

功能：
1. 读取旧式 .xls 总表，提取所有激光码作为主表集合
2. 接收扫码枪输入（键盘模拟模式）或可选摄像头解码
3. 首次且存在于主表的码 → 无重码；重复扫码 → 重码并报警
4. 不存在或格式异常的码单独提示
5. 导出扫码记录为新 CSV
"""

import csv
import math
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    import xlrd
except ImportError:
    xlrd = None

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
LASER_CODE_PATTERN = re.compile(r"^\d{26}$")
BOX_CODE_PATTERN = re.compile(r"^\d{13}$")
ALARM_FREQ = 800
ALARM_DURATION_MS = 500
ALARM_REPEAT = 3
UNKNOWN_BEEP_FREQ = 400
UNKNOWN_BEEP_DURATION_MS = 200
CAMERA_REARM_EMPTY_CYCLES = 3

# ---------------------------------------------------------------------------
# 核心逻辑（无 UI，可测试）
# ---------------------------------------------------------------------------

def cell_to_str(cell_value, cell_type: int = -1) -> str:
    """将单元格值安全转为字符串。
    - 数字不带 .0 后缀
    - 保留前导零（如果原值是字符串）
    - 空值返回空字符串
    - cell_type: xlrd XL_CELL_* 常量，帮助区分文本和数字
    """
    if cell_value is None:
        return ""
    # xlrd 文本类型：直接返回字符串
    if cell_type == 1:  # XL_CELL_TEXT
        return str(cell_value).strip()
    if isinstance(cell_value, float):
        if cell_value == int(cell_value):
            return str(int(cell_value))
        return str(cell_value)
    if isinstance(cell_value, int):
        return str(cell_value)
    return str(cell_value).strip()


def is_suspect_numeric_cell(cell_value, cell_type: int = -1) -> bool:
    """判断数值型单元格是否可能是被浮点精度污染的长码。

    Excel/xlrd 对 26 位纯数字若按数值保存，读取时可能已经丢失末位精度。
    这类单元格必须跳过并提示用户改成“文本”格式，不能静默加入主表。
    """
    if cell_type != 2 and not isinstance(cell_value, (int, float)):
        return False
    if isinstance(cell_value, bool):
        return False
    try:
        number = float(cell_value)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(number):
        return False
    return len(format(number, ".0f")) >= 20


def normalize_code(raw: str) -> str:
    """码值归一化：去除首尾空白、引号和扫码枪附带的空白字符。

    不去除前导零；前导零是条码内容的一部分。
    """
    if raw is None:
        return ""
    s = str(raw).strip().replace('"', "").replace("'", "")
    s = re.sub(r"\s+", "", s)
    return s


def is_valid_laser_code(code: str) -> bool:
    """检查归一化后的码是否为有效激光码（26位纯数字）。"""
    return bool(LASER_CODE_PATTERN.match(code))


def is_valid_box_code(code: str) -> bool:
    """检查归一化后的码是否为有效箱码（13位纯数字）。"""
    return bool(BOX_CODE_PATTERN.match(code))


def load_workbook_codes(filepath: str) -> Tuple[Set[str], Dict[str, int], List[str]]:
    """从 .xls 工作簿加载所有激光码。
    
    返回:
        master_set: 所有唯一激光码集合（主表）
        sheet_counts: 每个工作表中的码数量
        warnings: 警告信息列表
    """
    if xlrd is None:
        raise ImportError("需要安装 xlrd 库：pip install xlrd")

    warnings = []
    master_set: Set[str] = set()
    sheet_counts: Dict[str, int] = {}
    suspect_numeric_count = 0

    wb = xlrd.open_workbook(filepath)
    
    for sheet_name in wb.sheet_names():
        sheet = wb.sheet_by_name(sheet_name)
        count = 0
        
        for row_idx in range(sheet.nrows):
            for col_idx in range(sheet.ncols):
                cell = sheet.cell(row_idx, col_idx)
                if is_suspect_numeric_cell(cell.value, cell.ctype):
                    suspect_numeric_count += 1
                    continue
                raw = cell_to_str(cell.value, cell.ctype)
                code = normalize_code(raw)
                
                if is_valid_laser_code(code):
                    master_set.add(code)
                    count += 1

        sheet_counts[sheet_name] = count

    if suspect_numeric_count:
        warnings.append(
            f"发现 {suspect_numeric_count} 个疑似按数值保存的长码，已跳过；"
            "请在 Excel 中把激光码列设置为“文本”后再加载。"
        )

    return master_set, sheet_counts, warnings


def classify_scan(code: str, master_set: Set[str], scanned_set: Set[str]) -> Tuple[str, str]:
    """分类扫码结果。
    
    返回:
        (状态, 消息)
        状态: "unknown", "normal", "duplicate", "format_error"
    """
    normalized = normalize_code(code)
    
    if not is_valid_laser_code(normalized):
        return "format_error", f"格式异常：'{code}' 不是26位激光码"
    
    if normalized not in master_set:
        return "unknown", f"未知码：'{normalized}' 不存在于总表中"
    
    if normalized in scanned_set:
        return "duplicate", f"重码：'{normalized}' 本次批次已扫过"
    
    return "normal", f"无重码：'{normalized}' 首次扫码"


def beep_alarm(repeat: int = ALARM_REPEAT, freq: int = ALARM_FREQ, duration_ms: int = ALARM_DURATION_MS):
    """Windows 报警蜂鸣，失败时安全降级。"""
    try:
        import winsound
        for _ in range(repeat):
            winsound.Beep(freq, duration_ms)
            time.sleep(0.1)
    except (ImportError, RuntimeError):
        # 非 Windows 或 winsound 不可用，安全降级
        pass


def beep_unknown():
    """未知码/格式异常提示音。"""
    try:
        import winsound
        winsound.Beep(UNKNOWN_BEEP_FREQ, UNKNOWN_BEEP_DURATION_MS)
    except (ImportError, RuntimeError):
        pass


# ---------------------------------------------------------------------------
# 摄像头解码（可选）
# ---------------------------------------------------------------------------

class CameraDecoder:
    """后台摄像头线程，使用 zxing-cpp 解码。帧通过锁交给主线程，从不从后台线程调用 Tk API。"""
    
    def __init__(self, on_code_callback=None):
        self.on_code_callback = on_code_callback
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.camera = None
        self.last_code = ""
        self.lock = threading.Lock()          # 保护 last_code 和去抖状态
        self._camera_lock = threading.Lock()   # 保护 camera 对象
        self._frame_lock = threading.Lock()    # 保护 _latest_frame
        self._latest_frame = None
        self._pending_codes: queue.Queue[str] = queue.Queue()
        self._empty_decode_cycles = 0
    
    def start(self) -> bool:
        """启动摄像头线程。返回是否成功。"""
        if self.running:
            return True
        
        try:
            import cv2
        except ImportError:
            print("警告：需要安装 opencv-python：pip install opencv-python")
            return False
        
        try:
            import zxingcpp
        except ImportError:
            print("警告：需要安装 zxing-cpp：pip install zxing-cpp")
            return False
        
        with self._camera_lock:
            self.camera = cv2.VideoCapture(0)
            if not self.camera.isOpened():
                self.camera = None
                print("警告：无法打开摄像头")
                return False

        with self.lock:
            self.last_code = ""
            self._empty_decode_cycles = 0
        with self._frame_lock:
            self._latest_frame = None
        while True:
            try:
                self._pending_codes.get_nowait()
            except queue.Empty:
                break
        
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        return True
    
    def stop(self):
        """停止摄像头线程并释放资源。"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
        with self._camera_lock:
            if self.camera:
                self.camera.release()
                self.camera = None
        with self._frame_lock:
            self._latest_frame = None
    
    def _capture_loop(self):
        """后台捕获循环。帧交给 _latest_frame，解码结果通过回调通知。从不调用 Tk API。"""
        try:
            import cv2
            import zxingcpp
        except ImportError:
            return
        
        frame_count = 0
        while self.running:
            with self._camera_lock:
                cam = self.camera
            if cam is None or not cam.isOpened():
                break
            
            ret, frame = cam.read()
            if not ret:
                time.sleep(0.1)
                continue
            
            # 始终将最新帧交给主线程（覆盖上一帧）
            with self._frame_lock:
                self._latest_frame = frame
            
            frame_count += 1
            # 每5帧解码一次，降低CPU占用
            if frame_count % 5 != 0:
                time.sleep(0.05)
                continue
            
            try:
                results = zxingcpp.read_barcodes(frame)
                self._handle_decoded_codes([result.text for result in results])
            except Exception:
                self._handle_decoded_codes([])
            
            time.sleep(0.05)

    def _handle_decoded_codes(self, decoded_texts: List[str]) -> None:
        """去抖并排队解码结果；连续无码后允许同一物料再次触发。"""
        valid_code = ""
        for raw in decoded_texts:
            code = normalize_code(raw)
            if is_valid_laser_code(code):
                valid_code = code
                break

        with self.lock:
            if valid_code:
                self._empty_decode_cycles = 0
                if valid_code != self.last_code:
                    self.last_code = valid_code
                    # 只把结果放入队列；Tkinter 由主线程轮询，
                    # 这里不能直接调用任何 Tk API。
                    self._pending_codes.put(valid_code)
                return

            self._empty_decode_cycles += 1
            if self._empty_decode_cycles >= CAMERA_REARM_EMPTY_CYCLES:
                self.last_code = ""
                self._empty_decode_cycles = 0
    
    def get_latest_frame(self):
        """获取最新帧（线程安全，主线程调用）。"""
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            copy_method = getattr(self._latest_frame, "copy", None)
            return copy_method() if copy_method else self._latest_frame

    def get_pending_codes(self) -> List[str]:
        """取出后台线程发现的码；调用者应在 Tk 主线程执行。"""
        codes: List[str] = []
        while True:
            try:
                codes.append(self._pending_codes.get_nowait())
            except queue.Empty:
                return codes
    
    def is_available(self) -> bool:
        """检查摄像头是否可用。"""
        with self._camera_lock:
            return self.camera is not None and self.camera.isOpened()


# ---------------------------------------------------------------------------
# CSV 导出
# ---------------------------------------------------------------------------

def export_csv(records: List[Dict], filepath: str):
    """导出扫码记录为 CSV。"""
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["时间", "码值", "状态", "消息"])
        writer.writeheader()
        writer.writerows(records)


# ---------------------------------------------------------------------------
# Tkinter UI
# ---------------------------------------------------------------------------

class EV80CodeCheckerApp:
    """EV80 防重码扫码工具主界面。"""
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("EV80 防重码扫码工具")
        self.root.geometry("1000x750")
        self.root.minsize(900, 650)
        
        # 状态
        self.master_set: Set[str] = set()
        self.scanned_set: Set[str] = set()
        self.records: List[Dict] = []
        self.workbook_path: Optional[str] = None
        self.sheet_info: Dict[str, int] = {}
        self.normal_count = 0
        self.duplicate_count = 0
        self.unknown_count = 0
        
        # 摄像头
        self.camera_decoder: Optional[CameraDecoder] = None
        self.camera_active = False
        self._preview_after_id: Optional[str] = None
        
        self._build_ui()
        self._bind_shortcuts()
    
    def _build_ui(self):
        """构建界面。"""
        # 顶部：文件选择
        file_frame = ttk.LabelFrame(self.root, text="总表文件", padding=5)
        file_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.file_var = tk.StringVar()
        self.file_entry = ttk.Entry(file_frame, textvariable=self.file_var, state="readonly")
        self.file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(file_frame, text="选择文件", command=self._select_file).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(file_frame, text="重载", command=self._reload_file).pack(side=tk.LEFT)
        
        # 信息栏
        info_frame = ttk.Frame(self.root, padding=5)
        info_frame.pack(fill=tk.X, padx=5)
        
        self.status_label = ttk.Label(info_frame, text="未加载总表", foreground="gray")
        self.status_label.pack(side=tk.LEFT)
        
        self.count_label = ttk.Label(info_frame, text="")
        self.count_label.pack(side=tk.RIGHT)
        
        # 输入区
        input_frame = ttk.LabelFrame(self.root, text="扫码输入", padding=5)
        input_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.input_var = tk.StringVar()
        self.input_entry = ttk.Entry(input_frame, textvariable=self.input_var, font=("Consolas", 14))
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.input_entry.bind("<Return>", self._on_submit)
        self.input_entry.focus_set()
        
        ttk.Button(input_frame, text="提交", command=self._on_submit).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(input_frame, text="清空批次", command=self._clear_batch).pack(side=tk.LEFT)
        
        # 摄像头开关
        self.camera_btn = ttk.Button(input_frame, text="开启摄像头", command=self._toggle_camera)
        self.camera_btn.pack(side=tk.LEFT, padx=(5, 0))
        
        # 状态显示区
        main_frame = ttk.Frame(self.root, padding=5)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5)
        
        # 左侧：最近状态大字提示
        left_frame = ttk.LabelFrame(main_frame, text="最近扫码状态", padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        self.result_text = tk.Text(left_frame, height=4, font=("Microsoft YaHei", 16, "bold"),
                                   state="disabled", wrap=tk.WORD)
        self.result_text.pack(fill=tk.BOTH, expand=True)
        
        # 摄像头预览区（仅在摄像头开启时显示）
        self.camera_frame_container = ttk.LabelFrame(left_frame, text="摄像头预览", padding=5)
        self.camera_preview_label = ttk.Label(self.camera_frame_container, text="摄像头未开启")
        self.camera_preview_label.pack(fill=tk.BOTH, expand=True)
        
        # 右侧：各列表
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 无重码列表
        normal_frame = ttk.LabelFrame(right_frame, text="无重码", padding=5)
        normal_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        self.normal_text = scrolledtext.ScrolledText(normal_frame, height=6, state="disabled",
                                                     font=("Consolas", 10))
        self.normal_text.pack(fill=tk.BOTH, expand=True)
        self.normal_count_label = ttk.Label(normal_frame, text="0 个")
        self.normal_count_label.pack(anchor=tk.W)
        
        # 重码列表
        dup_frame = ttk.LabelFrame(right_frame, text="重码", padding=5)
        dup_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        self.dup_text = scrolledtext.ScrolledText(dup_frame, height=6, state="disabled",
                                                   font=("Consolas", 10), foreground="red")
        self.dup_text.pack(fill=tk.BOTH, expand=True)
        self.dup_count_label = ttk.Label(dup_frame, text="0 个")
        self.dup_count_label.pack(anchor=tk.W)
        
        # 未知/格式异常列表
        unknown_frame = ttk.LabelFrame(right_frame, text="未知/格式异常", padding=5)
        unknown_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        self.unknown_text = scrolledtext.ScrolledText(unknown_frame, height=6, state="disabled",
                                                       font=("Consolas", 10), foreground="orange")
        self.unknown_text.pack(fill=tk.BOTH, expand=True)
        self.unknown_count_label = ttk.Label(unknown_frame, text="0 个")
        self.unknown_count_label.pack(anchor=tk.W)
        
        # 底部：导出
        bottom_frame = ttk.Frame(self.root, padding=5)
        bottom_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        
        self.export_btn = ttk.Button(bottom_frame, text="导出 CSV", command=self._export_csv)
        self.export_btn.pack(side=tk.RIGHT)
        
        self.total_label = ttk.Label(bottom_frame, text="总计扫码：0")
        self.total_label.pack(side=tk.LEFT)
    
    def _bind_shortcuts(self):
        """绑定快捷键。"""
        self.root.bind("<Control-o>", lambda e: self._select_file())
        self.root.bind("<Control-r>", lambda e: self._reload_file())
        self.root.bind("<Control-e>", lambda e: self._export_csv())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _select_file(self):
        """选择总表文件。"""
        path = filedialog.askopenfilename(
            title="选择 EV80 总表",
            filetypes=[("Excel 文件", "*.xls"), ("所有文件", "*.*")]
        )
        if path:
            self._load_file(path)
    
    def _reload_file(self):
        """重载当前文件。"""
        if self.workbook_path:
            self._load_file(self.workbook_path)
        else:
            self._select_file()
    
    def _load_file(self, path: str):
        """加载工作簿。"""
        try:
            self.master_set, self.sheet_info, warnings = load_workbook_codes(path)
        except Exception as e:
            messagebox.showerror("加载错误", f"无法加载文件：{e}")
            return
        
        self.workbook_path = path
        self.file_var.set(path)
        
        # 更新状态
        info_parts = [f"主表码数：{len(self.master_set)}"]
        for sheet_name, count in self.sheet_info.items():
            if count > 0:
                info_parts.append(f"{sheet_name}: {count}")
        
        self.status_label.config(text=" | ".join(info_parts), foreground="green")
        self.count_label.config(text=f"主表去重码数：{len(self.master_set)}")
        self._update_count()
        self._set_result("总表加载成功", "green" if not warnings else "orange")
        
        if warnings:
            messagebox.showwarning("总表提示", "\n".join(warnings))
    
    def _on_submit(self, event=None):
        """提交扫码输入。"""
        code = self.input_var.get().strip()
        if not code:
            return
        
        self.input_var.set("")
        self._process_code(code)
    
    def _process_code(self, code: str):
        """处理扫码结果。"""
        if not self.master_set:
            self._set_result("请先加载总表", "orange")
            return
        
        status, message = classify_scan(code, self.master_set, self.scanned_set)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 记录
        self.records.append({
            "时间": now,
            "码值": normalize_code(code),
            "状态": status,
            "消息": message
        })
        
        # 更新显示
        if status == "normal":
            normalized = normalize_code(code)
            self.scanned_set.add(normalized)
            self._set_result(message, "green")
            self._append_normal(f"[{now}] {normalized}")
        
        elif status == "duplicate":
            normalized = normalize_code(code)
            self._set_result(message, "red")
            self._append_dup(f"[{now}] {normalized}")
            threading.Thread(target=beep_alarm, daemon=True).start()
        
        elif status == "unknown":
            self._set_result(message, "orange")
            self._append_unknown(f"[{now}] {code}")
            threading.Thread(target=beep_unknown, daemon=True).start()
        
        elif status == "format_error":
            self._set_result(message, "orange")
            self._append_unknown(f"[{now}] {message}")
            threading.Thread(target=beep_unknown, daemon=True).start()
        
        self._update_count()
    
    def _set_result(self, text: str, color: str):
        """设置最近状态大字。"""
        self.result_text.config(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert("1.0", text)
        self.result_text.config(state="disabled", foreground=color)
    
    def _append_normal(self, text: str):
        """追加到无重码列表。"""
        self.normal_text.config(state="normal")
        self.normal_text.insert(tk.END, text + "\n")
        self.normal_text.see(tk.END)
        self.normal_text.config(state="disabled")
        self.normal_count += 1
        self.normal_count_label.config(text=f"{self.normal_count} 个")
    
    def _append_dup(self, text: str):
        """追加到重码列表。"""
        self.dup_text.config(state="normal")
        self.dup_text.insert(tk.END, text + "\n")
        self.dup_text.see(tk.END)
        self.dup_text.config(state="disabled")
        self.duplicate_count += 1
        self.dup_count_label.config(text=f"{self.duplicate_count} 个")
    
    def _append_unknown(self, text: str):
        """追加到未知/格式异常列表。"""
        self.unknown_text.config(state="normal")
        self.unknown_text.insert(tk.END, text + "\n")
        self.unknown_text.see(tk.END)
        self.unknown_text.config(state="disabled")
        self.unknown_count += 1
        self.unknown_count_label.config(text=f"{self.unknown_count} 个")
    
    def _update_count(self):
        """更新总计数。"""
        total = len(self.records)
        normal = sum(1 for r in self.records if r["状态"] == "normal")
        dup = sum(1 for r in self.records if r["状态"] == "duplicate")
        unknown = sum(1 for r in self.records if r["状态"] in ("unknown", "format_error"))
        self.total_label.config(
            text=f"总计扫码：{total} | 无重码：{normal} | 重码：{dup} | 未知/异常：{unknown}"
        )
    
    def _clear_batch(self):
        """清空批次数据。"""
        if not self.records:
            return
        if not messagebox.askyesno("确认", "确定要清空当前批次数据吗？"):
            return
        
        self.scanned_set.clear()
        self.records.clear()
        self.normal_count = 0
        self.duplicate_count = 0
        self.unknown_count = 0
        
        for text_widget in (self.normal_text, self.dup_text, self.unknown_text):
            text_widget.config(state="normal")
            text_widget.delete("1.0", tk.END)
            text_widget.config(state="disabled")
        
        self.normal_count_label.config(text="0 个")
        self.dup_count_label.config(text="0 个")
        self.unknown_count_label.config(text="0 个")
        self._set_result("批次已清空", "gray")
        self._update_count()
    
    def _export_csv(self):
        """导出 CSV。"""
        if not self.records:
            messagebox.showwarning("导出", "没有扫码记录可导出")
            return
        
        default_name = f"EV80_扫码记录_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(
            title="导出 CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV 文件", "*.csv")]
        )
        if path:
            try:
                export_csv(self.records, path)
                messagebox.showinfo("导出成功", f"已导出 {len(self.records)} 条记录到：\n{path}")
            except Exception as e:
                messagebox.showerror("导出失败", f"导出失败：{e}")
    
    def _toggle_camera(self):
        """切换摄像头开关。"""
        if self.camera_active:
            self._stop_camera()
        else:
            self._start_camera()
    
    def _start_camera(self):
        """启动摄像头并开始预览轮询。"""
        if self.camera_decoder is None:
            self.camera_decoder = CameraDecoder()
        
        if self.camera_decoder.start():
            self.camera_active = True
            self.camera_btn.config(text="关闭摄像头")
            self._set_result("摄像头已开启，对准码即可扫描", "blue")
            # 显示预览区
            self.camera_frame_container.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
            self._schedule_preview()
        else:
            self._set_result("摄像头启动失败，请检查依赖和设备", "red")
    
    def _stop_camera(self):
        """停止摄像头并取消预览轮询。"""
        self._cancel_preview()
        if self.camera_decoder:
            self.camera_decoder.stop()
        self.camera_active = False
        self.camera_btn.config(text="开启摄像头")
        # 隐藏预览区
        self.camera_frame_container.pack_forget()
        self._set_result("摄像头已关闭", "gray")
    
    def _schedule_preview(self):
        """安排下一次预览更新（主线程安全）。"""
        if not self.camera_active:
            return
        # 摄像头线程只放入队列；扫码判定和 Tk 更新均在此主线程完成。
        if self.camera_decoder is not None:
            for code in self.camera_decoder.get_pending_codes():
                self._process_code(code)
        self._update_preview()
        self._preview_after_id = self.root.after(100, self._schedule_preview)
    
    def _cancel_preview(self):
        """取消预览轮询。"""
        if self._preview_after_id is not None:
            try:
                self.root.after_cancel(self._preview_after_id)
            except tk.TclError:
                pass
            self._preview_after_id = None
    
    def _update_preview(self):
        """从 CameraDecoder 获取最新帧并显示（始终在主线程运行）。"""
        if self.camera_decoder is None or not self.camera_active:
            return
        frame = self.camera_decoder.get_latest_frame()
        if frame is None:
            return
        try:
            import cv2
            # OpenCV BGR → RGB
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # 缩放到预览尺寸（最大 320x240）
            h, w = rgb.shape[:2]
            max_w, max_h = 320, 240
            scale = min(max_w / w, max_h / h, 1.0)
            if scale < 1.0:
                rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))
            # PhotoImage 需要 bytes；将 RGB 转为 PPM 数据
            # 构建 PPM P6 格式
            header = f"P6\n{rgb.shape[1]} {rgb.shape[0]}\n255\n".encode()
            img_data = header + rgb.tobytes()
            img = tk.PhotoImage(data=img_data, format="PPM")
            self.camera_preview_label.config(image=img, text="")
            self.camera_preview_label._img = img  # 防止 GC
        except Exception:
            pass
    
    def _on_camera_code(self, code: str):
        """处理摄像头码；仅由 Tk 主线程的队列轮询调用。"""
        self._process_code(code)
    
    def _on_close(self):
        """关闭窗口。"""
        self._cancel_preview()
        if self.camera_decoder:
            self.camera_decoder.stop()
        self.root.destroy()


# ---------------------------------------------------------------------------
# 命令行 smoke check
# ---------------------------------------------------------------------------

def smoke_check(filepath: str):
    """只读 smoke check：验证总表加载和示例码命中。"""
    print(f"=== EV80 防重码 Smoke Check ===")
    print(f"文件：{filepath}")
    
    master_set, sheet_info, warnings = load_workbook_codes(filepath)
    
    print(f"\n主表码数：{len(master_set)}")
    for name, count in sheet_info.items():
        print(f"  {name}: {count}")
    
    if warnings:
        print(f"\n警告：")
        for w in warnings:
            print(f"  {w}")
    
    # 示例码命中测试
    if master_set:
        sample = list(master_set)[0]
        print(f"\n示例码测试：")
        print(f"  码值：{sample}")
        
        # 模拟首次扫码
        scanned = set()
        status, msg = classify_scan(sample, master_set, scanned)
        print(f"  首次扫码：{status} - {msg}")
        
        # 模拟重复扫码
        scanned.add(sample)
        status, msg = classify_scan(sample, master_set, scanned)
        print(f"  重复扫码：{status} - {msg}")
        
        # 未知码测试
        status, msg = classify_scan("00000000000000000000000000", master_set, scanned)
        print(f"  未知码测试：{status} - {msg}")
        
        # 格式异常测试
        status, msg = classify_scan("abc123", master_set, scanned)
        print(f"  格式异常测试：{status} - {msg}")
    
    print("\n=== Smoke Check 完成 ===")


def find_default_workbook() -> Optional[Path]:
    """查找用户可替换的总表，兼容源码和 PyInstaller onedir。"""
    workbook_name = "ev80 06(1).xls"
    if getattr(sys, "frozen", False):
        # 优先使用 EXE 同级文件，便于现场直接替换总表；PyInstaller 6
        # 的 onedir 数据文件通常位于 sys._MEIPASS（即 _internal）下。
        base_dirs = [Path(sys.executable).resolve().parent]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            base_dirs.append(Path(meipass).resolve())
    else:
        base_dirs = [Path(__file__).resolve().parent]

    for base_dir in base_dirs:
        candidate = base_dir / workbook_name
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--smoke-check" and len(sys.argv) > 2:
            # --windowed 打包时 stdout/stderr 可能为 None；测试入口仍应
            # 能以退出码报告成功或失败，而不因 print 本身中断。
            if sys.stdout is None:
                sys.stdout = open(os.devnull, "w", encoding="utf-8")
            if sys.stderr is None:
                sys.stderr = open(os.devnull, "w", encoding="utf-8")
            smoke_check(sys.argv[2])
            return
    
    root = tk.Tk()
    app = EV80CodeCheckerApp(root)
    default_workbook = find_default_workbook()
    if default_workbook is not None:
        root.after(0, app._load_file, str(default_workbook))
    root.mainloop()


if __name__ == "__main__":
    main()
