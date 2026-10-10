from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Sequence

import pymysql

from .models import FieldMap, InspectionResult, StationConfig


class DatabaseError(RuntimeError):
    pass


class InspectionRepository:
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

    def _query(self, sql: str, args: Sequence[str]) -> list[tuple]:
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, args)
                    return list(cur.fetchall())
        except DatabaseError:
            raise
        except Exception as exc:
            raise DatabaseError(f"数据库查询失败: {exc}") from exc

    def query_serial(self, serial: str) -> list[tuple]:
        return self._query(
            "SELECT * FROM information WHERE 流水码编号=%s ORDER BY 干检日期 DESC LIMIT 5000", (serial,)
        )

    def query_customer(self, customer: str) -> list[tuple]:
        return self._query(
            "SELECT * FROM information WHERE 激光码信息=%s ORDER BY 烘干日期 DESC LIMIT 5000", (customer,)
        )

    @staticmethod
    def _value(row: tuple, index: int) -> str:
        return "" if index >= len(row) or row[index] is None else str(row[index]).strip()

    def inspect_serial(self, serial: str, fields: FieldMap | None = None) -> InspectionResult:
        fields = fields or self.config.field_map
        rows = self.query_serial(serial)
        if not rows:
            return InspectionResult(serial, "serial", reason="未查询到流水码", online_count=0)
        row = rows[0]
        dry = self._value(row, fields.dry_test)
        nitrogen = self._value(row, fields.nitrogen_test)
        station = self._value(row, fields.station)
        result = InspectionResult(serial, "serial", rows=rows, station=station,
                                  dry_test=dry, nitrogen_test=nitrogen,
                                  helium_test=nitrogen,
                                  package_gate=self._value(row, fields.package_gate), online_count=len(rows))
        result.can_package = dry == "OK" and nitrogen == "OK"
        result.reason = "流水码校验通过" if result.can_package else "干检或氮检未通过"
        return result

    def inspect_customer(self, customer: str, fields: FieldMap | None = None) -> InspectionResult:
        fields = fields or self.config.field_map
        rows = self.query_customer(customer)
        if not rows:
            return InspectionResult(customer, "customer", reason="未查询到客户码")
        row = rows[0]
        customer_code = self._value(row, fields.customer_code)
        box_code = self._value(row, fields.box_code)
        gate = self._value(row, fields.package_gate)
        result = InspectionResult(customer, "customer", rows=rows,
                                  station=self._value(row, fields.station),
                                  dry_test=self._value(row, fields.dry_test),
                                  nitrogen_test=self._value(row, fields.nitrogen_test),
                                  helium_test=self._value(row, fields.nitrogen_test),
                                  drying_status=self._value(row, fields.drying_date),
                                  customer_code=customer_code, box_code=box_code,
                                  package_gate=gate, customer_count=len(rows),
                                  has_customer_code=len(customer_code) > 10,
                                  already_boxed=bool(box_code))
        if result.already_boxed:
            result.is_duplicate = True
            result.duplicate_source = "database"
            result.reason = f"该产品已经包装，原箱码：{box_code}"
            return result
        problems = []
        if not result.drying_status:
            problems.append("无烘干记录")
        if result.dry_test != "OK":
            problems.append("干检未完成（无记录）" if not result.dry_test else f"干检未通过（{result.dry_test}）")
        if result.nitrogen_test != "OK":
            problems.append("氦检未完成（无记录）" if not result.nitrogen_test else f"氦检未通过（{result.nitrogen_test}）")
        if not result.has_customer_code:
            problems.append("客户码缺失")
        result.can_package = not problems
        result.reason = "客户码校验通过" if result.can_package else "不允许装箱：" + "，".join(problems)
        return result

    def update_box_codes(self, box_code: str, laser_codes: Sequence[str]) -> None:
        if not laser_codes:
            raise DatabaseError("没有可回写的激光码")
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    for laser in laser_codes:
                        cur.execute("UPDATE information SET 箱码=%s WHERE 激光码信息=%s", (box_code, laser))
                        if cur.rowcount < 1:
                            raise DatabaseError(f"激光码不存在或未更新: {laser}")
                conn.commit()
        except DatabaseError:
            raise
        except Exception as exc:
            raise DatabaseError(f"箱码回写失败: {exc}") from exc

    def release_from_box(self, laser_code: str, expected_box: str) -> bool:
        """回退模式：仅当产品仍处于扫码时所见的箱码内，才解除其箱码。"""
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE information SET 箱码=%s WHERE 激光码信息=%s AND 箱码=%s",
                                ("", laser_code, expected_box))
                    released = cur.rowcount >= 1
                conn.commit()
                return released
        except DatabaseError:
            raise
        except Exception as exc:
            raise DatabaseError(f"解除箱码失败: {exc}") from exc
