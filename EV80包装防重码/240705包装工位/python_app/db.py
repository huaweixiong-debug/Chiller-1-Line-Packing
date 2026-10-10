from __future__ import annotations

from contextlib import contextmanager
from typing import Sequence

import pymysql
from pymysql.cursors import DictCursor

from .models import InspectionResult, StationConfig


class DatabaseError(RuntimeError):
    pass


class InspectionRepository:
    """information 表访问层：按上线码查询干检/装箱状态，并回写箱码。"""

    def __init__(self, config: StationConfig, connector=None):
        self.config = config
        self.connector = connector or pymysql.connect

    @contextmanager
    def connection(self):
        try:
            conn = self.connector(
                host=self.config.db_host, port=self.config.db_port,
                user=self.config.db_user, password=self.config.db_password,
                database=self.config.db_name, connect_timeout=5,
                read_timeout=5, write_timeout=5, charset="utf8mb4",
                autocommit=False,
            )
            try:
                yield conn
            finally:
                conn.close()
        except Exception as exc:
            raise DatabaseError(f"数据库连接失败: {exc}") from exc

    @property
    def _columns(self) -> tuple[str, str, str, str, str, str]:
        cols = self.config.columns
        return (cols.code, cols.time, cols.dry_result, cols.helium_result, cols.box, cols.model)

    def query_rows(self, code: str) -> list[dict]:
        """按上线码取该产品的全部检测记录，最新的排在最前。"""
        code_col, time_col, dry_col, helium_col, box_col, model_col = self._columns
        sql = (f"SELECT `{code_col}`, `{time_col}`, `{dry_col}`, `{helium_col}`, `{box_col}`, `{model_col}` "
               f"FROM information WHERE `{code_col}`=%s ORDER BY `{time_col}` DESC LIMIT 500")
        try:
            with self.connection() as conn:
                with conn.cursor(DictCursor) as cur:
                    cur.execute(sql, (code,))
                    return list(cur.fetchall())
        except DatabaseError:
            raise
        except Exception as exc:
            raise DatabaseError(f"数据库查询失败: {exc}") from exc

    @staticmethod
    def _text(row: dict, column: str) -> str:
        value = row.get(column)
        return "" if value is None else str(value).strip()

    def _inspect(self, code: str, mode: str) -> InspectionResult:
        columns = self.config.columns
        checks = self.config.checks
        rows = self.query_rows(code)
        if not rows:
            return InspectionResult(code, mode, reason=f"未查询到上线码 {code}")
        latest = rows[0]
        box_codes = [self._text(row, columns.box) for row in rows]
        box_code = next((value for value in box_codes if value), "")
        dry = self._text(latest, columns.dry_result)
        helium = self._text(latest, columns.helium_result)
        result = InspectionResult(code, mode, rows=rows, model=self._text(latest, columns.model),
                                  dry_test=dry, helium_test=helium, box_code=box_code,
                                  already_boxed=bool(box_code),
                                  online_count=len(rows), is_duplicate=False)
        if result.already_boxed and checks.duplicate:
            result.is_duplicate = True
            result.duplicate_source = "database"
            result.reason = f"该产品已经包装，原箱码：{box_code}"
            return result
        problems = []
        if checks.dry_test and dry != "OK":
            problems.append("干检未完成（无记录）" if not dry else f"干检未通过（{dry}）")
        if checks.helium and helium != "OK":
            problems.append("氦检未完成（无记录）" if not helium else f"氦检未通过（{helium}）")
        result.can_package = not problems
        result.reason = "校验通过" if result.can_package else "不允许装箱：" + "，".join(problems)
        return result

    def inspect_serial(self, serial: str) -> InspectionResult:
        """仅查询路径：显示干检与装箱状态，不参与装箱。"""
        return self._inspect(serial, "serial")

    def inspect_customer(self, code: str) -> InspectionResult:
        """装箱路径：按上线码校验干检与重码后决定是否允许装箱。"""
        return self._inspect(code, "customer")

    def update_box_codes(self, box_code: str, laser_codes: Sequence[str]) -> None:
        if not laser_codes:
            raise DatabaseError("没有可回写的上线码")
        code_col, _, _, _, box_col, _ = self._columns
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    for code in laser_codes:
                        cur.execute(f"UPDATE information SET `{box_col}`=%s WHERE `{code_col}`=%s",
                                    (box_code, code))
                        if cur.rowcount < 1:
                            raise DatabaseError(f"上线码不存在或未更新: {code}")
                conn.commit()
        except DatabaseError:
            raise
        except Exception as exc:
            raise DatabaseError(f"箱码回写失败: {exc}") from exc

    def release_from_box(self, code: str, expected_box: str) -> bool:
        """回退模式：仅当产品仍处于扫码时所见的箱码内，才解除其箱码。"""
        code_col, _, _, _, box_col, _ = self._columns
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"UPDATE information SET `{box_col}`=%s WHERE `{code_col}`=%s AND `{box_col}`=%s",
                                ("", code, expected_box))
                    released = cur.rowcount >= 1
                conn.commit()
                return released
        except DatabaseError:
            raise
        except Exception as exc:
            raise DatabaseError(f"解除箱码失败: {exc}") from exc
