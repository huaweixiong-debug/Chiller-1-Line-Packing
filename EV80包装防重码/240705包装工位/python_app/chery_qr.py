"""奇瑞 KD 装箱标签二维码载荷（可选附加打印数据，不改动现有 BarTender 上线码文件）。"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

SUPPLIER_CODE = "8KN"

# 客户件号 | 零件名称 | 纸箱唯一码前缀 | 纸箱编号 | 包装收容数
PARTS: list[dict[str, Any]] = [
    {"part_no": "30100351AA", "name": "电池冷却器", "unique_prefix": "A0001",
     "box_no": "ZX680540230", "qty": 6},
    {"part_no": "301003472AA", "name": "HVAC总成智能组件", "unique_prefix": "B0001",
     "box_no": "ZX725680560", "qty": 1},
    {"part_no": "301003484AA", "name": "蒸发器到压缩机管路总成", "unique_prefix": "C0001",
     "box_no": "ZX680540230", "qty": 30},
    {"part_no": "301003483AA", "name": "冷凝器到蒸发器管路总成", "unique_prefix": "D0001",
     "box_no": "ZX1080680560", "qty": 10},
    {"part_no": "301002052AA", "name": "过冷式冷凝器总成", "unique_prefix": "E0001",
     "box_no": "ZX1080680560", "qty": 6},
    {"part_no": "301002053AA", "name": "冷凝器-压缩机管路总成", "unique_prefix": "F0001",
     "box_no": "ZX680540230", "qty": 30},
    {"part_no": "301003471AA", "name": "HVAC总成模式分配箱总成", "unique_prefix": "G0001",
     "box_no": "ZX1080680560", "qty": 1},
    {"part_no": "301003630AA", "name": "热管理控制模块", "unique_prefix": "H0001",
     "box_no": "ZX340270230", "qty": 20},
    {"part_no": "301005156AA", "name": "电池冷却器", "unique_prefix": "R0001",
     "box_no": "ZX680540230", "qty": 12},
    {"part_no": "FJ310004", "name": "单管夹", "unique_prefix": "J0001",
     "box_no": "ZX340270160", "qty": 120},
]


def get_part(part_no: str) -> dict[str, Any]:
    key = part_no.strip().upper()
    for part in PARTS:
        if part["part_no"].upper() == key:
            return part
    known = ", ".join(p["part_no"] for p in PARTS)
    raise ValueError(f"未知奇瑞零件号: {part_no!r}（可选: {known}）")


def build_payload(
    part_no: str,
    qty: str | int,
    batch: str,
    layers: str | int,
    prod_date: str,
    unique_code: str,
    box_no: str,
) -> str:
    """
    10#{零件号}$ 11#8KN$ 17#{包装数量}$ 18#{发运批次}$ 19#{码放层数}$
    20#{生产日期YYYYMMDD}$ 31#{纸箱唯一码}$ PK#{纸箱编号}$
    """
    return (
        f"10#{part_no.strip().upper()}$ "
        f"11#{SUPPLIER_CODE}$ "
        f"17#{str(qty).strip()}$ "
        f"18#{batch.strip().upper()}$ "
        f"19#{str(layers).strip()}$ "
        f"20#{prod_date.strip()}$ "
        f"31#{unique_code.strip().upper()}$ "
        f"PK#{box_no.strip().upper()}$"
    )


def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def parse_unique_code(code: str) -> tuple[str, int, int]:
    match = re.fullmatch(r"([A-Za-z]+)(\d+)", code.strip())
    if not match:
        raise ValueError(f"纸箱唯一码格式无效: {code!r}（期望如 A0001）")
    return match.group(1).upper(), int(match.group(2)), len(match.group(2))


def format_unique_code(letter: str, number: int, width: int) -> str:
    return f"{letter.upper()}{number:0{width}d}"


def load_counters(path: str | os.PathLike[str]) -> dict[str, int]:
    counters_path = Path(os.path.expandvars(str(path)))
    if not counters_path.exists():
        return {}
    try:
        data = json.loads(counters_path.read_text(encoding="utf-8"))
        return {str(key): int(value) for key, value in data.items()}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def save_counters(path: str | os.PathLike[str], counters: dict[str, int]) -> None:
    counters_path = Path(os.path.expandvars(str(path)))
    counters_path.parent.mkdir(parents=True, exist_ok=True)
    counters_path.write_text(
        json.dumps(counters, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def next_unique_code(start_code: str, counters: dict[str, int]) -> str:
    letter, start_num, width = parse_unique_code(start_code)
    last = counters.get(letter)
    next_num = start_num if last is None else max(last + 1, start_num)
    return format_unique_code(letter, next_num, width)


def commit_unique_code(code: str, counters: dict[str, int], path: str | os.PathLike[str]) -> None:
    letter, number, _ = parse_unique_code(code)
    counters[letter] = max(counters.get(letter, 0), number)
    save_counters(path, counters)
