from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from typing import Callable


class ScannerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScanFrame:
    code: str
    mode: str


class ScanGate:
    """Allow exactly one scan to enter the workflow at a time."""

    def __init__(self):
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._busy = False

    def wait(self, timeout: float) -> bool:
        return self._ready.wait(timeout)

    def begin(self) -> bool:
        with self._lock:
            if self._busy or not self._ready.is_set():
                return False
            self._busy = True
            self._ready.clear()
            return True

    def resolve(self, reopen: bool) -> None:
        with self._lock:
            self._busy = False
            if reopen:
                self._ready.set()
            else:
                self._ready.clear()

    def pause(self) -> None:
        with self._lock:
            self._ready.clear()

    @property
    def is_open(self) -> bool:
        return self._ready.is_set()


class ScannerService:
    def __init__(self, host: str, port: int, timeout: float = 5.0, serial_length: int = 22,
                 trigger_command: bytes = b"LON\r"):
        self.host, self.port, self.timeout, self.serial_length = host, port, timeout, serial_length
        self.trigger_command = trigger_command
        self.last_online = False
        self._stop = threading.Event()
        self._sock: socket.socket | None = None

    def read_once(self, expected_length: int | None = None) -> ScanFrame:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            self.last_online = False
            raise ScannerError(f"扫码器通信失败: {exc}") from exc
        self.last_online = True
        try:
            self._sock = sock
            with sock:
                if self.trigger_command:
                    sock.sendall(self.trigger_command)
                chunks = bytearray()
                got_data = False
                while not self._stop.is_set():
                    try:
                        data = sock.recv(256)
                    except socket.timeout:
                        if got_data:
                            break
                        raise ScannerError("扫码器未返回数据")
                    if not data:
                        break
                    chunks.extend(data)
                    if not got_data:
                        got_data = True
                        sock.settimeout(0.35)
                    if chunks[-1] in (0x0A, 0x0D):
                        break
                    if expected_length and len(chunks) >= expected_length:
                        break
                if not chunks:
                    raise ScannerError("扫码器未返回数据")
                code = bytes(chunks).decode("utf-8", errors="replace").strip("\x00\r\n \t")
                if not code:
                    raise ScannerError("扫码器未返回有效数据")
                return ScanFrame(code, "serial")
        except ScannerError:
            raise
        except (OSError, UnicodeError) as exc:
            raise ScannerError(f"扫码器通信失败: {exc}") from exc
        finally:
            self._sock = None

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
