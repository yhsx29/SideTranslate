from __future__ import annotations

import ctypes
import os
import struct
import subprocess
import threading
import time
from ctypes import wintypes
from typing import Callable


if os.name != "nt":
    raise RuntimeError("Side Translate currently supports Windows only")


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WH_MOUSE_LL = 14
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
CF_TEXT = 1
CF_UNICODETEXT = 13
CF_DIB = 8
CF_DIBV5 = 17
KEYEVENTF_KEYUP = 0x0002
SW_HIDE = 0


class HotkeyError(RuntimeError):
    pass


class MouseHookError(RuntimeError):
    pass


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


def set_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def parse_hotkey(value: str) -> tuple[int, int]:
    parts = [part.strip().upper() for part in value.split("+") if part.strip()]
    if len(parts) < 2:
        raise HotkeyError("快捷键至少需要一个修饰键和一个按键")
    modifiers = 0
    key = None
    for part in parts:
        if part in {"CTRL", "CONTROL"}:
            modifiers |= MOD_CONTROL
        elif part == "ALT":
            modifiers |= MOD_ALT
        elif part == "SHIFT":
            modifiers |= MOD_SHIFT
        elif part in {"WIN", "WINDOWS"}:
            modifiers |= MOD_WIN
        elif key is None:
            key = _virtual_key(part)
        else:
            raise HotkeyError("快捷键只能包含一个普通按键")
    if not modifiers or key is None:
        raise HotkeyError("快捷键格式无效，例如 Ctrl+Alt+T")
    return modifiers | MOD_NOREPEAT, key


def _virtual_key(name: str) -> int:
    aliases = {
        "SPACE": 0x20,
        "ENTER": 0x0D,
        "TAB": 0x09,
        "ESC": 0x1B,
        "UP": 0x26,
        "DOWN": 0x28,
        "LEFT": 0x25,
        "RIGHT": 0x27,
    }
    if name in aliases:
        return aliases[name]
    if len(name) == 1 and name.isalnum():
        return ord(name)
    if name.startswith("F") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return 0x6F + int(name[1:])
    raise HotkeyError(f"不支持按键 {name}")


class GlobalHotkeys:
    def __init__(self, dispatch: Callable[[str], None]) -> None:
        self.dispatch = dispatch
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._bindings: dict[int, tuple[str, int, int]] = {}
        self._ready = threading.Event()
        self._error: Exception | None = None

    def start(self, bindings: dict[str, str]) -> None:
        self.stop()
        parsed: dict[int, tuple[str, int, int]] = {}
        for index, (action, shortcut) in enumerate(bindings.items(), start=1):
            modifiers, key = parse_hotkey(shortcut)
            parsed[index] = (action, modifiers, key)
        self._bindings = parsed
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="global-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(2)
        if self._error:
            raise HotkeyError(str(self._error))

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
        self._thread = None
        self._thread_id = 0

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        registered: list[int] = []
        try:
            for identifier, (_, modifiers, key) in self._bindings.items():
                if not user32.RegisterHotKey(None, identifier, modifiers, key):
                    raise ctypes.WinError(ctypes.get_last_error())
                registered.append(identifier)
            self._ready.set()
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY:
                    action = self._bindings.get(int(message.wParam), ("", 0, 0))[0]
                    if action:
                        self.dispatch(action)
        except Exception as exc:
            self._error = exc
            self._ready.set()
        finally:
            for identifier in registered:
                user32.UnregisterHotKey(None, identifier)


def is_selection_drag(
    start: tuple[int, int],
    end: tuple[int, int],
    duration_seconds: float,
    minimum_distance: int = 8,
) -> bool:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    return duration_seconds >= 0.08 and delta_x * delta_x + delta_y * delta_y >= minimum_distance**2


class MouseSelectionWatcher:
    def __init__(self, dispatch: Callable[[], None], minimum_distance: int = 8) -> None:
        self.dispatch = dispatch
        self.minimum_distance = minimum_distance
        self._process_id = os.getpid()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook: wintypes.HHOOK | None = None
        self._hook_proc: HOOKPROC | None = None
        self._ready = threading.Event()
        self._error: Exception | None = None
        self._drag_start: tuple[int, int, float, int] | None = None

    def start(self) -> None:
        self.stop()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="mouse-selection-hook", daemon=True)
        self._thread.start()
        if not self._ready.wait(2):
            self.stop()
            raise MouseHookError("鼠标划词监听启动超时")
        if self._error:
            raise MouseHookError(str(self._error))

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
        self._thread = None
        self._thread_id = 0

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self._hook_proc = HOOKPROC(self._handle_mouse_event)
        try:
            module = kernel32.GetModuleHandleW(None)
            self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._hook_proc, module, 0)
            if not self._hook:
                raise ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                pass
        except Exception as exc:
            self._error = exc
            self._ready.set()
        finally:
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._hook_proc = None

    def _handle_mouse_event(self, code: int, message: int, event_pointer: int) -> int:
        if code >= 0:
            event = ctypes.cast(event_pointer, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if int(message) == WM_LBUTTONDOWN:
                self._drag_start = (
                    int(event.pt.x),
                    int(event.pt.y),
                    time.perf_counter(),
                    _foreground_process_id(),
                )
            elif int(message) == WM_LBUTTONUP and self._drag_start:
                start_x, start_y, started, process_id = self._drag_start
                self._drag_start = None
                if process_id != self._process_id and is_selection_drag(
                    (start_x, start_y),
                    (int(event.pt.x), int(event.pt.y)),
                    time.perf_counter() - started,
                    self.minimum_distance,
                ):
                    self.dispatch()
        return int(user32.CallNextHookEx(self._hook, code, message, event_pointer))


def _foreground_process_id() -> int:
    process_id = wintypes.DWORD()
    window = user32.GetForegroundWindow()
    if window:
        user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
    return int(process_id.value)


def clipboard_sequence_number() -> int:
    return int(user32.GetClipboardSequenceNumber())


def copy_selected_text(delay: float = 0.18) -> str:
    release_deadline = time.time() + 0.8
    while time.time() < release_deadline:
        control_down = user32.GetAsyncKeyState(0x11) & 0x8000
        alt_down = user32.GetAsyncKeyState(0x12) & 0x8000
        if not control_down and not alt_down:
            break
        time.sleep(0.02)
    before = clipboard_sequence_number()
    user32.keybd_event(0x11, 0, 0, 0)
    user32.keybd_event(ord("C"), 0, 0, 0)
    user32.keybd_event(ord("C"), 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)
    deadline = time.time() + max(delay, 0.8)
    changed = False
    while time.time() < deadline:
        if clipboard_sequence_number() != before:
            changed = True
            break
        time.sleep(0.03)
    if not changed:
        return ""
    return get_clipboard_text().strip()


def get_clipboard_text() -> str:
    if not _open_clipboard():
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> None:
    if not _open_clipboard():
        return
    try:
        user32.EmptyClipboard()
        payload = (text + "\0").encode("utf-16-le")
        handle = kernel32.GlobalAlloc(0x0002, len(payload))
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, payload, len(payload))
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(CF_UNICODETEXT, handle)
    finally:
        user32.CloseClipboard()


def launch_screen_clip() -> None:
    subprocess.Popen(
        ["explorer.exe", "ms-screenclip:"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def wait_for_clipboard_image(previous_sequence: int, timeout: float = 45.0) -> bytes:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if clipboard_sequence_number() != previous_sequence:
            image = get_clipboard_image()
            if image:
                return image
        time.sleep(0.12)
    raise TimeoutError("未收到截图，请重新触发后框选需要翻译的区域")


def get_clipboard_image() -> bytes:
    if not _open_clipboard():
        return b""
    try:
        png_format = user32.RegisterClipboardFormatW("PNG")
        for image_format in (png_format, CF_DIBV5, CF_DIB):
            handle = user32.GetClipboardData(image_format)
            if not handle:
                continue
            size = kernel32.GlobalSize(handle)
            pointer = kernel32.GlobalLock(handle)
            if not pointer or not size:
                continue
            try:
                data = ctypes.string_at(pointer, size)
                if image_format == png_format:
                    return data
                return _dib_to_bmp(data)
            finally:
                kernel32.GlobalUnlock(handle)
        return b""
    finally:
        user32.CloseClipboard()


def cursor_position() -> tuple[int, int]:
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return int(point.x), int(point.y)


def _open_clipboard(attempts: int = 12) -> bool:
    for _ in range(attempts):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def _dib_to_bmp(dib: bytes) -> bytes:
    if len(dib) < 40:
        return b""
    header_size = struct.unpack_from("<I", dib, 0)[0]
    bit_count = struct.unpack_from("<H", dib, 14)[0]
    compression = struct.unpack_from("<I", dib, 16)[0]
    clr_used = struct.unpack_from("<I", dib, 32)[0]
    palette_entries = clr_used or ((1 << bit_count) if bit_count <= 8 else 0)
    extra_masks = 12 if header_size == 40 and compression == 3 else 0
    pixel_offset = 14 + header_size + extra_masks + palette_entries * 4
    file_size = 14 + len(dib)
    file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, pixel_offset)
    return file_header + dib
