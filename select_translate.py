from __future__ import annotations

import argparse
import asyncio
import base64
import ctypes
import hashlib
import hmac
import http.client
import json
import logging
import os
import queue
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from collections import Counter
from collections.abc import Iterator
from tkinter import colorchooser, filedialog, messagebox, ttk

import edge_tts
import eng_to_ipa as ipa


APP_NAME = "划词翻译朗读"
VOICE = "en-US-AriaNeural"
COLOR_BG = "#120f19"
COLOR_SURFACE = "#1c1826"
COLOR_SURFACE_ALT = "#252030"
COLOR_FIELD = "#211b2d"
COLOR_BORDER = "#3a314a"
COLOR_HEADER = "#17121f"
COLOR_TEXT = "#f4f0f8"
COLOR_MUTED = "#aaa1b7"
COLOR_SUBTLE = "#7e758c"
COLOR_ACCENT = "#8b5cf6"
COLOR_ACCENT_HOVER = "#7445e7"
COLOR_ACCENT_SOFT = "#302547"
COLOR_ACCENT_TEXT = "#cdbdff"
COLOR_STAR = "#f0bd59"
COLOR_SUCCESS = "#55b98a"
COLOR_WARNING = "#d8a64e"
COLOR_ERROR = "#ef6a78"
COLOR_ON_ACCENT = "#ffffff"
DEFAULT_ACCENT = COLOR_ACCENT
HOTKEY_TRANSLATE = 1
HOTKEY_EXIT = 2
HOTKEY_SETTINGS = 3
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_Q = 0x51
VK_S = 0x53
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2
MONITOR_DEFAULTTONEAREST = 2
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
WRAP_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[.+_:/-][A-Za-z0-9]+)*/?|\s+|.", re.DOTALL)
SINGLE_WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
WORD_EXTRACT_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
OPENING_PUNCTUATION = "（([【《“‘"
CLOSING_PUNCTUATION = "，。！？；：、）)]】》”’,.!?;:"


def blend_hex(start: str, end: str, amount: float) -> str:
    start_rgb = tuple(int(start[index:index + 2], 16) for index in (1, 3, 5))
    end_rgb = tuple(int(end[index:index + 2], 16) for index in (1, 3, 5))
    mixed = tuple(round(left + (right - left) * amount) for left, right in zip(start_rgb, end_rgb))
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


def contrast_text(background: str) -> str:
    channels = [int(background[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#111318" if luminance > 0.48 else "#ffffff"


def set_theme_palette(color: str) -> None:
    global COLOR_BG, COLOR_SURFACE, COLOR_SURFACE_ALT, COLOR_FIELD, COLOR_BORDER, COLOR_HEADER
    global COLOR_TEXT, COLOR_MUTED, COLOR_SUBTLE
    global COLOR_ACCENT, COLOR_ACCENT_HOVER, COLOR_ACCENT_SOFT, COLOR_ACCENT_TEXT, COLOR_ON_ACCENT
    normalized = color.strip().lower()
    if not re.fullmatch(r"#[0-9a-f]{6}", normalized):
        normalized = DEFAULT_ACCENT
    COLOR_BG = blend_hex("#090a0e", normalized, 0.06)
    COLOR_HEADER = blend_hex("#0b0d12", normalized, 0.08)
    COLOR_SURFACE = blend_hex("#12141a", normalized, 0.11)
    COLOR_FIELD = blend_hex("#171a22", normalized, 0.14)
    COLOR_SURFACE_ALT = blend_hex("#1a1d26", normalized, 0.17)
    COLOR_BORDER = blend_hex("#323744", normalized, 0.22)
    COLOR_TEXT = blend_hex("#f4f6fb", normalized, 0.03)
    COLOR_MUTED = blend_hex("#a2a8b3", normalized, 0.08)
    COLOR_SUBTLE = blend_hex("#737b89", normalized, 0.10)
    COLOR_ACCENT = normalized
    COLOR_ACCENT_HOVER = blend_hex(normalized, "#000000", 0.18)
    COLOR_ACCENT_SOFT = blend_hex(COLOR_SURFACE, normalized, 0.24)
    COLOR_ACCENT_TEXT = blend_hex(normalized, COLOR_TEXT, 0.58)
    COLOR_ON_ACCENT = contrast_text(normalized)

FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
CONFIG_HOME = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "SelectTranslate"
BOOTSTRAP_FILE = CONFIG_HOME / "bootstrap.json"
DEFAULT_DATA_DIR = CONFIG_HOME / "data"


def _configured_data_dir() -> Path:
    try:
        data = json.loads(BOOTSTRAP_FILE.read_text(encoding="utf-8"))
        configured = str(data.get("data_directory", "")).strip()
        if configured:
            return Path(configured).expanduser().resolve()
    except (OSError, ValueError, TypeError):
        pass
    return DEFAULT_DATA_DIR


def _set_data_paths(path: Path) -> None:
    global DATA_DIR, CACHE_DIR, WORD_DB, SETTINGS_FILE, SECRETS_FILE
    DATA_DIR = path
    CACHE_DIR = DATA_DIR / "cache"
    WORD_DB = DATA_DIR / "word-history.db"
    SETTINGS_FILE = DATA_DIR / "settings.json"
    SECRETS_FILE = DATA_DIR / "secrets.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


CONFIG_HOME.mkdir(parents=True, exist_ok=True)
_set_data_paths(_configured_data_dir())
SELECTION_READER = RESOURCE_DIR / "SelectionReader.exe"
APP_ICON = (RESOURCE_DIR / "app-icon.ico") if FROZEN else (BASE_DIR / "assets" / "app-icon.ico")


def set_window_icon(window: tk.Misc) -> None:
    try:
        window.iconbitmap(default=str(APP_ICON))
    except (OSError, tk.TclError):
        pass


def _migrate_legacy_data() -> None:
    legacy = BASE_DIR / "data"
    if not FROZEN or not legacy.is_dir() or legacy.resolve() == DATA_DIR.resolve():
        return
    for name in ("word-history.db", "settings.json"):
        source = legacy / name
        destination = DATA_DIR / name
        if source.is_file() and not destination.exists():
            shutil.copy2(source, destination)
    legacy_cache = legacy / "cache"
    if legacy_cache.is_dir() and not any(CACHE_DIR.iterdir()):
        shutil.copytree(legacy_cache, CACHE_DIR, dirs_exist_ok=True)


try:
    _migrate_legacy_data()
except OSError:
    pass

ENGINE_LABELS = {
    "auto": "自动（腾讯优先，微软备用）",
    "tencent": "腾讯翻译",
    "microsoft": "Microsoft 翻译",
    "deepseek": "DeepSeek API",
    "qwen": "Qwen API（阿里云百炼）",
    "glm": "GLM API（智谱）",
}
LLM_PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "endpoint": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-flash",
    },
    "qwen": {
        "label": "Qwen",
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-plus",
    },
    "glm": {
        "label": "GLM",
        "endpoint": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-5.3-flash",
    },
}
logging.basicConfig(
    filename=DATA_DIR / "select-translate.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
crypt32 = ctypes.windll.crypt32
shcore = ctypes.windll.shcore


def enable_high_dpi() -> None:
    """Enable crisp rendering before Tk creates any Windows handles."""
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


user32.OpenClipboard.argtypes = (wintypes.HWND,)
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = (wintypes.UINT,)
user32.GetClipboardData.restype = wintypes.HANDLE
user32.EmptyClipboard.restype = wintypes.BOOL
user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
user32.SetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.GetMessageW.restype = ctypes.c_int
user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
user32.MonitorFromPoint.argtypes = (POINT, wintypes.DWORD)
user32.MonitorFromPoint.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MONITORINFO))
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = (
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
)
user32.SetWindowPos.restype = wintypes.BOOL
shcore.GetDpiForMonitor.argtypes = (
    wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT),
)
shcore.GetDpiForMonitor.restype = ctypes.c_long
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetAncestor.restype = wintypes.HWND
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetClassNameW.restype = ctypes.c_int
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = wintypes.SHORT


def monitor_work_area(x: int, y: int) -> tuple[int, int, int, int]:
    monitor = user32.MonitorFromPoint(POINT(x, y), MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        area = info.rcWork
        return area.left, area.top, area.right, area.bottom
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def monitor_dpi(x: int, y: int) -> int:
    monitor = user32.MonitorFromPoint(POINT(x, y), MONITOR_DEFAULTTONEAREST)
    horizontal = wintypes.UINT()
    vertical = wintypes.UINT()
    if monitor and shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(horizontal), ctypes.byref(vertical)) == 0:
        return horizontal.value
    return 96
kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
kernel32.LocalFree.restype = ctypes.c_void_p
crypt32.CryptProtectData.argtypes = (
    ctypes.POINTER(DATA_BLOB),
    wintypes.LPCWSTR,
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
)
crypt32.CryptProtectData.restype = wintypes.BOOL
crypt32.CryptUnprotectData.argtypes = (
    ctypes.POINTER(DATA_BLOB),
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
)
crypt32.CryptUnprotectData.restype = wintypes.BOOL


def _protect_secret(secret: str) -> str:
    if not secret:
        return ""
    raw = secret.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    protected = DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(source), APP_NAME, None, None, None, 1, ctypes.byref(protected)):
        raise ctypes.WinError()
    try:
        return base64.b64encode(ctypes.string_at(protected.pbData, protected.cbData)).decode("ascii")
    finally:
        kernel32.LocalFree(protected.pbData)


def _unprotect_secret(encoded: str) -> str:
    if not encoded:
        return ""
    raw = base64.b64decode(encoded)
    buffer = ctypes.create_string_buffer(raw)
    source = DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    plain = DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(plain)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(plain.pbData, plain.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(plain.pbData)


def load_api_secrets() -> dict[str, str]:
    secrets = {provider: "" for provider in LLM_PROVIDERS}
    try:
        encrypted = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
        for provider in secrets:
            secrets[provider] = _unprotect_secret(str(encrypted.get(provider, "")))
    except (OSError, ValueError, TypeError):
        pass
    except Exception:
        logging.exception("Unable to decrypt saved API keys")
    return secrets


def save_api_secrets(secrets: dict[str, str]) -> None:
    encrypted = {provider: _protect_secret(secrets.get(provider, "").strip()) for provider in LLM_PROVIDERS}
    SECRETS_FILE.write_text(json.dumps(encrypted, indent=2), encoding="utf-8")


def _open_clipboard() -> bool:
    for _ in range(30):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def get_clipboard_text() -> str | None:
    if not _open_clipboard():
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> None:
    data = (text + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        return
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        return
    ctypes.memmove(pointer, data, len(data))
    kernel32.GlobalUnlock(handle)
    if not _open_clipboard():
        return
    try:
        user32.EmptyClipboard()
        user32.SetClipboardData(CF_UNICODETEXT, handle)
    finally:
        user32.CloseClipboard()


def _key(vk: int, key_up: bool = False) -> INPUT:
    return INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP if key_up else 0, time=0, dwExtraInfo=0),
    )


def send_ctrl_c() -> None:
    releases = [VK_Q, 0x11, 0xA2, 0xA3, 0x12, 0xA4, 0xA5, 0x10, 0xA0, 0xA1, 0x5B, 0x5C]
    release_inputs = (INPUT * len(releases))(*[_key(vk, True) for vk in releases])
    released = user32.SendInput(len(release_inputs), release_inputs, ctypes.sizeof(INPUT))
    if released != len(release_inputs):
        raise ctypes.WinError()
    time.sleep(0.035)
    copy_events = [_key(0x11), _key(0x43), _key(0x43, True), _key(0x11, True)]
    copy_inputs = (INPUT * len(copy_events))(*copy_events)
    copied = user32.SendInput(len(copy_inputs), copy_inputs, ctypes.sizeof(INPUT))
    if copied != len(copy_inputs):
        raise ctypes.WinError()


def capture_selection(timeout: float = 1.5) -> str:
    original = get_clipboard_text()
    sequence = user32.GetClipboardSequenceNumber()
    release_deadline = time.monotonic() + 0.16
    while time.monotonic() < release_deadline:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (VK_Q, 0x11, 0x12)):
            break
        time.sleep(0.01)
    send_ctrl_c()
    deadline = time.monotonic() + timeout
    changed = False
    while time.monotonic() < deadline:
        if user32.GetClipboardSequenceNumber() != sequence:
            changed = True
            time.sleep(0.008)
            break
        time.sleep(0.01)
    if not changed:
        logging.warning("Clipboard did not change after Ctrl+C")
        return ""
    selected = (get_clipboard_text() or "").strip()
    if original is not None:
        time.sleep(0.008)
        set_clipboard_text(original)
    return selected


def get_window_class(window_handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(window_handle, buffer, len(buffer))
    return buffer.value


def capture_selection_uia(window_handle: int, timeout: float = 1.2) -> str:
    if not SELECTION_READER.exists():
        return ""
    result = subprocess.run(
        [str(SELECTION_READER), str(window_handle)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
        timeout=timeout,
    )
    return result.stdout.decode("utf-8-sig", errors="replace").strip()


TRANSLATOR_KEY = bytes(
    [
        0xA2, 0x29, 0x3A, 0x3D, 0xD0, 0xDD, 0x32, 0x73, 0x97, 0x7A, 0x64, 0xDB, 0xC2, 0xF3, 0x27, 0xF5,
        0xD7, 0xBF, 0x87, 0xD9, 0x45, 0x9D, 0xF0, 0x5A, 0x09, 0x66, 0xC6, 0x30, 0xC6, 0x6A, 0xAA, 0x84,
        0x9A, 0x41, 0xAA, 0x94, 0x3A, 0xA8, 0xD5, 0x1A, 0x6E, 0x4D, 0xAA, 0xC9, 0xA3, 0x70, 0x12, 0x35,
        0xC7, 0xEB, 0x12, 0xF6, 0xE8, 0x23, 0x07, 0x9E, 0x47, 0x10, 0x95, 0x91, 0x88, 0x55, 0xD8, 0x17,
    ]
)
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_tencent_lock = threading.Lock()
_tencent_connection: http.client.HTTPSConnection | None = None


def translate_tencent(text: str) -> str:
    global _tencent_connection
    body = json.dumps(
        {
            "header": {
                "fn": "auto_translation_block",
                "client_key": "browser-windows-SelectTranslate",
            },
            "type": "plain",
            "model_category": "normal",
            "source": {"lang": "auto", "text_block": text},
            "target": {"lang": "zh"},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Referer": "https://yi.qq.com/zh-CN/index",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    last_error: Exception | None = None
    with _tencent_lock:
        for _ in range(2):
            try:
                if _tencent_connection is None:
                    _tencent_connection = http.client.HTTPSConnection("transmart.qq.com", timeout=18)
                _tencent_connection.request("POST", "/api/imt", body=body, headers=headers)
                response = _tencent_connection.getresponse()
                raw = response.read()
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                data = json.loads(raw.decode("utf-8"))
                break
            except Exception as exc:
                last_error = exc
                if _tencent_connection is not None:
                    _tencent_connection.close()
                _tencent_connection = None
        else:
            raise last_error or RuntimeError("腾讯翻译连接失败")
    translated = data.get("auto_translation", "").strip()
    if not translated:
        raise RuntimeError("腾讯翻译没有返回结果")
    return translated


def translate_microsoft(text: str) -> str:
    request_path = "api.cognitive.microsofttranslator.com/translate?api-version=3.0&to=zh-Hans"
    now = datetime.now(timezone.utc)
    stamp = f"{WEEKDAYS[now.weekday()]}, {now.day:02d} {MONTHS[now.month - 1]} {now.year:04d} {now:%H:%M:%S}GMT"
    request_id = uuid.uuid4().hex
    escaped = urllib.parse.quote(request_path, safe="")
    payload = f"MSTranslatorAndroidApp{escaped}{stamp}{request_id}".lower().encode("utf-8")
    digest = hmac.new(TRANSLATOR_KEY, payload, hashlib.sha256).digest()
    signature = f"MSTranslatorAndroidApp::{base64.b64encode(digest).decode()}::{stamp}::{request_id}"
    body = json.dumps([{"Text": text}], ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"https://{request_path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "X-MT-Signature": signature,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=18) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data[0]["translations"][0]["text"]


def translate_llm(text: str, provider: str, api_key: str, model: str = "") -> str:
    config = LLM_PROVIDERS[provider]
    if not api_key.strip():
        raise RuntimeError(f"请先在设置中填写 {config['label']} API Key")
    payload = json.dumps(
        {
            "model": model.strip() or config["model"],
            "messages": [
                {
                    "role": "system",
                    "content": "你是专业翻译。将用户提供的内容准确、自然地翻译成简体中文，只输出译文，不解释。",
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        str(config["endpoint"]),
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "SelectTranslate/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"{config['label']} HTTP {exc.code}: {detail}") from exc
    try:
        translated = str(data["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"{config['label']} 返回格式异常") from exc
    if not translated:
        raise RuntimeError(f"{config['label']} 没有返回译文")
    return translated


def translate_to_chinese(
    text: str,
    engine: str = "auto",
    api_key: str = "",
    model: str = "",
) -> str:
    if engine in LLM_PROVIDERS:
        return translate_llm(text, engine, api_key, model)
    errors = []
    translators = {
        "auto": (("腾讯", translate_tencent), ("Microsoft", translate_microsoft)),
        "tencent": (("腾讯", translate_tencent),),
        "microsoft": (("Microsoft", translate_microsoft),),
    }.get(engine, (("腾讯", translate_tencent), ("Microsoft", translate_microsoft)))
    for name, translator in translators:
        try:
            return translator(text)
        except Exception as exc:
            logging.warning("%s translation failed: %s", name, exc)
            errors.append(f"{name}: {exc}")
    raise RuntimeError("；".join(errors))


async def synthesize(text: str, path: Path) -> None:
    await edge_tts.Communicate(text, VOICE).save(str(path))


def normalize_single_word(text: str) -> str:
    word = text.strip().strip(".,!?;:()[]{}\"“”‘’")
    if not SINGLE_WORD_RE.fullmatch(word):
        return ""
    return word.lower().replace("’", "'")


def phonetic_for_selection(text: str) -> str:
    word = normalize_single_word(text)
    if not word:
        return ""
    try:
        phonetic = ipa.convert(word.lower(), keep_punct=False).strip()
    except Exception:
        logging.exception("Phonetic lookup failed for %s", word)
        return ""
    if not phonetic or "*" in phonetic:
        return ""
    return "/" + phonetic.strip("/") + "/"


def player_command(path: Path) -> list[str]:
    uri = path.resolve().as_uri().replace("'", "''")
    script = f"""
Add-Type -AssemblyName PresentationCore
$p = New-Object System.Windows.Media.MediaPlayer
$p.Open([Uri]'{uri}')
$p.Play()
$w = [Diagnostics.Stopwatch]::StartNew()
while (-not $p.NaturalDuration.HasTimeSpan -and $w.Elapsed.TotalSeconds -lt 12) {{ Start-Sleep -Milliseconds 50 }}
if (-not $p.NaturalDuration.HasTimeSpan) {{ $p.Close(); exit 2 }}
$d = $p.NaturalDuration.TimeSpan
while ($p.Position -lt $d -and $w.Elapsed.TotalMinutes -lt 20) {{ Start-Sleep -Milliseconds 100 }}
$p.Close()
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-WindowStyle", "Hidden", "-EncodedCommand", encoded]


class WordStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS words (
                    word TEXT PRIMARY KEY COLLATE NOCASE,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    lookup_count INTEGER NOT NULL DEFAULT 0,
                    sentence_count INTEGER NOT NULL DEFAULT 0,
                    starred INTEGER NOT NULL DEFAULT 0,
                    translation TEXT NOT NULL DEFAULT '',
                    phonetic TEXT NOT NULL DEFAULT '',
                    test_count INTEGER NOT NULL DEFAULT 0,
                    correct_count INTEGER NOT NULL DEFAULT 0,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                )
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [token.lower().replace("’", "'") for token in WORD_EXTRACT_RE.findall(text)]

    def record_selection(self, text: str) -> str:
        single_word = normalize_single_word(text)
        counts = Counter([single_word]) if single_word else Counter(self._tokens(text))
        if not counts:
            return ""
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connect() as connection:
            for word, count in counts.items():
                lookup_increment = count if single_word else 0
                sentence_increment = 0 if single_word else count
                connection.execute(
                    """
                    INSERT INTO words (
                        word, total_count, lookup_count, sentence_count, first_seen, last_seen
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(word) DO UPDATE SET
                        total_count = total_count + excluded.total_count,
                        lookup_count = lookup_count + excluded.lookup_count,
                        sentence_count = sentence_count + excluded.sentence_count,
                        last_seen = excluded.last_seen
                    """,
                    (word, count, lookup_increment, sentence_increment, now, now),
                )
        return single_word

    def update_details(self, word: str, translation: str, phonetic: str) -> None:
        if not word:
            return
        with self._connect() as connection:
            connection.execute(
                "UPDATE words SET translation = ?, phonetic = ? WHERE word = ?",
                (translation, phonetic, word),
            )

    def is_starred(self, word: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT starred FROM words WHERE word = ?", (word,)).fetchone()
        return bool(row and row["starred"])

    def toggle_star(self, word: str) -> bool:
        if not word:
            return False
        starred = not self.is_starred(word)
        with self._connect() as connection:
            connection.execute("UPDATE words SET starred = ? WHERE word = ?", (int(starred), word))
        return starred

    def stats(self) -> tuple[int, int, int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS unique_words, COALESCE(SUM(total_count), 0) AS total, COALESCE(SUM(starred), 0) AS starred FROM words"
            ).fetchone()
        return int(row["unique_words"]), int(row["total"]), int(row["starred"])

    def top_words(self, limit: int = 12) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT word, total_count, starred FROM words ORDER BY total_count DESC, last_seen DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def history(self, search: str = "", starred_only: bool = False, limit: int = 500) -> list[sqlite3.Row]:
        clauses = []
        values: list[object] = []
        if search:
            clauses.append("word LIKE ?")
            values.append(f"%{search.lower()}%")
        if starred_only:
            clauses.append("starred = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        with self._connect() as connection:
            return connection.execute(
                f"""
                SELECT word, translation, phonetic, total_count, lookup_count,
                       sentence_count, starred, last_seen, test_count, correct_count
                FROM words {where}
                ORDER BY starred DESC, total_count DESC, last_seen DESC
                LIMIT ?
                """,
                values,
            ).fetchall()

    def quiz_candidates(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT word, translation
                FROM words
                WHERE translation <> ''
                ORDER BY starred DESC, total_count DESC, last_seen DESC
                LIMIT 300
                """
            ).fetchall()

    def record_test(self, word: str, correct: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE words SET test_count = test_count + 1, correct_count = correct_count + ? WHERE word = ?",
                (int(correct), word),
            )


def load_user_settings() -> dict[str, str]:
    defaults = {"translation_engine": "auto", "accent_color": DEFAULT_ACCENT}
    defaults.update({f"{provider}_model": str(config["model"]) for provider, config in LLM_PROVIDERS.items()})
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if data.get("translation_engine") in ENGINE_LABELS:
            defaults["translation_engine"] = data["translation_engine"]
        accent_color = str(data.get("accent_color", "")).strip().lower()
        if re.fullmatch(r"#[0-9a-f]{6}", accent_color):
            defaults["accent_color"] = accent_color
        for provider in LLM_PROVIDERS:
            model = str(data.get(f"{provider}_model", "")).strip()
            if model:
                defaults[f"{provider}_model"] = model
    except (OSError, ValueError, TypeError):
        pass
    return defaults


def save_user_settings(settings: dict[str, str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


class SlimProgress(tk.Canvas):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, height=3, bg=COLOR_SURFACE_ALT, highlightthickness=0, bd=0)
        self._value = 0.0
        self._indeterminate = False
        self._phase = 0.0
        self._job: str | None = None
        self.bind("<Configure>", lambda _event: self._draw())

    def set(self, value: float) -> None:
        self._value = max(0.0, min(100.0, value))
        self._draw()

    def start(self, interval: int = 16) -> None:
        self.stop()
        self._indeterminate = True
        self._animate(max(12, interval))

    def stop(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        self._indeterminate = False

    def _animate(self, interval: int) -> None:
        if not self._indeterminate:
            return
        self._phase = (self._phase + 0.035) % 1.0
        self._draw()
        self._job = self.after(interval, self._animate, interval)

    def _draw(self) -> None:
        self.delete("bar")
        width = max(1, self.winfo_width())
        if self._indeterminate:
            block = max(36, int(width * 0.28))
            x = int(self._phase * (width + block)) - block
            self.create_rectangle(x, 0, x + block, self.winfo_height(), fill=COLOR_ACCENT, outline="", tags="bar")
        elif self._value > 0:
            self.create_rectangle(0, 0, int(width * self._value / 100), self.winfo_height(), fill=COLOR_ACCENT, outline="", tags="bar")


class App:
    def __init__(self, background: bool) -> None:
        self.root = tk.Tk()
        set_window_icon(self.root)
        self.root.withdraw()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.store = WordStore(WORD_DB)
        self.user_settings = load_user_settings()
        set_theme_palette(self.user_settings["accent_color"])
        self.api_keys = load_api_secrets()
        self.translation_engine = self.user_settings["translation_engine"]
        self.source_text = ""
        self.translation = ""
        self.current_word = ""
        self.translation_cache: dict[str, str] = {}
        self.request_generation = 0
        self.translation_done = False
        self.audio_done = False
        self.translation_seconds = 0.0
        self.audio_seconds = 0.0
        self.audio_path: Path | None = None
        self.audio_error = ""
        self.play_when_ready = False
        self.player: subprocess.Popen | None = None
        self.speech_generation = 0
        self.hotkey_thread_id = 0
        self.anchor = (0, 0)
        self.popup_base_dpi = monitor_dpi(0, 0)
        self.popup_scale = 1.0
        self.light_dismiss_armed = False
        self._mouse_was_down = False
        self.card_source = ""
        self.card_translation = ""
        self.settings_window: tk.Toplevel | None = None
        self.chart_rows: list[sqlite3.Row] = []
        self.quiz_queue: list[sqlite3.Row] = []
        self.quiz_word = ""
        self.quiz_correct = 0
        self.quiz_total = 0
        self.quiz_answered = False
        self.quiz_player: subprocess.Popen | None = None
        self.window = self._build_window()
        threading.Thread(target=self._hotkey_loop, daemon=True).start()
        threading.Thread(target=self._warm_translation, daemon=True).start()
        self.root.after(50, self._poll)
        self.root.after(60, self._watch_outside_click)
        if not background:
            self.root.after(250, self.show_guide)

    def _build_window(self) -> tk.Toplevel:
        win = tk.Toplevel(self.root)
        set_window_icon(win)
        win.withdraw()
        win.title(APP_NAME)
        win.configure(bg=COLOR_BORDER)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.985)
        try:
            win.attributes("-toolwindow", True)
        except tk.TclError:
            pass
        win.overrideredirect(True)
        win.protocol("WM_DELETE_WINDOW", self.hide)
        win.resizable(False, False)
        win.bind("<Escape>", lambda _event: self.hide())
        win.bind("<FocusOut>", self._on_focus_out)
        card = tk.Frame(win, bg=COLOR_SURFACE, highlightthickness=1, highlightbackground=COLOR_BORDER)
        self.popup_card = card
        card.pack(fill="both", expand=True)
        self.progress = SlimProgress(card)
        self.progress.pack(fill="x")

        content = tk.Frame(card, bg=COLOR_SURFACE, padx=18, pady=14)
        self.popup_content = content
        content.pack(fill="both", expand=True)
        text_area = tk.Frame(content, bg=COLOR_SURFACE)
        text_area.pack(side="left", fill="both", expand=True)
        self.source_label = tk.Label(
            text_area,
            text="",
            bg=COLOR_SURFACE,
            fg=COLOR_MUTED,
            anchor="w",
            justify="left",
            font=("Segoe UI", 9),
        )
        self.source_label.pack(fill="x")
        self.translation_label = tk.Label(
            text_area,
            text="",
            bg=COLOR_SURFACE,
            fg=COLOR_TEXT,
            anchor="w",
            justify="left",
            font=("Microsoft YaHei UI", 14, "bold"),
            cursor="hand2",
        )
        self.translation_label.pack(fill="x", pady=(7, 7))
        self.translation_label.bind("<Button-1>", lambda _event: self.copy_translation())
        self.phonetic_label = tk.Label(
            text_area,
            text="",
            bg=COLOR_SURFACE,
            fg=COLOR_ACCENT_TEXT,
            anchor="w",
            justify="left",
            font=("Segoe UI", 11),
        )
        self.status_label = tk.Label(
            text_area,
            text="准备就绪",
            bg=COLOR_SURFACE,
            fg=COLOR_SUBTLE,
            anchor="w",
            justify="left",
            font=("Microsoft YaHei UI", 8),
        )
        self.status_label.pack(fill="x")

        action_area = tk.Frame(content, bg=COLOR_SURFACE)
        self.popup_action_area = action_area
        action_area.pack(side="right", padx=(14, 0), anchor="center")
        icon_row = tk.Frame(action_area, bg=COLOR_SURFACE)
        self.popup_icon_row = icon_row
        icon_row.pack(fill="x", pady=(0, 5))
        self.star_button = tk.Button(
            icon_row,
            text="☆",
            command=self.toggle_current_star,
            bg=COLOR_SURFACE,
            fg=COLOR_MUTED,
            activebackground=COLOR_SURFACE,
            activeforeground=COLOR_STAR,
            relief="flat",
            bd=0,
            padx=5,
            pady=1,
            cursor="hand2",
            font=("Segoe UI Symbol", 19),
        )
        self.settings_button = tk.Button(
            icon_row,
            text="⚙",
            command=self.open_settings,
            bg=COLOR_SURFACE,
            fg=COLOR_MUTED,
            activebackground=COLOR_SURFACE,
            activeforeground=COLOR_ACCENT_TEXT,
            relief="flat",
            bd=0,
            padx=5,
            pady=2,
            cursor="hand2",
            font=("Segoe UI Symbol", 15),
        )
        self.settings_button.pack(side="right")
        self.speaker = tk.Canvas(action_area, width=50, height=50, bg=COLOR_SURFACE, highlightthickness=0, cursor="hand2")
        self.speaker.pack()
        self.speaker_circle = self.speaker.create_oval(3, 3, 47, 47, fill=COLOR_ACCENT_SOFT, outline=COLOR_BORDER, width=1)
        self.speaker_body = self.speaker.create_polygon(
            13, 22, 19, 22, 26, 16, 26, 34, 19, 28, 13, 28,
            fill=COLOR_ACCENT_TEXT,
            outline="",
            tags=("speaker-icon", "speaker-play"),
        )
        self.speaker_wave_inner = self.speaker.create_arc(
            23, 18, 35, 32,
            start=-52,
            extent=104,
            style="arc",
            outline=COLOR_ACCENT_TEXT,
            width=2,
            tags=("speaker-icon", "speaker-play"),
        )
        self.speaker_wave_outer = self.speaker.create_arc(
            22, 14, 41, 36,
            start=-49,
            extent=98,
            style="arc",
            outline=COLOR_ACCENT_TEXT,
            width=2,
            tags=("speaker-icon", "speaker-play"),
        )
        self.speaker_wait_dots = tuple(
            self.speaker.create_oval(x, 23, x + 4, 27, fill=COLOR_MUTED, outline="", state="hidden", tags=("speaker-icon", "speaker-wait"))
            for x in (17, 23, 29)
        )
        self.speaker_stop = self.speaker.create_rectangle(
            19, 19, 31, 31,
            fill=COLOR_ERROR,
            outline="",
            state="hidden",
            tags=("speaker-icon", "speaker-stop"),
        )
        self.speaker.bind("<Button-1>", lambda _event: self.toggle_speech())
        self.speaker.bind("<Enter>", lambda _event: self._set_speaker_hover(True))
        self.speaker.bind("<Leave>", lambda _event: self._set_speaker_hover(False))
        return win

    def _set_popup_scale(self, scale: float) -> None:
        if abs(scale - self.popup_scale) < 0.01:
            return
        ratio = scale / self.popup_scale
        self.popup_scale = scale
        px = lambda value: max(1, round(value * scale))
        self.popup_card.configure(highlightthickness=px(1))
        self.progress.configure(height=px(3))
        self.popup_content.configure(padx=px(18), pady=px(14))
        self.translation_label.pack_configure(pady=(px(7), px(7)))
        if self.phonetic_label.winfo_manager():
            self.phonetic_label.pack_configure(pady=(0, px(5)))
        self.popup_action_area.pack_configure(padx=(px(14), 0))
        self.popup_icon_row.pack_configure(pady=(0, px(5)))
        self.phonetic_label.configure(font=("Segoe UI", px(11)))
        self.status_label.configure(font=("Microsoft YaHei UI", px(8)))
        self.star_button.configure(font=("Segoe UI Symbol", px(19)), padx=px(5), pady=px(1))
        self.settings_button.configure(font=("Segoe UI Symbol", px(15)), padx=px(5), pady=px(2))
        self.speaker.configure(width=px(50), height=px(50))
        self.speaker.scale("all", 0, 0, ratio, ratio)
        self.speaker.itemconfigure(self.speaker_circle, width=px(1))
        self.speaker.itemconfigure(self.speaker_wave_inner, width=px(2))
        self.speaker.itemconfigure(self.speaker_wave_outer, width=px(2))

    def _update_star_button(self) -> None:
        if not self.current_word:
            self.star_button.pack_forget()
            return
        starred = self.store.is_starred(self.current_word)
        self.star_button.configure(text="★" if starred else "☆", fg=COLOR_STAR if starred else COLOR_MUTED)
        if not self.star_button.winfo_manager():
            self.star_button.pack(side="left")

    def toggle_current_star(self) -> None:
        if not self.current_word:
            return
        self.store.toggle_star(self.current_word)
        self._update_star_button()
        self._refresh_dashboard()

    def open_settings(self) -> None:
        self.hide()
        if self.settings_window is None or not self.settings_window.winfo_exists():
            self._build_settings_window()
        self._refresh_dashboard()
        self.settings_window.deiconify()
        self.settings_window.lift()
        self.settings_window.focus_force()
        self.settings_window.after_idle(self._finish_opening_settings)

    def _finish_opening_settings(self) -> None:
        if self.settings_window is None or not self.settings_window.winfo_exists():
            return
        self.settings_window.update_idletasks()
        self._draw_frequency_chart()

    def _build_settings_window(self) -> None:
        win = tk.Toplevel(self.root)
        set_window_icon(win)
        self.settings_window = win
        win.withdraw()
        win.title(f"{APP_NAME} · 单词本")
        screen_width = win.winfo_screenwidth()
        screen_height = win.winfo_screenheight()
        width = min(1080, max(900, screen_width - 160))
        height = min(760, max(620, screen_height - 140))
        x = max(20, (screen_width - width) // 2)
        y = max(20, (screen_height - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
        win.minsize(860, 600)
        win.configure(bg=COLOR_BG)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)

        style = ttk.Style(win)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Wordbook.TNotebook", background=COLOR_BG, borderwidth=0)
        style.configure(
            "Wordbook.TNotebook.Tab",
            font=("Microsoft YaHei UI", 10),
            padding=(18, 10),
            background=COLOR_SURFACE_ALT,
            foreground=COLOR_MUTED,
        )
        style.map(
            "Wordbook.TNotebook.Tab",
            background=[("selected", COLOR_ACCENT_SOFT), ("active", COLOR_SURFACE_ALT)],
            foreground=[("selected", COLOR_TEXT), ("active", COLOR_TEXT)],
        )
        style.configure(
            "Wordbook.Treeview",
            rowheight=30,
            font=("Microsoft YaHei UI", 9),
            background=COLOR_SURFACE,
            fieldbackground=COLOR_SURFACE,
            foreground=COLOR_TEXT,
            borderwidth=0,
        )
        style.map("Wordbook.Treeview", background=[("selected", COLOR_ACCENT_SOFT)], foreground=[("selected", COLOR_TEXT)])
        style.configure("Wordbook.Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"), background=COLOR_SURFACE_ALT, foreground=COLOR_TEXT)
        style.configure("Purple.TCombobox", fieldbackground=COLOR_FIELD, background=COLOR_SURFACE_ALT, foreground=COLOR_TEXT, arrowcolor=COLOR_ACCENT_TEXT)
        style.map("Purple.TCombobox", fieldbackground=[("readonly", COLOR_FIELD)], foreground=[("readonly", COLOR_TEXT)], selectbackground=[("readonly", COLOR_FIELD)], selectforeground=[("readonly", COLOR_TEXT)])
        style.configure("Wordbook.Vertical.TScrollbar", troughcolor=COLOR_BG, background=COLOR_SURFACE_ALT, bordercolor=COLOR_BORDER, arrowcolor=COLOR_MUTED, darkcolor=COLOR_SURFACE_ALT, lightcolor=COLOR_SURFACE_ALT)

        header = tk.Frame(win, bg=COLOR_HEADER, height=86)
        header.pack(fill="x")
        header.pack_propagate(False)
        title_area = tk.Frame(header, bg=COLOR_HEADER)
        title_area.pack(fill="both", expand=True, padx=28, pady=17)
        tk.Label(
            title_area,
            text="我的单词本",
            bg=COLOR_HEADER,
            fg=COLOR_TEXT,
            font=("Microsoft YaHei UI", 18, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_area,
            text="本地记录 · 高频回顾 · 拼写练习",
            bg=COLOR_HEADER,
            fg=COLOR_ACCENT_TEXT,
            font=("Microsoft YaHei UI", 9),
            anchor="w",
        ).pack(anchor="w", pady=(3, 0))

        notebook = ttk.Notebook(win, style="Wordbook.TNotebook")
        notebook.pack(fill="both", expand=True, padx=20, pady=(12, 20))

        overview = tk.Frame(notebook, bg=COLOR_BG)
        history = tk.Frame(notebook, bg=COLOR_BG)
        quiz = tk.Frame(notebook, bg=COLOR_BG)
        settings = tk.Frame(notebook, bg=COLOR_BG)
        notebook.add(overview, text="概览")
        notebook.add(history, text="单词记录")
        notebook.add(quiz, text="拼写测试")
        notebook.add(settings, text="设置")

        settings_canvas = tk.Canvas(settings, bg=COLOR_BG, highlightthickness=0)
        settings_scrollbar = ttk.Scrollbar(settings, orient="vertical", command=settings_canvas.yview, style="Wordbook.Vertical.TScrollbar")
        settings_body = tk.Frame(settings_canvas, bg=COLOR_BG)
        settings_body_window = settings_canvas.create_window((0, 0), window=settings_body, anchor="nw")
        settings_canvas.configure(yscrollcommand=settings_scrollbar.set)
        settings_canvas.pack(side="left", fill="both", expand=True)
        settings_scrollbar.pack(side="right", fill="y")
        settings_body.bind(
            "<Configure>",
            lambda _event: settings_canvas.configure(scrollregion=settings_canvas.bbox("all")),
        )
        settings_canvas.bind(
            "<Configure>",
            lambda event: settings_canvas.itemconfigure(settings_body_window, width=event.width),
        )

        stats_row = tk.Frame(overview, bg=COLOR_BG)
        stats_row.pack(fill="x", pady=(12, 18))
        self.stat_unique = self._stat_card(stats_row, "收录词汇", "0", "种不同单词")
        self.stat_total = self._stat_card(stats_row, "累计出现", "0", "次扫描记录")
        self.stat_starred = self._stat_card(stats_row, "星标词汇", "0", "个重点单词")
        tk.Label(
            overview,
            text="高频词",
            bg=COLOR_BG,
            fg=COLOR_TEXT,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w", padx=4)
        tk.Label(
            overview,
            text="选中的句子也会自动拆分并计入词频",
            bg=COLOR_BG,
            fg=COLOR_MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=4, pady=(3, 9))
        self.frequency_canvas = tk.Canvas(
            overview,
            bg=COLOR_SURFACE,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            height=280,
        )
        self.frequency_canvas.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.frequency_canvas.bind("<Configure>", self._draw_frequency_chart)

        filters = tk.Frame(history, bg=COLOR_BG)
        filters.pack(fill="x", pady=(12, 10))
        self.history_search_var = tk.StringVar()
        search_entry = tk.Entry(
            filters,
            textvariable=self.history_search_var,
            relief="flat",
            bg=COLOR_FIELD,
            fg=COLOR_TEXT,
            insertbackground=COLOR_ACCENT_TEXT,
            font=("Microsoft YaHei UI", 10),
        )
        search_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 12))
        search_entry.insert(0, "")
        self.history_starred_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            filters,
            text="只看星标",
            variable=self.history_starred_var,
            command=self._refresh_history,
            bg=COLOR_BG,
            activebackground=COLOR_BG,
            fg=COLOR_MUTED,
            activeforeground=COLOR_TEXT,
            selectcolor=COLOR_FIELD,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right")
        self.history_search_var.trace_add("write", lambda *_args: self._refresh_history())

        table_frame = tk.Frame(history, bg=COLOR_SURFACE, highlightthickness=1, highlightbackground=COLOR_BORDER)
        table_frame.pack(fill="both", expand=True, pady=(0, 4))
        columns = ("word", "translation", "total", "lookup", "sentence", "star", "last")
        self.history_tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            style="Wordbook.Treeview",
        )
        headings = {
            "word": "单词",
            "translation": "中文",
            "total": "总频次",
            "lookup": "单独查询",
            "sentence": "句中出现",
            "star": "星标",
            "last": "最近记录",
        }
        widths = {"word": 145, "translation": 235, "total": 68, "lookup": 78, "sentence": 78, "star": 50, "last": 145}
        for column in columns:
            self.history_tree.heading(column, text=headings[column])
            self.history_tree.column(column, width=widths[column], minwidth=45, anchor="center" if column not in ("word", "translation") else "w")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.history_tree.yview, style="Wordbook.Vertical.TScrollbar")
        self.history_tree.configure(yscrollcommand=scrollbar.set)
        self.history_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.history_tree.bind("<Double-1>", self._toggle_history_star)

        quiz_card = tk.Frame(quiz, bg=COLOR_SURFACE, highlightthickness=1, highlightbackground=COLOR_BORDER)
        quiz_card.pack(fill="both", expand=True, padx=50, pady=28)
        tk.Label(
            quiz_card,
            text="听音 · 看中文 · 拼写英文",
            bg=COLOR_SURFACE,
            fg=COLOR_MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(pady=(32, 8))
        self.quiz_chinese_label = tk.Label(
            quiz_card,
            text="暂无可测试单词",
            bg=COLOR_SURFACE,
            fg=COLOR_TEXT,
            font=("Microsoft YaHei UI", 22, "bold"),
            wraplength=520,
            justify="center",
        )
        self.quiz_chinese_label.pack(pady=(0, 10))
        self.quiz_audio_button = tk.Button(
            quiz_card,
            text="🔊  播放读音",
            command=self._play_quiz_audio,
            relief="flat",
            bg=COLOR_ACCENT_SOFT,
            fg=COLOR_ACCENT_TEXT,
            activebackground=COLOR_BORDER,
            activeforeground=COLOR_TEXT,
            font=("Microsoft YaHei UI", 10),
            padx=15,
            pady=7,
            cursor="hand2",
        )
        self.quiz_audio_button.pack(pady=(0, 18))
        self.quiz_entry = tk.Entry(
            quiz_card,
            justify="center",
            relief="solid",
            bd=1,
            font=("Segoe UI", 17),
            bg=COLOR_FIELD,
            fg=COLOR_TEXT,
            insertbackground=COLOR_ACCENT_TEXT,
            highlightbackground=COLOR_BORDER,
        )
        self.quiz_entry.pack(fill="x", padx=95, ipady=9)
        self.quiz_entry.bind("<Return>", lambda _event: self._submit_quiz())
        quiz_actions = tk.Frame(quiz_card, bg=COLOR_SURFACE)
        quiz_actions.pack(pady=14)
        tk.Button(
            quiz_actions,
            text="检查拼写",
            command=self._submit_quiz,
            relief="flat",
            bg=COLOR_ACCENT,
            fg=COLOR_ON_ACCENT,
            activebackground=COLOR_ACCENT_HOVER,
            activeforeground=COLOR_ON_ACCENT,
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=18,
            pady=8,
            cursor="hand2",
        ).pack(side="left", padx=5)
        tk.Button(
            quiz_actions,
            text="下一个",
            command=self._next_quiz_word,
            relief="flat",
            bg=COLOR_SURFACE_ALT,
            fg=COLOR_MUTED,
            activebackground=COLOR_BORDER,
            activeforeground=COLOR_TEXT,
            font=("Microsoft YaHei UI", 10),
            padx=18,
            pady=8,
            cursor="hand2",
        ).pack(side="left", padx=5)
        self.quiz_feedback_label = tk.Label(
            quiz_card,
            text="",
            bg=COLOR_SURFACE,
            fg=COLOR_MUTED,
            font=("Microsoft YaHei UI", 10),
        )
        self.quiz_feedback_label.pack()
        self.quiz_score_label = tk.Label(
            quiz_card,
            text="本轮 0 / 0",
            bg=COLOR_SURFACE,
            fg=COLOR_SUBTLE,
            font=("Microsoft YaHei UI", 8),
        )
        self.quiz_score_label.pack(pady=(8, 20))

        theme_card = tk.Frame(settings_body, bg=COLOR_SURFACE, highlightthickness=1, highlightbackground=COLOR_BORDER)
        theme_card.pack(fill="x", pady=(18, 10), padx=4)
        tk.Label(theme_card, text="界面颜色", bg=COLOR_SURFACE, fg=COLOR_TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=24, pady=(18, 3))
        tk.Label(theme_card, text="选择主题色；背景、卡片、边框、选中态和按钮会自动生成同一套色系。", bg=COLOR_SURFACE, fg=COLOR_MUTED, font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=24, pady=(0, 10))
        theme_row = tk.Frame(theme_card, bg=COLOR_SURFACE)
        theme_row.pack(fill="x", padx=24, pady=(0, 18))
        self.accent_color_var = tk.StringVar(value=self.user_settings["accent_color"])
        self.accent_swatch = tk.Canvas(theme_row, width=42, height=30, bg=COLOR_ACCENT, highlightthickness=1, highlightbackground=COLOR_BORDER)
        self.accent_swatch.pack(side="left")
        self.accent_hex_label = tk.Label(theme_row, text=COLOR_ACCENT.upper(), bg=COLOR_SURFACE, fg=COLOR_ACCENT_TEXT, font=("Consolas", 10, "bold"), width=10)
        self.accent_hex_label.pack(side="left", padx=(10, 8))
        tk.Button(theme_row, text="选择颜色", command=self._choose_accent_color, relief="flat", bg=COLOR_ACCENT, fg=COLOR_ON_ACCENT, activebackground=COLOR_ACCENT_HOVER, activeforeground=COLOR_ON_ACCENT, font=("Microsoft YaHei UI", 9, "bold"), padx=14, pady=7, cursor="hand2").pack(side="left")
        tk.Button(theme_row, text="恢复默认紫色", command=self._reset_accent_color, relief="flat", bg=COLOR_SURFACE_ALT, fg=COLOR_MUTED, activebackground=COLOR_BORDER, activeforeground=COLOR_TEXT, font=("Microsoft YaHei UI", 9), padx=12, pady=7, cursor="hand2").pack(side="left", padx=(8, 0))

        settings_card = tk.Frame(settings_body, bg=COLOR_SURFACE, highlightthickness=1, highlightbackground=COLOR_BORDER)
        settings_card.pack(fill="x", pady=10, padx=4)
        tk.Label(
            settings_card,
            text="翻译服务",
            bg=COLOR_SURFACE,
            fg=COLOR_TEXT,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w", padx=24, pady=(22, 4))
        tk.Label(
            settings_card,
            text="自动模式会优先使用腾讯翻译，失败时切换到 Microsoft。",
            bg=COLOR_SURFACE,
            fg=COLOR_MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=24, pady=(0, 10))
        self.engine_label_var = tk.StringVar(value=ENGINE_LABELS[self.translation_engine])
        engine_box = ttk.Combobox(
            settings_card,
            textvariable=self.engine_label_var,
            values=list(ENGINE_LABELS.values()),
            state="readonly",
            font=("Microsoft YaHei UI", 10),
            style="Purple.TCombobox",
        )
        engine_box.pack(fill="x", padx=24, ipady=5)
        tk.Frame(settings_card, bg=COLOR_SURFACE, height=18).pack()

        api_card = tk.Frame(settings_body, bg=COLOR_SURFACE, highlightthickness=1, highlightbackground=COLOR_BORDER)
        api_card.pack(fill="x", pady=10, padx=4)
        tk.Label(api_card, text="模型 API（可选）", bg=COLOR_SURFACE, fg=COLOR_TEXT, font=("Microsoft YaHei UI", 12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=24, pady=(18, 3))
        tk.Label(api_card, text="API Key 使用 Windows DPAPI 加密，仅当前 Windows 用户可解密。", bg=COLOR_SURFACE, fg=COLOR_MUTED, font=("Microsoft YaHei UI", 8)).grid(row=1, column=0, columnspan=3, sticky="w", padx=24, pady=(0, 10))
        tk.Label(api_card, text="服务", bg=COLOR_SURFACE, fg=COLOR_MUTED, font=("Microsoft YaHei UI", 8, "bold")).grid(row=2, column=0, sticky="w", padx=(24, 8))
        tk.Label(api_card, text="模型", bg=COLOR_SURFACE, fg=COLOR_MUTED, font=("Microsoft YaHei UI", 8, "bold")).grid(row=2, column=1, sticky="w", padx=8)
        tk.Label(api_card, text="API Key", bg=COLOR_SURFACE, fg=COLOR_MUTED, font=("Microsoft YaHei UI", 8, "bold")).grid(row=2, column=2, sticky="w", padx=(8, 24))
        api_card.grid_columnconfigure(1, weight=1)
        api_card.grid_columnconfigure(2, weight=2)
        self.api_key_vars: dict[str, tk.StringVar] = {}
        self.api_model_vars: dict[str, tk.StringVar] = {}
        for row_number, (provider, config) in enumerate(LLM_PROVIDERS.items(), start=3):
            tk.Label(api_card, text=str(config["label"]), bg=COLOR_SURFACE, fg=COLOR_TEXT, font=("Microsoft YaHei UI", 9, "bold"), width=10, anchor="w").grid(row=row_number, column=0, sticky="w", padx=(24, 8), pady=5)
            model_var = tk.StringVar(value=self.user_settings[f"{provider}_model"])
            key_var = tk.StringVar(value=self.api_keys.get(provider, ""))
            self.api_model_vars[provider] = model_var
            self.api_key_vars[provider] = key_var
            tk.Entry(api_card, textvariable=model_var, relief="solid", bd=1, font=("Segoe UI", 9), bg=COLOR_FIELD, fg=COLOR_TEXT, insertbackground=COLOR_ACCENT_TEXT, highlightbackground=COLOR_BORDER).grid(row=row_number, column=1, sticky="ew", padx=8, pady=5, ipady=5)
            tk.Entry(api_card, textvariable=key_var, show="●", relief="solid", bd=1, font=("Segoe UI", 9), bg=COLOR_FIELD, fg=COLOR_TEXT, insertbackground=COLOR_ACCENT_TEXT, highlightbackground=COLOR_BORDER).grid(row=row_number, column=2, sticky="ew", padx=(8, 24), pady=5, ipady=5)
        tk.Frame(api_card, bg=COLOR_SURFACE, height=12).grid(row=6, column=0, columnspan=3)

        storage_card = tk.Frame(settings_body, bg=COLOR_SURFACE, highlightthickness=1, highlightbackground=COLOR_BORDER)
        storage_card.pack(fill="x", pady=10, padx=4)
        tk.Label(storage_card, text="本地数据目录", bg=COLOR_SURFACE, fg=COLOR_TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=24, pady=(18, 3))
        tk.Label(storage_card, text="词频、星标、测试记录、设置和语音缓存都保存在这里。", bg=COLOR_SURFACE, fg=COLOR_MUTED, font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=24, pady=(0, 9))
        storage_row = tk.Frame(storage_card, bg=COLOR_SURFACE)
        storage_row.pack(fill="x", padx=24, pady=(0, 18))
        self.data_dir_var = tk.StringVar(value=str(DATA_DIR))
        tk.Entry(storage_row, textvariable=self.data_dir_var, relief="solid", bd=1, font=("Segoe UI", 9), bg=COLOR_FIELD, fg=COLOR_TEXT, insertbackground=COLOR_ACCENT_TEXT, highlightbackground=COLOR_BORDER).pack(side="left", fill="x", expand=True, ipady=6)
        tk.Button(storage_row, text="选择目录", command=self._choose_data_directory, relief="flat", bg=COLOR_SURFACE_ALT, fg=COLOR_TEXT, activebackground=COLOR_BORDER, activeforeground=COLOR_TEXT, font=("Microsoft YaHei UI", 9), padx=14, pady=7, cursor="hand2").pack(side="left", padx=(10, 0))

        action_row = tk.Frame(settings_body, bg=COLOR_BG)
        action_row.pack(fill="x", padx=4, pady=(4, 12))
        self.settings_status_label = tk.Label(action_row, text="", bg=COLOR_BG, fg=COLOR_SUCCESS, font=("Microsoft YaHei UI", 9))
        self.settings_status_label.pack(side="left")
        tk.Button(action_row, text="保存全部设置", command=self._save_settings_from_ui, relief="flat", bg=COLOR_ACCENT, fg=COLOR_ON_ACCENT, activebackground=COLOR_ACCENT_HOVER, activeforeground=COLOR_ON_ACCENT, font=("Microsoft YaHei UI", 9, "bold"), padx=18, pady=9, cursor="hand2").pack(side="right")

        info_card = tk.Frame(settings_body, bg=COLOR_SURFACE, highlightthickness=1, highlightbackground=COLOR_BORDER)
        info_card.pack(fill="x", padx=4, pady=(0, 18))
        info_lines = (
            ("快捷键", "Alt + Q  划词翻译    ·    Alt + Shift + S  打开单词本    ·    Alt + Shift + Q  退出"),
            ("安装目录", str(BASE_DIR)),
        )
        for index, (label, value) in enumerate(info_lines):
            row = tk.Frame(info_card, bg=COLOR_SURFACE)
            row.pack(fill="x", padx=24, pady=(16 if index == 0 else 8, 16 if index == len(info_lines) - 1 else 8))
            tk.Label(row, text=label, width=9, anchor="w", bg=COLOR_SURFACE, fg=COLOR_TEXT, font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
            tk.Label(row, text=value, anchor="w", bg=COLOR_SURFACE, fg=COLOR_MUTED, font=("Microsoft YaHei UI", 9), wraplength=650, justify="left").pack(side="left", fill="x", expand=True)

        notebook.bind("<<NotebookTabChanged>>", self._on_settings_tab_changed)

    def _stat_card(self, parent: tk.Widget, title: str, value: str, subtitle: str) -> tk.Label:
        card = tk.Frame(parent, bg=COLOR_SURFACE, highlightthickness=1, highlightbackground=COLOR_BORDER)
        card.pack(side="left", fill="x", expand=True, padx=4)
        tk.Label(card, text=title, bg=COLOR_SURFACE, fg=COLOR_MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=18, pady=(15, 2))
        value_label = tk.Label(card, text=value, bg=COLOR_SURFACE, fg=COLOR_TEXT, font=("Segoe UI", 23, "bold"))
        value_label.pack(anchor="w", padx=18)
        tk.Label(card, text=subtitle, bg=COLOR_SURFACE, fg=COLOR_SUBTLE, font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=18, pady=(0, 15))
        return value_label

    def _refresh_dashboard(self) -> None:
        if self.settings_window is None or not self.settings_window.winfo_exists():
            return
        unique_words, total, starred = self.store.stats()
        self.stat_unique.configure(text=str(unique_words))
        self.stat_total.configure(text=str(total))
        self.stat_starred.configure(text=str(starred))
        self.chart_rows = self.store.top_words()
        self._refresh_history()
        self.frequency_canvas.after_idle(self._draw_frequency_chart)

    def _refresh_history(self) -> None:
        if self.settings_window is None or not self.settings_window.winfo_exists() or not hasattr(self, "history_tree"):
            return
        rows = self.store.history(self.history_search_var.get().strip(), self.history_starred_var.get())
        self.history_tree.delete(*self.history_tree.get_children())
        for row in rows:
            last_seen = str(row["last_seen"]).replace("T", " ")[:16]
            self.history_tree.insert(
                "",
                "end",
                iid=str(row["word"]),
                values=(
                    row["word"],
                    row["translation"],
                    row["total_count"],
                    row["lookup_count"],
                    row["sentence_count"],
                    "★" if row["starred"] else "",
                    last_seen,
                ),
            )

    def _toggle_history_star(self, _event: tk.Event) -> None:
        selected = self.history_tree.selection()
        if not selected:
            return
        word = str(selected[0])
        self.store.toggle_star(word)
        if word.casefold() == self.current_word.casefold():
            self._update_star_button()
        self._refresh_dashboard()

    def _draw_frequency_chart(self, _event: tk.Event | None = None) -> None:
        if not hasattr(self, "frequency_canvas"):
            return
        canvas = self.frequency_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 500)
        height = max(canvas.winfo_height(), 220)
        rows = self.chart_rows
        if not rows:
            canvas.create_text(width / 2, height / 2, text="还没有词频记录\n选中英文后按 Alt + Q 开始积累", fill=COLOR_SUBTLE, font=("Microsoft YaHei UI", 10), justify="center")
            return
        margin_x, margin_top, margin_bottom = 38, 28, 66
        available = width - margin_x * 2
        visible_count = min(len(rows), max(5, int(available // 92)))
        rows = rows[:visible_count]
        gap = 12
        bar_width = max(12, (available - gap * (len(rows) - 1)) / len(rows))
        max_count = max(int(row["total_count"]) for row in rows)
        baseline = height - margin_bottom
        chart_height = max(80, baseline - margin_top)
        for index, row in enumerate(rows):
            count = int(row["total_count"])
            x1 = margin_x + index * (bar_width + gap)
            x2 = x1 + bar_width
            bar_height = max(7, chart_height * count / max_count)
            y1 = baseline - bar_height
            color = COLOR_STAR if row["starred"] else COLOR_ACCENT
            canvas.create_rectangle(x1, y1, x2, baseline, fill=color, outline="")
            canvas.create_text((x1 + x2) / 2, y1 - 10, text=str(count), fill=COLOR_MUTED, font=("Segoe UI", 8))
            word = str(row["word"])
            if len(word) > 11:
                split_at = min(7, (len(word) + 1) // 2)
                label = f"{word[:split_at]}\n{word[split_at:12]}{'…' if len(word) > 12 else ''}"
            else:
                label = word
            canvas.create_text(
                (x1 + x2) / 2,
                baseline + 11,
                text=label,
                width=max(52, int(bar_width + gap - 8)),
                anchor="n",
                justify="center",
                fill=COLOR_TEXT,
                font=("Segoe UI", 8),
            )

    def _choose_data_directory(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.settings_window,
            title="选择本地数据目录",
            initialdir=self.data_dir_var.get() or str(DATA_DIR),
            mustexist=False,
        )
        if selected:
            self.data_dir_var.set(str(Path(selected).resolve()))

    def _choose_accent_color(self) -> None:
        _rgb, selected = colorchooser.askcolor(
            color=self.accent_color_var.get(),
            parent=self.settings_window,
            title="选择整套界面主题色",
        )
        if selected:
            self._preview_accent_color(selected)

    def _reset_accent_color(self) -> None:
        self._preview_accent_color(DEFAULT_ACCENT)

    def _preview_accent_color(self, color: str) -> None:
        old_palette = (
            COLOR_BG, COLOR_HEADER, COLOR_SURFACE, COLOR_FIELD, COLOR_SURFACE_ALT, COLOR_BORDER,
            COLOR_TEXT, COLOR_MUTED, COLOR_SUBTLE,
            COLOR_ACCENT, COLOR_ACCENT_HOVER, COLOR_ACCENT_SOFT, COLOR_ACCENT_TEXT, COLOR_ON_ACCENT,
        )
        set_theme_palette(color)
        new_palette = (
            COLOR_BG, COLOR_HEADER, COLOR_SURFACE, COLOR_FIELD, COLOR_SURFACE_ALT, COLOR_BORDER,
            COLOR_TEXT, COLOR_MUTED, COLOR_SUBTLE,
            COLOR_ACCENT, COLOR_ACCENT_HOVER, COLOR_ACCENT_SOFT, COLOR_ACCENT_TEXT, COLOR_ON_ACCENT,
        )
        replacements = dict(zip(old_palette, new_palette))

        def recolor(widget: tk.Misc) -> None:
            for option in (
                "background", "foreground", "activebackground", "activeforeground",
                "insertbackground", "selectcolor", "selectbackground", "selectforeground",
                "highlightbackground", "highlightcolor",
            ):
                try:
                    current = str(widget.cget(option)).lower()
                    if current in replacements:
                        widget.configure(**{option: replacements[current]})
                except tk.TclError:
                    pass
            if isinstance(widget, tk.Canvas):
                for item in widget.find_all():
                    for option in ("fill", "outline"):
                        try:
                            current = str(widget.itemcget(item, option)).lower()
                            if current in replacements:
                                widget.itemconfigure(item, **{option: replacements[current]})
                        except tk.TclError:
                            pass
            for child in widget.winfo_children():
                recolor(child)

        recolor(self.window)
        if self.settings_window is not None and self.settings_window.winfo_exists():
            recolor(self.settings_window)
            style = ttk.Style(self.settings_window)
            style.configure("Wordbook.TNotebook", background=COLOR_BG)
            style.configure("Wordbook.TNotebook.Tab", background=COLOR_SURFACE_ALT, foreground=COLOR_MUTED)
            style.map("Wordbook.TNotebook.Tab", background=[("selected", COLOR_ACCENT_SOFT), ("active", COLOR_SURFACE_ALT)])
            style.configure("Wordbook.Treeview", background=COLOR_SURFACE, fieldbackground=COLOR_SURFACE, foreground=COLOR_TEXT)
            style.map("Wordbook.Treeview", background=[("selected", COLOR_ACCENT_SOFT)], foreground=[("selected", COLOR_TEXT)])
            style.configure("Wordbook.Treeview.Heading", background=COLOR_SURFACE_ALT, foreground=COLOR_TEXT)
            style.configure("Purple.TCombobox", fieldbackground=COLOR_FIELD, background=COLOR_SURFACE_ALT, foreground=COLOR_TEXT, arrowcolor=COLOR_ACCENT_TEXT)
            style.map("Purple.TCombobox", fieldbackground=[("readonly", COLOR_FIELD)], foreground=[("readonly", COLOR_TEXT)], selectbackground=[("readonly", COLOR_FIELD)], selectforeground=[("readonly", COLOR_TEXT)])
            style.configure("Wordbook.Vertical.TScrollbar", troughcolor=COLOR_BG, background=COLOR_SURFACE_ALT, bordercolor=COLOR_BORDER, arrowcolor=COLOR_MUTED, darkcolor=COLOR_SURFACE_ALT, lightcolor=COLOR_SURFACE_ALT)
            self.accent_color_var.set(COLOR_ACCENT)
            self.accent_swatch.configure(bg=COLOR_ACCENT)
            self.accent_hex_label.configure(text=COLOR_ACCENT.upper(), fg=COLOR_ACCENT_TEXT)
        self._set_speaker_state(getattr(self, "speaker_state", "play"))
        self.progress._draw()
        self._draw_frequency_chart()

    def _switch_data_directory(self, destination: Path) -> None:
        destination = destination.expanduser().resolve()
        if destination == DATA_DIR.resolve():
            return
        destination.mkdir(parents=True, exist_ok=True)
        old_data_dir = DATA_DIR
        for name in ("word-history.db", "settings.json", "secrets.json"):
            source = old_data_dir / name
            target = destination / name
            if source.is_file() and not target.exists():
                shutil.copy2(source, target)
        old_cache = old_data_dir / "cache"
        if old_cache.is_dir():
            shutil.copytree(old_cache, destination / "cache", dirs_exist_ok=True)
        BOOTSTRAP_FILE.write_text(
            json.dumps({"data_directory": str(destination)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _set_data_paths(destination)
        self.store = WordStore(WORD_DB)

    def _save_settings_from_ui(self) -> None:
        try:
            requested_directory_text = self.data_dir_var.get().strip()
            if not requested_directory_text:
                raise ValueError("请选择本地数据目录")
            requested_directory = Path(requested_directory_text)
            self._switch_data_directory(requested_directory)
            selected_label = self.engine_label_var.get()
            engine = next((key for key, label in ENGINE_LABELS.items() if label == selected_label), "auto")
            self.translation_engine = engine
            self.user_settings["translation_engine"] = engine
            self.user_settings["accent_color"] = self.accent_color_var.get()
            for provider in LLM_PROVIDERS:
                self.user_settings[f"{provider}_model"] = self.api_model_vars[provider].get().strip() or str(LLM_PROVIDERS[provider]["model"])
                self.api_keys[provider] = self.api_key_vars[provider].get().strip()
            save_user_settings(self.user_settings)
            save_api_secrets(self.api_keys)
            self.data_dir_var.set(str(DATA_DIR))
            self.translation_cache.clear()
            self.settings_status_label.configure(text="✓ 设置已保存", fg=COLOR_SUCCESS)
        except Exception as exc:
            logging.exception("Unable to save settings")
            self.settings_status_label.configure(text="保存失败", fg=COLOR_ERROR)
            messagebox.showerror("保存设置失败", str(exc), parent=self.settings_window)

    def _on_settings_tab_changed(self, event: tk.Event) -> None:
        notebook = event.widget
        if notebook.tab(notebook.select(), "text") == "拼写测试" and not self.quiz_word:
            self._reset_quiz_session()

    def _reset_quiz_session(self) -> None:
        self.quiz_correct = 0
        self.quiz_total = 0
        self.quiz_score_label.configure(text="本轮 0 / 0")
        self._refill_quiz_queue()
        self._next_quiz_word()

    def _refill_quiz_queue(self) -> None:
        self.quiz_queue = list(self.store.quiz_candidates())
        random.shuffle(self.quiz_queue)
        if len(self.quiz_queue) > 1 and self.quiz_word:
            if str(self.quiz_queue[-1]["word"]).casefold() == self.quiz_word.casefold():
                self.quiz_queue[0], self.quiz_queue[-1] = self.quiz_queue[-1], self.quiz_queue[0]

    def _next_quiz_word(self) -> None:
        if not self.quiz_queue:
            self._refill_quiz_queue()
        if not self.quiz_queue:
            self.quiz_word = ""
            self.quiz_chinese_label.configure(text="暂无可测试单词")
            self.quiz_feedback_label.configure(text="先划词翻译几个单词，再回来练习", fg=COLOR_MUTED)
            self.quiz_entry.delete(0, "end")
            return
        row = self.quiz_queue.pop()
        self.quiz_word = str(row["word"])
        self.quiz_answered = False
        self.quiz_chinese_label.configure(text=str(row["translation"]))
        self.quiz_feedback_label.configure(text="请输入对应的英文单词", fg=COLOR_MUTED)
        self.quiz_entry.delete(0, "end")
        self.quiz_entry.focus_set()
        self.root.after(180, self._play_quiz_audio)

    def _submit_quiz(self) -> None:
        if not self.quiz_word:
            return
        if self.quiz_answered:
            self._next_quiz_word()
            return
        answer = self.quiz_entry.get().strip()
        if not answer:
            self.quiz_feedback_label.configure(text="请先输入拼写", fg=COLOR_WARNING)
            return
        correct = answer.casefold() == self.quiz_word.casefold()
        self.quiz_answered = True
        self.store.record_test(self.quiz_word, correct)
        self.quiz_total += 1
        if correct:
            self.quiz_correct += 1
            self.quiz_feedback_label.configure(text="✓ 拼写正确", fg=COLOR_SUCCESS)
        else:
            self.quiz_feedback_label.configure(text=f"正确答案：{self.quiz_word}", fg=COLOR_ERROR)
        self.quiz_score_label.configure(text=f"本轮 {self.quiz_correct} / {self.quiz_total}")

    def _play_quiz_audio(self) -> None:
        if not self.quiz_word or (self.quiz_player is not None and self.quiz_player.poll() is None):
            return
        word = self.quiz_word
        self.quiz_feedback_label.configure(text="正在准备读音…", fg=COLOR_MUTED)
        threading.Thread(target=self._play_quiz_audio_worker, args=(word,), daemon=True).start()

    def _play_quiz_audio_worker(self, word: str) -> None:
        error = ""
        try:
            key = hashlib.sha256(f"{VOICE}|{word}".encode("utf-8")).hexdigest()
            path = CACHE_DIR / f"{key}.mp3"
            if not path.exists() or path.stat().st_size == 0:
                asyncio.run(synthesize(word, path))
            self.quiz_player = subprocess.Popen(player_command(path), creationflags=CREATE_NO_WINDOW)
            self.quiz_player.wait()
        except Exception as exc:
            logging.exception("Quiz speech failed")
            error = str(exc)
        finally:
            self.quiz_player = None
            self.events.put(("quiz_audio_done", (word, error)))

    @staticmethod
    def _compact(text: str, limit: int) -> str:
        single_line = " ".join(text.split())
        single_line = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff0-9（(])", "", single_line)
        single_line = re.sub(r"(?<=[0-9）)])\s+(?=[\u4e00-\u9fff])", "", single_line)
        single_line = re.sub(r"\s+([，。！？；：、）])", r"\1", single_line)
        single_line = re.sub(r"([（])\s+", r"\1", single_line)
        single_line = re.sub(r"(?<=\d)\s*/\s*(?=[（(])", "/", single_line)
        return single_line if len(single_line) <= limit else f"{single_line[:limit - 1]}…"

    def _set_speaker_state(self, state: str) -> None:
        styles = {
            "play": (COLOR_ACCENT_SOFT, COLOR_BORDER),
            "wait": (COLOR_SURFACE_ALT, COLOR_BORDER),
            "stop": (blend_hex(COLOR_SURFACE, COLOR_ERROR, 0.18), blend_hex(COLOR_BORDER, COLOR_ERROR, 0.28)),
        }
        self.speaker_state = state
        fill, outline = styles[state]
        self.speaker.itemconfigure(self.speaker_circle, fill=fill, outline=outline)
        self.speaker.itemconfigure("speaker-icon", state="hidden")
        self.speaker.itemconfigure(f"speaker-{state}", state="normal")
        if state == "play":
            self.speaker.itemconfigure(self.speaker_body, fill=COLOR_ACCENT_TEXT)
            self.speaker.itemconfigure(self.speaker_wave_inner, outline=COLOR_ACCENT_TEXT)
            self.speaker.itemconfigure(self.speaker_wave_outer, outline=COLOR_ACCENT_TEXT)
        elif state == "wait":
            for dot in self.speaker_wait_dots:
                self.speaker.itemconfigure(dot, fill=COLOR_MUTED)
        else:
            self.speaker.itemconfigure(self.speaker_stop, fill=COLOR_ERROR)

    def _set_speaker_hover(self, hovering: bool) -> None:
        if getattr(self, "speaker_state", "play") != "play":
            return
        fill = blend_hex(COLOR_ACCENT_SOFT, COLOR_ACCENT, 0.16) if hovering else COLOR_ACCENT_SOFT
        self.speaker.itemconfigure(self.speaker_circle, fill=fill)

    def _set_card_text(self, source: str, translation: str) -> None:
        self.card_source = self._compact(source, 260)
        self.card_translation = self._compact(translation, 1400)
        self.source_label.configure(text=self.card_source)
        self.translation_label.configure(text=self.card_translation)
        phonetic = phonetic_for_selection(source)
        self.phonetic_label.configure(text=phonetic)
        if phonetic:
            if not self.phonetic_label.winfo_manager():
                self.phonetic_label.pack(fill="x", pady=(0, 5), before=self.status_label)
        else:
            self.phonetic_label.pack_forget()

    def _natural_wrap(self, text: str, max_width: int, font_name: str) -> str:
        def measure(value: str) -> int:
            return int(self.root.tk.call("font", "measure", font_name, value))

        lines: list[str] = []
        line = ""
        for raw_token in WRAP_TOKEN_RE.findall(text):
            token = " " if raw_token.isspace() else raw_token
            if token == " " and (not line or line.endswith(" ")):
                continue
            candidate = line + token
            if measure(candidate) <= max_width:
                line = candidate
                continue
            if token in CLOSING_PUNCTUATION and line:
                line += token
                continue
            if line:
                if line[-1:] in OPENING_PUNCTUATION:
                    token = line[-1] + token.lstrip()
                    line = line[:-1]
                if line.rstrip():
                    lines.append(line.rstrip())
            line = token.lstrip()
            if line and measure(line) > max_width:
                fragment = ""
                for character in line:
                    if fragment and measure(fragment + character) > max_width:
                        lines.append(fragment)
                        fragment = character
                    else:
                        fragment += character
                line = fragment
        if line.rstrip():
            lines.append(line.rstrip())
        return "\n".join(lines)

    def _apply_native_style(self) -> None:
        try:
            self.window.update_idletasks()
            hwnd = user32.GetAncestor(self.window.winfo_id(), 2) or self.window.winfo_id()
            preference = ctypes.c_int(DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(preference),
                ctypes.sizeof(preference),
            )
        except Exception:
            logging.debug("Rounded-corner styling unavailable", exc_info=True)

    def _on_focus_out(self, _event: tk.Event) -> None:
        if self.light_dismiss_armed:
            self.root.after(35, self._dismiss_if_inactive)

    def _dismiss_if_inactive(self) -> None:
        if not self.light_dismiss_armed or not self.window.winfo_viewable():
            return
        focused = self.window.focus_get()
        if focused is None or focused.winfo_toplevel() != self.window:
            self.hide()

    def _watch_outside_click(self) -> None:
        down = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000) or bool(user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
        if down and not self._mouse_was_down and self.light_dismiss_armed and self.window.winfo_viewable():
            point = POINT()
            user32.GetCursorPos(ctypes.byref(point))
            left = self.window.winfo_rootx()
            top = self.window.winfo_rooty()
            right = left + self.window.winfo_width()
            bottom = top + self.window.winfo_height()
            if not (left <= point.x <= right and top <= point.y <= bottom):
                self.hide()
        self._mouse_was_down = down
        self.root.after(40, self._watch_outside_click)

    def _set_progress_busy(self, status: str) -> None:
        self.progress.start(12)
        self.status_label.configure(text=status)

    def _update_progress(self) -> None:
        self.progress.stop()
        if self.translation_done and self.audio_done:
            self.progress.set(100)
            if self.audio_error:
                self.status_label.configure(text=f"翻译 {self.translation_seconds:.1f}s · 语音准备失败")
            else:
                self.status_label.configure(text=f"完成 · 翻译 {self.translation_seconds:.1f}s · 语音 {self.audio_seconds:.1f}s")
        elif self.translation_done:
            self.progress.set(75)
            self.status_label.configure(text=f"翻译完成 {self.translation_seconds:.1f}s · 正在准备语音…")
        elif self.audio_done:
            self.progress.set(55)
            self.status_label.configure(text=f"语音已准备 {self.audio_seconds:.1f}s · 正在翻译…")
        else:
            self.progress.set(10)
            self.status_label.configure(text="正在处理…")

    def _resize_at_anchor(self) -> None:
        anchor_x, anchor_y = self.anchor
        if not anchor_x and not anchor_y:
            point = POINT()
            user32.GetCursorPos(ctypes.byref(point))
            anchor_x, anchor_y = point.x, point.y
        left, top, right, bottom = monitor_work_area(anchor_x, anchor_y)
        screen_w = right - left
        screen_h = bottom - top
        self._set_popup_scale(monitor_dpi(anchor_x, anchor_y) / self.popup_base_dpi)
        scale = self.popup_scale
        content_length = max(len(self.card_source), len(self.card_translation))
        max_width = min(round(920 * scale), screen_w - round(48 * scale))
        if content_length <= 24:
            width = 350
        elif content_length <= 100:
            width = 430 + int((content_length - 24) * 2.8)
        else:
            width = 642 + int((content_length - 100) * 1.35)
        width = min(max_width, round(width * scale))
        text_width = width - round(110 * scale)
        source_size = round((9 if len(self.card_source) <= 150 else 8) * scale)
        if len(self.card_translation) <= 80:
            translation_font = ("Microsoft YaHei UI", round(14 * scale), "bold")
        elif len(self.card_translation) <= 260:
            translation_font = ("Microsoft YaHei UI", round(11 * scale), "bold")
        else:
            translation_font = ("Microsoft YaHei UI", round(10 * scale))
        self.source_label.configure(font=("Segoe UI", source_size))
        self.translation_label.configure(font=translation_font)
        self.source_label.configure(text=self._natural_wrap(self.card_source, text_width, self.source_label.cget("font")), wraplength=0)
        self.translation_label.configure(
            text=self._natural_wrap(self.card_translation, text_width, self.translation_label.cget("font")),
            wraplength=0,
        )
        self.status_label.configure(wraplength=text_width)
        self.window.update_idletasks()
        height = max(round(118 * scale), min(screen_h - round(96 * scale), self.window.winfo_reqheight()))
        x = anchor_x + round(14 * scale)
        y = anchor_y + round(18 * scale)
        if x + width > right - round(12 * scale):
            x = anchor_x - width - round(14 * scale)
        if y + height > bottom - round(12 * scale):
            y = anchor_y - height - round(18 * scale)
        x = min(max(left + round(12 * scale), x), right - width - round(12 * scale))
        y = min(max(top + round(12 * scale), y), bottom - height - round(12 * scale))
        self.window.geometry(f"{width}x{height}")
        self.window.update_idletasks()
        hwnd = user32.GetAncestor(self.window.winfo_id(), 2) or self.window.winfo_id()
        user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def show_window(self) -> None:
        self._resize_at_anchor()
        self.light_dismiss_armed = False
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
        self._apply_native_style()
        self.root.after(220, self._arm_light_dismiss)

    def _arm_light_dismiss(self) -> None:
        if self.window.winfo_viewable():
            self.light_dismiss_armed = True

    def show_guide(self) -> None:
        self.progress.stop()
        self.progress.set(0)
        self.status_label.configure(text="Alt + Shift + S 打开单词本")
        self.current_word = ""
        self._update_star_button()
        self._set_card_text("划词翻译朗读", "选中文字后按 Alt + Q")
        self._set_speaker_state("play")
        self.show_window()

    def _hotkey_loop(self) -> None:
        self.hotkey_thread_id = kernel32.GetCurrentThreadId()
        modifiers = MOD_ALT | MOD_NOREPEAT
        translate_ok = bool(user32.RegisterHotKey(None, HOTKEY_TRANSLATE, modifiers, VK_Q))
        exit_ok = bool(user32.RegisterHotKey(None, HOTKEY_EXIT, modifiers | MOD_SHIFT, VK_Q))
        settings_ok = bool(user32.RegisterHotKey(None, HOTKEY_SETTINGS, modifiers | MOD_SHIFT, VK_S))
        logging.info("Hotkeys registered: translate=%s exit=%s settings=%s", translate_ok, exit_ok, settings_ok)
        self.events.put(("hotkey_status", (translate_ok, exit_ok, settings_ok)))
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY and message.wParam == HOTKEY_TRANSLATE:
                    point = POINT()
                    user32.GetCursorPos(ctypes.byref(point))
                    self.events.put(("capture", (int(user32.GetForegroundWindow()), point.x, point.y)))
                elif message.message == WM_HOTKEY and message.wParam == HOTKEY_EXIT:
                    self.events.put(("exit", None))
                elif message.message == WM_HOTKEY and message.wParam == HOTKEY_SETTINGS:
                    self.events.put(("settings", None))
        finally:
            user32.UnregisterHotKey(None, HOTKEY_TRANSLATE)
            user32.UnregisterHotKey(None, HOTKEY_EXIT)
            user32.UnregisterHotKey(None, HOTKEY_SETTINGS)

    def _poll(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "capture":
                    window_handle, anchor_x, anchor_y = value  # type: ignore[misc]
                    self.anchor = (int(anchor_x), int(anchor_y))
                    threading.Thread(target=self._capture_worker, args=(int(window_handle),), daemon=True).start()
                elif kind == "selection":
                    self._show_selection(str(value))
                elif kind == "translation":
                    generation, ok, text, elapsed = value  # type: ignore[misc]
                    if generation != self.request_generation:
                        continue
                    self.translation = str(text) if ok else ""
                    self.card_translation = self._compact(str(text), 1400)
                    self.translation_label.configure(text=self.card_translation)
                    self.translation_done = True
                    self.translation_seconds = float(elapsed)
                    if ok and self.current_word:
                        self.store.update_details(self.current_word, self.translation, phonetic_for_selection(self.source_text))
                        self._refresh_dashboard()
                    self._update_progress()
                    if self.window.winfo_viewable():
                        self._resize_at_anchor()
                elif kind == "audio_ready":
                    generation, path, error, elapsed = value  # type: ignore[misc]
                    if generation != self.request_generation:
                        continue
                    self.audio_path = Path(path) if path else None
                    self.audio_error = str(error)
                    self.audio_done = True
                    self.audio_seconds = float(elapsed)
                    self._update_progress()
                    if self.play_when_ready and self.audio_path is not None:
                        self._start_playback(self.audio_path)
                    elif self.player is None:
                        self._set_speaker_state("play")
                elif kind == "speech_done":
                    generation, error = value  # type: ignore[misc]
                    if generation == self.speech_generation:
                        self.player = None
                        self._set_speaker_state("play")
                        if error:
                            self.status_label.configure(text=f"朗读失败：{error}")
                elif kind == "quiz_audio_done":
                    word, error = value  # type: ignore[misc]
                    if str(word) == self.quiz_word and error:
                        self.quiz_feedback_label.configure(text=f"读音播放失败：{error}", fg=COLOR_ERROR)
                    elif str(word) == self.quiz_word and self.quiz_feedback_label.cget("text") == "正在准备读音…":
                        self.quiz_feedback_label.configure(text="请输入对应的英文单词", fg=COLOR_MUTED)
                elif kind == "hotkey_status":
                    translate_ok, _, settings_ok = value  # type: ignore[misc]
                    if not translate_ok:
                        self._set_card_text("快捷键注册失败", "Alt + Q 被其他软件占用了")
                        self.progress.stop()
                        self.progress.set(0)
                        self.status_label.configure(text="快捷键不可用")
                        self.show_window()
                    elif not settings_ok:
                        logging.warning("Settings hotkey Alt+Shift+S is unavailable")
                elif kind == "settings":
                    self.open_settings()
                elif kind == "exit":
                    self.shutdown()
                    return
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _capture_worker(self, window_handle: int) -> None:
        started = time.perf_counter()
        text = ""
        window_class = get_window_class(window_handle)
        browser_window = window_class.startswith("Chrome_WidgetWin")
        attempts = (
            (("clipboard", 0.65), ("uia", 1.1), ("clipboard", 0.75))
            if browser_window
            else (("uia", 0.65), ("clipboard", 0.75), ("uia", 1.0))
        )
        for attempt_number, (method, timeout) in enumerate(attempts, start=1):
            if method == "uia":
                try:
                    text = capture_selection_uia(window_handle, timeout=timeout)
                    if text:
                        logging.info("Selection captured through UI Automation on attempt %s", attempt_number)
                except subprocess.TimeoutExpired:
                    logging.warning("UI Automation selection timed out for %s after %.2fs", window_class, timeout)
                except Exception:
                    logging.exception("UI Automation selection failed")
            else:
                try:
                    text = capture_selection(timeout=timeout)
                except Exception:
                    logging.exception("Clipboard selection attempt %s failed", attempt_number)
                    text = ""
                if text:
                    logging.info("Selection captured through clipboard on attempt %s", attempt_number)
            if text:
                break
        logging.info("Selection capture finished in %.3fs success=%s", time.perf_counter() - started, bool(text))
        self.events.put(("selection", text))

    def _warm_translation(self) -> None:
        started = time.perf_counter()
        try:
            if self.translation_engine in LLM_PROVIDERS:
                return
            if self.translation_engine == "microsoft":
                translate_microsoft("hello")
            else:
                translate_tencent("hello")
            logging.info("Translation connection warmed in %.3fs", time.perf_counter() - started)
        except Exception:
            logging.exception("Translation warm-up failed")

    def _show_selection(self, text: str) -> None:
        self.stop_speech()
        self.request_generation += 1
        generation = self.request_generation
        if not text:
            self.source_text = ""
            self.translation = ""
            self.current_word = ""
            self._update_star_button()
            self._set_card_text("没有读取到选区", "请重新选中文字")
            self._set_speaker_state("play")
            self.progress.stop()
            self.progress.set(0)
            self.status_label.configure(text="没有读取到文字")
            self.show_window()
            return
        self.source_text = text[:5000]
        self.current_word = self.store.record_selection(self.source_text)
        self.translation = ""
        self.translation_done = False
        self.audio_done = False
        self.translation_seconds = 0.0
        self.audio_seconds = 0.0
        self.audio_path = None
        self.audio_error = ""
        self.play_when_ready = False
        self._set_card_text(self.source_text, "正在翻译…")
        self._update_star_button()
        self._refresh_dashboard()
        self._set_speaker_state("wait")
        self._set_progress_busy("正在翻译，同时准备语音…")
        self.show_window()
        threading.Thread(target=self._translate_worker, args=(self.source_text, generation), daemon=True).start()
        threading.Thread(target=self._prefetch_audio_worker, args=(self.source_text, generation), daemon=True).start()

    def _translate_worker(self, text: str, generation: int) -> None:
        started = time.perf_counter()
        try:
            engine = self.translation_engine
            api_key = self.api_keys.get(engine, "")
            model = self.user_settings.get(f"{engine}_model", "")
            cache_key = f"{engine}\0{model}\0{text}"
            translated = self.translation_cache.get(cache_key)
            if translated is None:
                translated = translate_to_chinese(text, engine, api_key, model)
                if len(self.translation_cache) >= 128:
                    self.translation_cache.pop(next(iter(self.translation_cache)))
                self.translation_cache[cache_key] = translated
            self.events.put(("translation", (generation, True, translated, time.perf_counter() - started)))
        except Exception as exc:
            logging.exception("Translation failed")
            self.events.put(("translation", (generation, False, f"翻译失败：{exc}", time.perf_counter() - started)))

    def _prefetch_audio_worker(self, text: str, generation: int) -> None:
        started = time.perf_counter()
        path: Path | None = None
        error = ""
        try:
            key = hashlib.sha256(f"{VOICE}|{text}".encode("utf-8")).hexdigest()
            path = CACHE_DIR / f"{key}.mp3"
            if not path.exists() or path.stat().st_size == 0:
                asyncio.run(synthesize(text, path))
        except Exception as exc:
            logging.exception("Speech prefetch failed")
            error = str(exc)
            path = None
        self.events.put(("audio_ready", (generation, path, error, time.perf_counter() - started)))

    def copy_translation(self) -> None:
        if self.translation:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.translation)

    def toggle_speech(self) -> None:
        if self.play_when_ready or (self.player is not None and self.player.poll() is None):
            self.stop_speech()
            return
        if not self.source_text:
            return
        if self.audio_path is not None:
            self._start_playback(self.audio_path)
            return
        if self.audio_done and self.audio_error:
            self.status_label.configure(text=f"朗读失败：{self.audio_error}")
            return
        self.play_when_ready = True
        self._set_speaker_state("wait")

    def _start_playback(self, path: Path) -> None:
        self.play_when_ready = False
        self.speech_generation += 1
        generation = self.speech_generation
        self._set_speaker_state("stop")
        threading.Thread(target=self._playback_worker, args=(path, generation), daemon=True).start()

    def _playback_worker(self, path: Path, generation: int) -> None:
        error = ""
        try:
            self.player = subprocess.Popen(player_command(path), creationflags=CREATE_NO_WINDOW)
            self.player.wait()
        except Exception as exc:
            logging.exception("Speech failed")
            error = str(exc)
        finally:
            self.events.put(("speech_done", (generation, error)))

    def stop_speech(self) -> None:
        self.play_when_ready = False
        self.speech_generation += 1
        player = self.player
        self.player = None
        if player is not None and player.poll() is None:
            player.terminate()
        self._set_speaker_state("play")

    def hide(self) -> None:
        self.light_dismiss_armed = False
        self.stop_speech()
        self.window.withdraw()

    def shutdown(self) -> None:
        self.stop_speech()
        quiz_player = self.quiz_player
        if quiz_player is not None and quiz_player.poll() is None:
            quiz_player.terminate()
        if self.hotkey_thread_id:
            user32.PostThreadMessageW(self.hotkey_thread_id, WM_QUIT, 0, 0)
        self.root.quit()
        self.root.destroy()

    def run(self) -> None:
        logging.info("SelectTranslate started")
        self.root.mainloop()


def self_test() -> int:
    sample = "The quick brown fox jumps over the lazy dog."
    translated = translate_to_chinese(sample)
    audio = CACHE_DIR / "self-test.mp3"
    asyncio.run(synthesize(sample, audio))
    print(f"translation={translated}")
    print(f"audio={audio} bytes={audio.stat().st_size}")
    return 0


def main() -> int:
    enable_high_dpi()
    parser = argparse.ArgumentParser()
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    mutex = kernel32.CreateMutexW(None, True, "Global\\SelectTranslate_SingleInstance")
    if mutex and kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        if not args.background:
            user32.MessageBoxW(None, "程序已经在后台运行。\n\n选中文字后按 Alt + Q。", APP_NAME, 0x40)
        return 0
    try:
        App(args.background).run()
    finally:
        if mutex:
            kernel32.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
