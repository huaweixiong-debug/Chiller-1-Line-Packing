from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None

from .models import StationConfig


def _expand(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(value))


def load_config(path: str | os.PathLike[str] | None = None) -> StationConfig:
    cfg = StationConfig()
    config_path = Path(_expand(str(path or "%ProgramData%\\PackagingStation\\config.toml")))
    if not config_path.exists() or tomllib is None:
        return cfg
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    db = raw.get("database", {})
    scanner = raw.get("scanner", {})
    paths = raw.get("paths", {})
    app = raw.get("app", {})
    for name, value in db.items():
        if hasattr(cfg, f"db_{name}"):
            setattr(cfg, f"db_{name}", value)
    for name, value in scanner.items():
        if hasattr(cfg, f"scanner_{name}") or hasattr(cfg, name):
            setattr(cfg, f"scanner_{name}" if hasattr(cfg, f"scanner_{name}") else name, value)
    mapping = {
        "bartend_exe": "bartend_exe", "label_template": "label_template",
        "quantity_file": "quantity_file", "final_box_file": "final_box_file",
        "box_sequence_file": "box_sequence_file", "laser_archive_dir": "laser_archive_dir",
        "journal_file": "journal_file",
    }
    for source, target in mapping.items():
        if source in paths:
            setattr(cfg, target, _expand(str(paths[source])))
    if "station_name" in app:
        cfg.station_name = str(app["station_name"])
    if "pack_min_length" in app:
        cfg.pack_min_length = int(app["pack_min_length"])
    for name, value in raw.get("columns", {}).items():
        if hasattr(cfg.columns, name):
            setattr(cfg.columns, name, str(value))
    for name, value in raw.get("checks", {}).items():
        if hasattr(cfg.checks, name):
            setattr(cfg.checks, name, bool(value))

    chery = raw.get("chery_label", {})
    if chery:
        if "enabled" in chery:
            cfg.chery.enabled = bool(chery["enabled"])
        if "part_no" in chery:
            cfg.chery.part_no = str(chery["part_no"])
        if "batch" in chery:
            cfg.chery.batch = str(chery["batch"])
        if "layers" in chery:
            cfg.chery.layers = str(chery["layers"])
        if "qty_override" in chery:
            cfg.chery.qty_override = str(chery["qty_override"])
        if "qr_payload_file" in chery:
            cfg.chery.qr_payload_file = _expand(str(chery["qr_payload_file"]))
        if "counters_file" in chery:
            cfg.chery.counters_file = _expand(str(chery["counters_file"]))
    admin = raw.get("admin", {})
    if "username" in admin:
        cfg.admin_username = str(admin["username"])
    if "password" in admin:
        cfg.admin_password = str(admin["password"])
    if "db_password_env" in db:
        cfg.db_password = os.environ.get(str(db["db_password_env"]), cfg.db_password)
    return cfg
