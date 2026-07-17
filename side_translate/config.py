from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import asdict, dataclass, fields
from pathlib import Path


APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "SideTranslate"
CONFIG_PATH = APP_DIR / "config.json"


@dataclass
class AppConfig:
    app_id: str = ""
    secret_key: str = ""
    ocr_api_key: str = ""
    ocr_secret_key: str = ""
    source_language: str = "auto"
    target_language: str = "zh"
    text_hotkey: str = "Ctrl+Alt+T"
    screenshot_hotkey: str = "Ctrl+Alt+S"
    auto_selection_hotkey: str = "Ctrl+Alt+A"
    popup_position: str = "cursor"
    popup_x: int = 0
    popup_y: int = 0
    popup_width: int = 420
    popup_height: int = 420
    always_on_top: bool = True
    auto_selection_enabled: bool = True


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


crypt32 = ctypes.windll.crypt32
kernel32 = ctypes.windll.kernel32
crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    wintypes.LPCWSTR,
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
crypt32.CryptProtectData.restype = wintypes.BOOL
crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
crypt32.CryptUnprotectData.restype = wintypes.BOOL
kernel32.LocalFree.argtypes = [ctypes.c_void_p]
kernel32.LocalFree.restype = ctypes.c_void_p


def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    value = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return value, buffer


def protect(value: str) -> str:
    if not value or os.name != "nt":
        return value
    source, keep_alive = _blob(value.encode("utf-8"))
    output = DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(source), "SideTranslate", None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(output.pbData, output.cbData)
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(output.pbData)
        del keep_alive


def unprotect(value: str) -> str:
    if not value.startswith("dpapi:") or os.name != "nt":
        return value
    try:
        encrypted = base64.b64decode(value[6:])
        source, keep_alive = _blob(encrypted)
        output = DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
        ):
            return ""
        try:
            return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
        finally:
            kernel32.LocalFree(output.pbData)
            del keep_alive
    except (ValueError, OSError, UnicodeDecodeError):
        return ""


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        allowed = {field.name for field in fields(AppConfig)}
        values = {key: value for key, value in raw.items() if key in allowed}
        for key in ("app_id", "secret_key", "ocr_api_key", "ocr_secret_key"):
            values[key] = unprotect(str(values.get(key, "")))
        return AppConfig(**values)
    except (OSError, ValueError, TypeError):
        return AppConfig()


def save_config(config: AppConfig) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    values = asdict(config)
    for key in ("app_id", "secret_key", "ocr_api_key", "ocr_secret_key"):
        values[key] = protect(str(values[key]))
    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(CONFIG_PATH)
