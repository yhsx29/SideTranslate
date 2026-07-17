from __future__ import annotations

import logging
import os
import queue
import threading
import time
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, ttk

from .baidu import BaiduClient, BaiduError, Translation
from .config import AppConfig, load_config, save_config
from .logging_setup import LOG_DIR, setup_logging
from .windows import (
    GlobalHotkeys,
    HotkeyError,
    MouseHookError,
    MouseSelectionWatcher,
    clipboard_sequence_number,
    copy_selected_text,
    cursor_position,
    launch_screen_clip,
    set_clipboard_text,
    set_dpi_awareness,
    wait_for_clipboard_image,
)


COLORS = {
    "bg": "#F4FBFA",
    "surface": "#FFFFFF",
    "surface_alt": "#F7FBFD",
    "line": "#CFE8E4",
    "text": "#183B3A",
    "muted": "#5D7476",
    "subtle": "#64748B",
    "primary": "#0F766E",
    "primary_hover": "#0B625C",
    "primary_soft": "#E5F7F3",
    "secondary": "#4F7DF3",
    "secondary_soft": "#EDF2FF",
    "accent": "#EA580C",
    "accent_soft": "#FFF0E9",
    "pink_soft": "#FFF0F5",
    "yellow_soft": "#FFF8D8",
    "success": "#147D5B",
    "success_soft": "#E6F7EF",
    "warning": "#B85C00",
    "danger": "#D14343",
}

LANGUAGES = {
    "自动检测": "auto",
    "中文": "zh",
    "英语": "en",
    "日语": "jp",
    "韩语": "kor",
    "法语": "fra",
    "德语": "de",
    "西班牙语": "spa",
    "俄语": "ru",
}
LANGUAGE_LABELS = {value: key for key, value in LANGUAGES.items()}
logger = logging.getLogger(__name__)


def _rounded_rectangle(
    canvas: tk.Canvas,
    left: float,
    top: float,
    right: float,
    bottom: float,
    radius: float,
    **options,
) -> int:
    radius = max(1, min(radius, (right - left) / 2, (bottom - top) / 2))
    points = [
        left + radius,
        top,
        right - radius,
        top,
        right,
        top,
        right,
        top + radius,
        right,
        bottom - radius,
        right,
        bottom,
        right - radius,
        bottom,
        left + radius,
        bottom,
        left,
        bottom,
        left,
        bottom - radius,
        left,
        top + radius,
        left,
        top,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **options)


class RoundedPanel(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        *,
        fill: str = COLORS["surface"],
        border: str = COLORS["line"],
        radius: int = 18,
        inset: int = 8,
        height: int | None = None,
    ) -> None:
        background = str(master.cget("bg"))
        super().__init__(
            master,
            bg=background,
            highlightthickness=0,
            bd=0,
            height=height or 1,
        )
        self.fill = fill
        self.border = border
        self.radius = radius
        self.inset = inset
        self.content = tk.Frame(self, bg=fill)
        self._content_window = self.create_window(
            inset,
            inset,
            anchor="nw",
            window=self.content,
        )
        self.bind("<Configure>", self._redraw)

    def _redraw(self, _event: tk.Event | None = None) -> None:
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height())
        self.delete("panel")
        _rounded_rectangle(
            self,
            1,
            1,
            width - 1,
            height - 1,
            self.radius,
            fill=self.fill,
            outline=self.border,
            width=1,
            tags="panel",
        )
        self.tag_lower("panel")
        self.coords(self._content_window, self.inset, self.inset)
        self.itemconfigure(
            self._content_window,
            width=max(1, width - self.inset * 2),
            height=max(1, height - self.inset * 2),
        )


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command,
        *,
        width: int = 104,
        height: int = 40,
        fill: str = COLORS["primary"],
        foreground: str = "white",
        hover: str = COLORS["primary_hover"],
        radius: int = 13,
        font: tuple = ("Microsoft YaHei UI", 9),
    ) -> None:
        super().__init__(
            master,
            width=width,
            height=height,
            bg=str(master.cget("bg")),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=1,
        )
        self.command = command
        self.text = text
        self.fill = fill
        self.foreground = foreground
        self.hover = hover
        self.radius = radius
        self.text_font = font
        self._hovered = False
        self._pressed = False
        self._focused = False
        self.enabled = True
        self.bind("<Configure>", self._redraw)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self.bind("<Return>", self._invoke)
        self.bind("<space>", self._invoke)
        self.after_idle(self._redraw)

    def set_colors(self, fill: str, foreground: str, hover: str) -> None:
        self.fill = fill
        self.foreground = foreground
        self.hover = hover
        self._redraw()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self._hovered = False
        self._pressed = False
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    def _redraw(self, _event: tk.Event | None = None) -> None:
        self.delete("all")
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height())
        fill = (
            COLORS["surface_alt"]
            if not self.enabled
            else self.hover
            if self._hovered or self._pressed
            else self.fill
        )
        foreground = COLORS["subtle"] if not self.enabled else self.foreground
        outline = COLORS["secondary"] if self._focused else fill
        outline_width = 2 if self._focused else 1
        _rounded_rectangle(
            self,
            2,
            2,
            width - 2,
            height - 2,
            self.radius,
            fill=fill,
            outline=outline,
            width=outline_width,
        )
        self.create_text(
            width / 2,
            height / 2,
            text=self.text,
            fill=foreground,
            font=self.text_font,
        )

    def _enter(self, _event: tk.Event) -> None:
        if not self.enabled:
            return
        self._hovered = True
        self._redraw()

    def _leave(self, _event: tk.Event) -> None:
        self._hovered = False
        self._pressed = False
        self._redraw()

    def _press(self, _event: tk.Event) -> None:
        if not self.enabled:
            return
        self.focus_set()
        self._pressed = True
        self._redraw()

    def _release(self, event: tk.Event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._redraw()
        if self.enabled and was_pressed and 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.command()

    def _invoke(self, _event: tk.Event) -> None:
        if self.enabled:
            self.command()

    def _focus_in(self, _event: tk.Event) -> None:
        self._focused = True
        self._redraw()

    def _focus_out(self, _event: tk.Event) -> None:
        self._focused = False
        self._redraw()


class PillLabel(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        text: str,
        *,
        width: int,
        height: int = 28,
        fill: str,
        foreground: str,
        font: tuple = ("Microsoft YaHei UI", 8),
    ) -> None:
        super().__init__(
            master,
            width=width,
            height=height,
            bg=str(master.cget("bg")),
            highlightthickness=0,
            bd=0,
        )
        self.text = text
        self.fill = fill
        self.foreground = foreground
        self.text_font = font
        self.bind("<Configure>", self._redraw)
        self.after_idle(self._redraw)

    def configure(self, cnf=None, **kwargs):  # type: ignore[override]
        if "text" in kwargs:
            self.text = kwargs.pop("text")
        if "bg" in kwargs:
            self.fill = kwargs.pop("bg")
        if "fg" in kwargs:
            self.foreground = kwargs.pop("fg")
        result = super().configure(cnf, **kwargs)
        self._redraw()
        return result

    config = configure

    def _redraw(self, _event: tk.Event | None = None) -> None:
        self.delete("all")
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height())
        _rounded_rectangle(
            self,
            1,
            1,
            width - 1,
            height - 1,
            height / 2,
            fill=self.fill,
            outline=self.fill,
        )
        self.create_text(
            width / 2,
            height / 2,
            text=self.text,
            fill=self.foreground,
            font=self.text_font,
        )


class RoundedEntry(RoundedPanel):
    def __init__(
        self,
        master: tk.Misc,
        variable: tk.StringVar,
        *,
        secret: bool = False,
    ) -> None:
        super().__init__(
            master,
            fill=COLORS["surface_alt"],
            border=COLORS["line"],
            radius=11,
            inset=6,
            height=40,
        )
        self.entry = tk.Entry(
            self.content,
            textvariable=variable,
            show="●" if secret else "",
            bd=0,
            relief="flat",
            bg=COLORS["surface_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["primary"],
            selectbackground=COLORS["secondary_soft"],
            selectforeground=COLORS["text"],
            font=("Microsoft YaHei UI", 9),
        )
        self.entry.pack(fill="both", expand=True, padx=4)
        self.entry.bind("<FocusIn>", lambda _event: self._set_focus(True))
        self.entry.bind("<FocusOut>", lambda _event: self._set_focus(False))

    def _set_focus(self, focused: bool) -> None:
        self.border = COLORS["secondary"] if focused else COLORS["line"]
        self._redraw()


class RoundedSelect(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        variable: tk.StringVar,
        values: list[str],
        *,
        width: int = 124,
    ) -> None:
        super().__init__(
            master,
            width=width,
            height=40,
            bg=str(master.cget("bg")),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=1,
        )
        self.variable = variable
        self.values = values
        self._hovered = False
        self._focused = False
        self.enabled = True
        self.menu = tk.Menu(
            self,
            tearoff=False,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            activebackground=COLORS["primary_soft"],
            activeforeground=COLORS["primary"],
            font=("Microsoft YaHei UI", 9),
            bd=1,
            relief="solid",
        )
        for value in values:
            self.menu.add_command(label=value, command=lambda item=value: self.variable.set(item))
        self.variable.trace_add("write", lambda *_args: self._redraw())
        self.bind("<Configure>", self._redraw)
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self.bind("<ButtonPress-1>", lambda _event: self.focus_set())
        self.bind("<ButtonRelease-1>", self._open)
        self.bind("<Return>", self._open)
        self.bind("<space>", self._open)
        self.bind("<Down>", lambda _event: self._cycle(1))
        self.bind("<Up>", lambda _event: self._cycle(-1))
        self.bind("<FocusIn>", lambda _event: self._set_focus(True))
        self.bind("<FocusOut>", lambda _event: self._set_focus(False))
        self.after_idle(self._redraw)

    def _open(self, _event: tk.Event) -> None:
        self.menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height())

    def _cycle(self, direction: int) -> None:
        try:
            index = self.values.index(self.variable.get())
        except ValueError:
            index = 0
        self.variable.set(self.values[(index + direction) % len(self.values)])

    def _set_hover(self, hovered: bool) -> None:
        self._hovered = hovered
        self._redraw()

    def _set_focus(self, focused: bool) -> None:
        self._focused = focused
        self._redraw()

    def _redraw(self, _event: tk.Event | None = None) -> None:
        self.delete("all")
        width = max(2, self.winfo_width())
        fill = COLORS["primary_soft"] if self._hovered else COLORS["surface_alt"]
        outline = COLORS["secondary"] if self._focused else COLORS["line"]
        _rounded_rectangle(
            self,
            2,
            2,
            width - 2,
            38,
            12,
            fill=fill,
            outline=outline,
            width=2 if self._focused else 1,
        )
        self.create_text(
            13,
            20,
            text=self.variable.get(),
            anchor="w",
            fill=COLORS["text"],
            font=("Microsoft YaHei UI", 9),
        )
        self.create_line(
            width - 22,
            17,
            width - 17,
            22,
            width - 12,
            17,
            fill=COLORS["muted"],
            width=2,
            capstyle="round",
            joinstyle="round",
        )


class ToggleSwitch(tk.Canvas):
    def __init__(self, master: tk.Misc, variable: tk.BooleanVar) -> None:
        super().__init__(
            master,
            width=46,
            height=26,
            bg=str(master.cget("bg")),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=1,
        )
        self.variable = variable
        self._focused = False
        self.bind("<ButtonRelease-1>", self._toggle)
        self.bind("<Return>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<FocusIn>", lambda _event: self._set_focus(True))
        self.bind("<FocusOut>", lambda _event: self._set_focus(False))
        self.variable.trace_add("write", lambda *_args: self._redraw())
        self.after_idle(self._redraw)

    def _toggle(self, _event: tk.Event) -> None:
        self.focus_set()
        self.variable.set(not self.variable.get())

    def _set_focus(self, focused: bool) -> None:
        self._focused = focused
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        enabled = self.variable.get()
        track = COLORS["primary"] if enabled else "#CBDAD8"
        outline = COLORS["secondary"] if self._focused else track
        _rounded_rectangle(
            self,
            2,
            2,
            44,
            24,
            11,
            fill=track,
            outline=outline,
            width=2 if self._focused else 1,
        )
        center_x = 33 if enabled else 13
        self.create_oval(
            center_x - 8,
            5,
            center_x + 8,
            21,
            fill="white",
            outline="white",
        )


class ActionCard(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        icon: str,
        title: str,
        hotkey: str,
        command,
        *,
        icon_fill: str,
        icon_color: str,
    ) -> None:
        super().__init__(
            master,
            height=70,
            bg=str(master.cget("bg")),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=1,
        )
        self.icon = icon
        self.title = title
        self.hotkey = hotkey
        self.command = command
        self.icon_fill = icon_fill
        self.icon_color = icon_color
        self._hovered = False
        self._focused = False
        self.enabled = True
        self.bind("<Configure>", self._redraw)
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self.bind("<ButtonPress-1>", lambda _event: self.focus_set())
        self.bind("<ButtonRelease-1>", self._activate)
        self.bind("<FocusIn>", lambda _event: self._set_focus(True))
        self.bind("<FocusOut>", lambda _event: self._set_focus(False))
        self.bind("<Return>", self._invoke)
        self.bind("<space>", self._invoke)

    def set_hotkey(self, hotkey: str) -> None:
        self.hotkey = hotkey
        self._redraw()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self._hovered = False
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    def _activate(self, event: tk.Event) -> None:
        if self.enabled and 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.command()

    def _invoke(self, _event: tk.Event) -> None:
        if self.enabled:
            self.command()

    def _set_hover(self, hovered: bool) -> None:
        if not self.enabled:
            return
        self._hovered = hovered
        self._redraw()

    def _set_focus(self, focused: bool) -> None:
        self._focused = focused
        self._redraw()

    def _redraw(self, _event: tk.Event | None = None) -> None:
        self.delete("all")
        width = max(120, self.winfo_width())
        fill = COLORS["primary_soft"] if self._hovered else COLORS["surface_alt"]
        outline = COLORS["secondary"] if self._focused else COLORS["line"]
        _rounded_rectangle(
            self,
            2,
            2,
            width - 2,
            68,
            17,
            fill=fill,
            outline=outline,
            width=2 if self._focused else 1,
        )
        _rounded_rectangle(
            self,
            13,
            13,
            55,
            57,
            13,
            fill=self.icon_fill,
            outline=self.icon_fill,
        )
        self.create_text(
            34,
            35,
            text=self.icon,
            fill=self.icon_color,
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        self.create_text(
            69,
            35,
            text=self.title,
            anchor="w",
            fill=COLORS["text"] if self.enabled else COLORS["subtle"],
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        pill_width = max(76, len(self.hotkey) * 7 + 18)
        _rounded_rectangle(
            self,
            width - pill_width - 13,
            21,
            width - 13,
            49,
            11,
            fill=COLORS["surface"],
            outline=COLORS["line"],
        )
        self.create_text(
            width - pill_width / 2 - 13,
            35,
            text=self.hotkey,
            fill=COLORS["primary"] if self.enabled else COLORS["subtle"],
            font=("Consolas", 8),
        )


class ResultPopup(tk.Toplevel):
    def __init__(self, app: "SideTranslateApp") -> None:
        super().__init__(app.root)
        self.app = app
        self.overrideredirect(True)
        self.withdraw()
        self._transparent_key = "#FF00FF"
        self.configure(bg=self._transparent_key)
        try:
            self.attributes("-transparentcolor", self._transparent_key)
        except tk.TclError:
            self.configure(bg=COLORS["bg"])
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._translation: Translation | None = None
        self._build()

    def _build(self) -> None:
        surface = RoundedPanel(
            self,
            fill=COLORS["surface"],
            border=COLORS["line"],
            radius=20,
            inset=9,
        )
        surface.pack(fill="both", expand=True)
        frame = surface.content

        titlebar = tk.Frame(frame, bg=COLORS["surface"], height=48, cursor="fleur")
        titlebar.pack(fill="x")
        titlebar.pack_propagate(False)
        brand = PillLabel(
            titlebar,
            text="译",
            width=34,
            height=30,
            fill=COLORS["secondary_soft"],
            foreground=COLORS["secondary"],
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        brand.pack(side="left", padx=(14, 9), pady=9)
        self.title_label = tk.Label(
            titlebar,
            text="旁译",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.title_label.pack(side="left")
        close = FlatButton(
            titlebar,
            "×",
            self.withdraw,
            width=30,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            hover=COLORS["surface_alt"],
            pady=4,
        )
        close.pack(side="right", padx=(4, 8), pady=7)
        self.status_label = tk.Label(
            titlebar,
            text="",
            bg=COLORS["surface"],
            fg=COLORS["primary"],
            font=("Microsoft YaHei UI", 8),
        )
        self.status_label.pack(side="right", padx=4)
        for widget in (titlebar, self.title_label, brand):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<ButtonRelease-1>", self._end_drag)

        meta = tk.Frame(frame, bg=COLORS["surface"])
        meta.pack(fill="x", padx=16, pady=(0, 10))
        self.language_label = PillLabel(
            meta,
            text="自动检测  →  中文",
            width=124,
            height=26,
            fill=COLORS["primary_soft"],
            foreground=COLORS["primary"],
            font=("Microsoft YaHei UI", 8),
        )
        self.language_label.pack(side="left")

        body = tk.Frame(frame, bg=COLORS["surface"])
        body.pack(fill="both", expand=True, padx=16)
        tk.Label(
            body,
            text="原文",
            bg=COLORS["surface"],
            fg=COLORS["subtle"],
            font=("Microsoft YaHei UI", 8, "bold"),
        ).pack(anchor="w", pady=(0, 5))
        source_panel = RoundedPanel(
            body,
            fill=COLORS["surface_alt"],
            border=COLORS["line"],
            radius=13,
            inset=7,
            height=102,
        )
        source_panel.pack(fill="x")
        self.source = tk.Text(
            source_panel.content,
            height=4,
            wrap="word",
            relief="flat",
            bg=COLORS["surface_alt"],
            fg=COLORS["muted"],
            padx=5,
            pady=3,
            font=("Microsoft YaHei UI", 9),
            cursor="arrow",
        )
        self.source.pack(fill="both", expand=True)
        self.source.configure(state="disabled")
        tk.Label(
            body,
            text="译文",
            bg=COLORS["surface"],
            fg=COLORS["subtle"],
            font=("Microsoft YaHei UI", 8, "bold"),
        ).pack(anchor="w", pady=(12, 5))
        self.result = tk.Text(
            body,
            height=5,
            wrap="word",
            relief="flat",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            padx=1,
            pady=1,
            font=("Microsoft YaHei UI", 11),
            cursor="arrow",
        )
        self.result.pack(fill="both", expand=True)
        self.result.configure(state="disabled")

        footer = tk.Frame(frame, bg=COLORS["surface"], height=48)
        self.footer = footer
        footer.pack(fill="x", side="bottom", before=body, padx=16, pady=(8, 10))
        FlatButton(
            footer,
            "复制",
            self.copy_result,
            width=72,
            bg=COLORS["primary_soft"],
            fg=COLORS["primary"],
            hover="#DDEAFF",
        ).pack(side="left")
        FlatButton(
            footer,
            "重试",
            self.retry,
            width=68,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            hover=COLORS["surface_alt"],
        ).pack(side="left", padx=5)
        size_grip = tk.Label(footer, text="◢", bg=COLORS["surface"], fg=COLORS["muted"], cursor="size_nw_se", font=("Segoe UI Symbol", 10))
        size_grip.pack(side="right", anchor="se")
        size_grip.bind("<ButtonPress-1>", self._start_resize)
        size_grip.bind("<B1-Motion>", self._resize)
        size_grip.bind("<ButtonRelease-1>", self._end_resize)

    def show_loading(self, source_text: str = "") -> None:
        self._translation = None
        self._set_text(self.source, source_text or "正在读取内容…")
        self._set_text(self.result, "正在翻译…")
        self.status_label.configure(text="处理中", fg=COLORS["primary"])
        self.title_label.configure(text="旁译")
        self._show_at_preferred_position()

    def show_translation(self, translation: Translation) -> None:
        self._translation = translation
        self._set_text(self.source, translation.source_text)
        self._set_text(self.result, translation.translated_text)
        source = LANGUAGE_LABELS.get(translation.source_language, translation.source_language)
        target = LANGUAGE_LABELS.get(translation.target_language, translation.target_language)
        self.language_label.configure(text=f"{source}  →  {target}")
        self.status_label.configure(text="翻译完成", fg=COLORS["success"])
        self.title_label.configure(text="旁译")
        self._show_at_preferred_position(keep_current=True)

    def show_error(self, message: str) -> None:
        self._translation = None
        self._set_text(self.result, message)
        self.status_label.configure(text="未完成", fg=COLORS["danger"])
        self.title_label.configure(text="需要处理")
        self._show_at_preferred_position(keep_current=True)

    def copy_result(self) -> None:
        if self._translation:
            set_clipboard_text(self._translation.translated_text)
            self.status_label.configure(text="已复制", fg=COLORS["success"])

    def retry(self) -> None:
        if self._translation:
            self.app.translate_text(self._translation.source_text)

    def _show_at_preferred_position(self, keep_current: bool = False) -> None:
        config = self.app.config
        width = max(360, config.popup_width)
        height = max(400, config.popup_height)
        self.update_idletasks()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        if keep_current and self.state() != "withdrawn":
            x, y = self.winfo_x(), self.winfo_y()
        elif config.popup_position == "fixed" and (config.popup_x or config.popup_y):
            x, y = config.popup_x, config.popup_y
        else:
            cursor_x, cursor_y = cursor_position()
            gap = 18
            x = cursor_x + gap
            y = cursor_y + gap
            if x + width > screen_width - 12:
                x = cursor_x - width - gap
            if y + height > screen_height - 48:
                y = max(12, cursor_y - height - gap)
        x = max(8, min(x, screen_width - width - 8))
        y = max(8, min(y, screen_height - height - 48))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.attributes("-topmost", self.app.config.always_on_top)
        self.deiconify()
        self.lift()

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_origin = (event.x_root, event.y_root, self.winfo_x(), self.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        if not self._drag_origin:
            return
        start_x, start_y, window_x, window_y = self._drag_origin
        self.geometry(f"+{window_x + event.x_root - start_x}+{window_y + event.y_root - start_y}")

    def _end_drag(self, _event: tk.Event) -> None:
        self._drag_origin = None
        self.app.config.popup_position = "fixed"
        self.app.config.popup_x = self.winfo_x()
        self.app.config.popup_y = self.winfo_y()
        save_config(self.app.config)
        self.app.sync_position_control()

    def _start_resize(self, event: tk.Event) -> None:
        self._drag_origin = (event.x_root, event.y_root, self.winfo_width(), self.winfo_height())

    def _resize(self, event: tk.Event) -> None:
        if not self._drag_origin:
            return
        start_x, start_y, width, height = self._drag_origin
        new_width = max(360, width + event.x_root - start_x)
        new_height = max(400, height + event.y_root - start_y)
        self.geometry(f"{new_width}x{new_height}")

    def _end_resize(self, _event: tk.Event) -> None:
        self._drag_origin = None
        self.app.config.popup_width = self.winfo_width()
        self.app.config.popup_height = self.winfo_height()
        save_config(self.app.config)


class FlatButton(RoundedButton):
    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command,
        width: int = 110,
        bg: str = COLORS["primary"],
        fg: str = "white",
        hover: str = COLORS["primary_hover"],
        pady: int = 7,
    ) -> None:
        super().__init__(
            master,
            text,
            command,
            width=max(34, width),
            height=max(34, pady * 2 + 22),
            fill=bg,
            foreground=fg,
            hover=hover,
            radius=12,
        )


class SideTranslateApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = load_config()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.hotkeys = GlobalHotkeys(lambda action: self.events.put(("hotkey", action)))
        self.mouse_selection = MouseSelectionWatcher(
            lambda: self.events.put(("mouse_selection", None))
        )
        self._busy = False
        self._build_window()
        self.popup = ResultPopup(self)
        self._load_vars()
        self._register_hotkeys(show_error=False)
        self._configure_mouse_selection(show_error=False)
        self.root.after(80, self._process_events)
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

    def _build_window(self) -> None:
        self.root.title("旁译 - 百度翻译桌面助手")
        self.root.geometry("860x680")
        self.root.minsize(800, 680)
        self.root.configure(bg=COLORS["bg"])

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "TEntry",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
            lightcolor=COLORS["line"],
            darkcolor=COLORS["line"],
            padding=8,
        )
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
            arrowcolor=COLORS["muted"],
            padding=7,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", COLORS["surface"])],
            selectbackground=[("readonly", COLORS["surface"])],
            selectforeground=[("readonly", COLORS["text"])],
        )
        style.configure(
            "TCheckbutton",
            background=COLORS["surface"],
            foreground=COLORS["text"],
            font=("Microsoft YaHei UI", 9),
            padding=2,
        )
        style.map("TCheckbutton", background=[("active", COLORS["surface"])])
        header_panel = RoundedPanel(
            self.root,
            fill=COLORS["surface"],
            border=COLORS["line"],
            radius=20,
            inset=8,
            height=76,
        )
        header_panel.pack(fill="x", padx=18, pady=(16, 8))
        header = header_panel.content
        mark = PillLabel(
            header,
            text="译",
            width=44,
            height=44,
            fill=COLORS["primary"],
            foreground="white",
            font=("Microsoft YaHei UI", 15, "bold"),
        )
        mark.pack(side="left", padx=(8, 11), pady=8)
        titles = tk.Frame(header, bg=COLORS["surface"])
        titles.pack(side="left", pady=8)
        tk.Label(
            titles,
            text="旁译",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=("Microsoft YaHei UI", 15, "bold"),
        ).pack(anchor="w")
        tk.Label(
            titles,
            text="Baidu Translate",
            bg=COLORS["surface"],
            fg=COLORS["subtle"],
            font=("Segoe UI", 8),
        ).pack(anchor="w")
        self.header_status = PillLabel(
            header,
            text="●  服务就绪",
            width=116,
            height=30,
            fill=COLORS["success_soft"],
            foreground=COLORS["success"],
            font=("Microsoft YaHei UI", 8),
        )
        self.header_status.pack(side="right", padx=8, pady=14)

        container = tk.Frame(self.root, bg=COLORS["bg"])
        container.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        tab_bar = tk.Frame(container, bg=COLORS["bg"], height=42)
        tab_bar.pack(fill="x", pady=(0, 8))
        self.quick_tab_button = RoundedButton(
            tab_bar,
            "快速翻译",
            lambda: self._show_view("quick"),
            width=108,
            height=40,
            fill=COLORS["primary"],
            foreground="white",
            hover=COLORS["primary_hover"],
            radius=14,
        )
        self.quick_tab_button.pack(side="left")
        self.settings_tab_button = RoundedButton(
            tab_bar,
            "设置",
            lambda: self._show_view("settings"),
            width=82,
            height=40,
            fill=COLORS["surface"],
            foreground=COLORS["muted"],
            hover=COLORS["primary_soft"],
            radius=14,
        )
        self.settings_tab_button.pack(side="left", padx=8)
        self.view_panel = RoundedPanel(
            container,
            fill=COLORS["surface"],
            border=COLORS["line"],
            radius=22,
            inset=8,
        )
        self.view_panel.pack(fill="both", expand=True)
        self.quick_tab = tk.Frame(self.view_panel.content, bg=COLORS["surface"])
        self.settings_tab = tk.Frame(self.view_panel.content, bg=COLORS["surface"])
        self._build_quick_tab()
        self._build_settings_tab()
        self._active_view = "quick"
        self._show_view("quick")
        self.root.bind("<Control-Tab>", self._cycle_view)

    def _show_view(self, view: str) -> None:
        self.quick_tab.pack_forget()
        self.settings_tab.pack_forget()
        if view == "settings":
            self.settings_tab.pack(fill="both", expand=True)
            self.quick_tab_button.set_colors(
                COLORS["surface"], COLORS["muted"], COLORS["primary_soft"]
            )
            self.settings_tab_button.set_colors(
                COLORS["primary"], "white", COLORS["primary_hover"]
            )
        else:
            self.quick_tab.pack(fill="both", expand=True)
            self.quick_tab_button.set_colors(
                COLORS["primary"], "white", COLORS["primary_hover"]
            )
            self.settings_tab_button.set_colors(
                COLORS["surface"], COLORS["muted"], COLORS["primary_soft"]
            )
        self._active_view = view

    def _cycle_view(self, _event: tk.Event) -> str:
        self._show_view("settings" if self._active_view == "quick" else "quick")
        return "break"

    def _build_quick_tab(self) -> None:
        tab = self.quick_tab
        content = tk.Frame(tab, bg=COLORS["surface"])
        content.pack(fill="both", expand=True, padx=26, pady=22)

        input_header = tk.Frame(content, bg=COLORS["surface"])
        input_header.pack(fill="x")
        tk.Label(
            input_header,
            text="输入文本",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(side="left")
        self.character_count = PillLabel(
            input_header,
            text="0 字符",
            width=72,
            height=25,
            fill=COLORS["yellow_soft"],
            foreground=COLORS["muted"],
            font=("Microsoft YaHei UI", 8),
        )
        self.character_count.pack(side="right")

        input_frame = RoundedPanel(
            content,
            fill=COLORS["surface_alt"],
            border=COLORS["line"],
            radius=18,
            inset=10,
        )
        input_frame.pack(fill="both", expand=True, pady=(9, 13))
        self.input_text = tk.Text(
            input_frame.content,
            height=8,
            wrap="word",
            relief="flat",
            bg=COLORS["surface_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["primary"],
            selectbackground="#CFE0FF",
            selectforeground=COLORS["text"],
            padx=14,
            pady=12,
            font=("Microsoft YaHei UI", 10),
            undo=True,
        )
        self.input_text.pack(fill="both", expand=True)
        self.input_text.bind("<KeyRelease>", self._update_character_count)
        self.input_text.bind("<Control-Return>", self._translate_from_shortcut)

        controls = tk.Frame(content, bg=COLORS["surface"])
        controls.pack(fill="x")
        self.source_var = tk.StringVar(value="自动检测")
        self.target_var = tk.StringVar(value="中文")
        self.source_combo = RoundedSelect(
            controls,
            self.source_var,
            list(LANGUAGES.keys()),
            width=126,
        )
        self.source_combo.pack(side="left")
        FlatButton(
            controls,
            "⇄",
            self.swap_languages,
            width=34,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            hover=COLORS["surface_alt"],
            pady=5,
        ).pack(side="left", padx=7)
        target_values = [label for label in LANGUAGES if label != "自动检测"]
        self.target_combo = RoundedSelect(
            controls,
            self.target_var,
            target_values,
            width=126,
        )
        self.target_combo.pack(side="left")
        self.translate_button = FlatButton(controls, "翻译", self.translate_input, width=96)
        self.translate_button.pack(side="right")

        divider = tk.Frame(content, bg=COLORS["line"], height=1)
        divider.pack(fill="x", pady=(20, 17))
        action_header = tk.Frame(content, bg=COLORS["surface"])
        action_header.pack(fill="x")
        tk.Label(
            action_header,
            text="快捷入口",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(side="left")
        self.auto_selection_status = PillLabel(
            action_header,
            text="●  划词翻译已开启",
            width=138,
            height=25,
            fill=COLORS["success_soft"],
            foreground=COLORS["success"],
            font=("Microsoft YaHei UI", 8),
        )
        self.auto_selection_status.pack(side="right")
        actions = tk.Frame(content, bg=COLORS["surface"])
        actions.pack(fill="x", pady=(10, 0))
        self.text_action = self._action_card(
            actions,
            "T",
            "选中文本",
            "Ctrl+Alt+T",
            self.capture_selection,
            icon_fill=COLORS["secondary_soft"],
            icon_color=COLORS["secondary"],
        )
        self.text_action.pack(side="left", fill="both", expand=True, padx=(0, 7))
        self.screen_action = self._action_card(
            actions,
            "▣",
            "截图翻译",
            "Ctrl+Alt+S",
            self.capture_screenshot,
            icon_fill=COLORS["accent_soft"],
            icon_color=COLORS["accent"],
        )
        self.screen_action.pack(side="left", fill="both", expand=True, padx=(7, 0))

    def _action_card(
        self,
        master: tk.Misc,
        icon: str,
        title: str,
        hotkey: str,
        command,
        *,
        icon_fill: str,
        icon_color: str,
    ) -> ActionCard:
        return ActionCard(
            master,
            icon,
            title,
            hotkey,
            command,
            icon_fill=icon_fill,
            icon_color=icon_color,
        )

    def _build_settings_tab(self) -> None:
        body = tk.Frame(self.settings_tab, bg=COLORS["surface"])
        body.pack(fill="both", expand=True, padx=26, pady=(16, 14))

        heading = tk.Frame(body, bg=COLORS["surface"])
        heading.pack(fill="x", pady=(0, 10))
        tk.Label(
            heading,
            text="应用设置",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(side="left")
        tk.Label(
            heading,
            text="凭据使用 Windows DPAPI 加密保存",
            bg=COLORS["surface"],
            fg=COLORS["subtle"],
            font=("Microsoft YaHei UI", 8),
        ).pack(side="right")

        columns = tk.Frame(body, bg=COLORS["surface"])
        columns.pack(fill="both", expand=True)
        columns.grid_columnconfigure(0, weight=1, uniform="settings")
        columns.grid_columnconfigure(2, weight=1, uniform="settings")
        columns.grid_rowconfigure(0, weight=1)
        left = tk.Frame(columns, bg=COLORS["surface"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 26))
        tk.Frame(columns, bg=COLORS["line"], width=1).grid(row=0, column=1, sticky="ns")
        right = tk.Frame(columns, bg=COLORS["surface"])
        right.grid(row=0, column=2, sticky="nsew", padx=(26, 0))

        self._settings_heading(left, "百度翻译", "通用文本翻译 API")
        self.app_id_var = tk.StringVar()
        self.secret_var = tk.StringVar()
        self._field(left, "App ID", self.app_id_var)
        self._field(left, "密钥", self.secret_var, secret=True)

        tk.Frame(left, bg=COLORS["line"], height=1).pack(fill="x", pady=(8, 10))
        self._settings_heading(left, "百度 OCR", "截图文字识别凭据")
        self.ocr_key_var = tk.StringVar()
        self.ocr_secret_var = tk.StringVar()
        self._field(left, "API Key", self.ocr_key_var)
        self._field(left, "Secret Key", self.ocr_secret_var, secret=True)

        self._settings_heading(right, "快捷键", "全局操作")
        hotkey_row = tk.Frame(right, bg=COLORS["surface"])
        self.hotkey_row = hotkey_row
        hotkey_row.pack(fill="x", pady=(2, 10))
        hotkey_row.grid_columnconfigure(0, weight=1, uniform="hotkeys")
        hotkey_row.grid_columnconfigure(1, weight=1, uniform="hotkeys")
        hotkey_row.grid_columnconfigure(2, weight=1, uniform="hotkeys")
        self.text_hotkey_var = tk.StringVar()
        self.screenshot_hotkey_var = tk.StringVar()
        self.auto_selection_hotkey_var = tk.StringVar()
        self._compact_field(hotkey_row, "选中文本", self.text_hotkey_var).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        self._compact_field(hotkey_row, "截图翻译", self.screenshot_hotkey_var).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        self._compact_field(hotkey_row, "划词开关", self.auto_selection_hotkey_var).grid(
            row=0, column=2, sticky="ew", padx=(6, 0)
        )

        self._settings_heading(right, "浮窗", "显示与交互")
        option_row = tk.Frame(right, bg=COLORS["surface"])
        option_row.pack(fill="x", pady=(3, 10))
        tk.Label(
            option_row,
            text="默认位置",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Microsoft YaHei UI", 8),
        ).pack(side="left")
        self.position_var = tk.StringVar(value="跟随鼠标")
        RoundedSelect(
            option_row,
            self.position_var,
            ["跟随鼠标", "固定位置"],
            width=126,
        ).pack(side="right")
        self.topmost_var = tk.BooleanVar(value=True)
        self.auto_selection_var = tk.BooleanVar(value=True)
        self._toggle_row(right, "浮窗保持置顶", self.topmost_var)
        self._toggle_row(right, "划词后自动翻译", self.auto_selection_var)

        tk.Frame(right, bg=COLORS["line"], height=1).pack(fill="x", pady=(9, 10))
        self._settings_heading(right, "诊断日志", "性能与错误记录")
        log_panel = RoundedPanel(
            right,
            fill=COLORS["surface_alt"],
            border=COLORS["line"],
            radius=13,
            inset=5,
            height=48,
        )
        log_panel.pack(fill="x", pady=(3, 0))
        log_row = log_panel.content
        tk.Label(
            log_row,
            text="app.log",
            bg=COLORS["surface_alt"],
            fg=COLORS["muted"],
            font=("Consolas", 8),
        ).pack(side="left", padx=11)
        FlatButton(
            log_row,
            "打开目录",
            self.open_log_directory,
            width=82,
            bg=COLORS["surface_alt"],
            fg=COLORS["primary"],
            hover=COLORS["primary_soft"],
            pady=4,
        ).pack(side="right", padx=6, pady=6)

        footer = tk.Frame(body, bg=COLORS["surface"])
        footer.pack(fill="x", pady=(9, 0))
        tk.Frame(footer, bg=COLORS["line"], height=1).pack(fill="x", pady=(0, 9))
        self.settings_feedback = tk.Label(
            footer,
            text="",
            bg=COLORS["surface"],
            fg=COLORS["success"],
            font=("Microsoft YaHei UI", 8),
        )
        self.settings_feedback.pack(side="left")
        FlatButton(footer, "保存设置", self.save_settings, width=104).pack(side="right")

    def _settings_heading(self, master: tk.Misc, title: str, detail: str) -> None:
        row = tk.Frame(master, bg=COLORS["surface"])
        row.pack(fill="x", pady=(0, 6))
        tk.Label(
            row,
            text=title,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")
        tk.Label(
            row,
            text=detail,
            bg=COLORS["surface"],
            fg=COLORS["subtle"],
            font=("Microsoft YaHei UI", 8),
        ).pack(side="right")

    def _field(
        self,
        master: tk.Misc,
        label: str,
        variable: tk.StringVar,
        secret: bool = False,
    ) -> None:
        row = tk.Frame(master, bg=COLORS["surface"])
        row.pack(fill="x", pady=(0, 6))
        tk.Label(
            row,
            text=label,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(0, 2))
        RoundedEntry(row, variable, secret=secret).pack(fill="x")

    def _compact_field(self, master: tk.Misc, label: str, variable: tk.StringVar) -> tk.Frame:
        frame = tk.Frame(master, bg=COLORS["surface"])
        tk.Label(
            frame,
            text=label,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(0, 2))
        RoundedEntry(frame, variable).pack(fill="x")
        return frame

    def _toggle_row(
        self,
        master: tk.Misc,
        label: str,
        variable: tk.BooleanVar,
    ) -> None:
        row = tk.Frame(master, bg=COLORS["surface"], height=34)
        row.pack(fill="x", pady=2)
        row.pack_propagate(False)
        tk.Label(
            row,
            text=label,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", pady=5)
        ToggleSwitch(row, variable).pack(side="right", pady=4)

    def _load_vars(self) -> None:
        self.app_id_var.set(self.config.app_id)
        self.secret_var.set(self.config.secret_key)
        self.ocr_key_var.set(self.config.ocr_api_key)
        self.ocr_secret_var.set(self.config.ocr_secret_key)
        self.text_hotkey_var.set(self.config.text_hotkey)
        self.screenshot_hotkey_var.set(self.config.screenshot_hotkey)
        self.auto_selection_hotkey_var.set(self.config.auto_selection_hotkey)
        self.source_var.set(LANGUAGE_LABELS.get(self.config.source_language, "自动检测"))
        self.target_var.set(LANGUAGE_LABELS.get(self.config.target_language, "中文"))
        self.position_var.set("固定位置" if self.config.popup_position == "fixed" else "跟随鼠标")
        self.topmost_var.set(self.config.always_on_top)
        self.auto_selection_var.set(self.config.auto_selection_enabled)
        self._update_hotkey_labels()
        self._update_auto_selection_status()

    def save_settings(self) -> None:
        new_config = replace(
            self.config,
            app_id=self.app_id_var.get().strip(),
            secret_key=self.secret_var.get().strip(),
            ocr_api_key=self.ocr_key_var.get().strip(),
            ocr_secret_key=self.ocr_secret_var.get().strip(),
            source_language=LANGUAGES.get(self.source_var.get(), "auto"),
            target_language=LANGUAGES.get(self.target_var.get(), "zh"),
            text_hotkey=self.text_hotkey_var.get().strip(),
            screenshot_hotkey=self.screenshot_hotkey_var.get().strip(),
            auto_selection_hotkey=self.auto_selection_hotkey_var.get().strip(),
            popup_position="fixed" if self.position_var.get() == "固定位置" else "cursor",
            always_on_top=self.topmost_var.get(),
            auto_selection_enabled=self.auto_selection_var.get(),
        )
        old_config = self.config
        self.config = new_config
        try:
            self._register_hotkeys(show_error=True)
            self._configure_mouse_selection(show_error=True)
            save_config(self.config)
        except (HotkeyError, MouseHookError, OSError) as exc:
            self.config = old_config
            self._register_hotkeys(show_error=False)
            self._configure_mouse_selection(show_error=False)
            messagebox.showerror("设置未保存", str(exc), parent=self.root)
            return
        self._update_hotkey_labels()
        self._update_auto_selection_status()
        self._set_header_status("设置已保存", "success")
        self.settings_feedback.configure(text="设置已保存并生效")
        self.root.after(2600, lambda: self.settings_feedback.configure(text=""))

    def sync_position_control(self) -> None:
        self.position_var.set("固定位置")

    def translate_input(self) -> None:
        text = self.input_text.get("1.0", "end").strip()
        self.translate_text(text)

    def _translate_from_shortcut(self, _event: tk.Event) -> str:
        self.translate_input()
        return "break"

    def _update_character_count(self, _event: tk.Event | None = None) -> None:
        characters = len(self.input_text.get("1.0", "end-1c"))
        self.character_count.configure(text=f"{characters} 字符")

    def swap_languages(self) -> None:
        source = self.source_var.get()
        target = self.target_var.get()
        if source == "自动检测":
            self.source_var.set(target)
            self.target_var.set("英语" if target == "中文" else "中文")
        else:
            self.source_var.set(target)
            self.target_var.set(source)

    def translate_text(self, text: str) -> None:
        if self._busy:
            return
        if not text.strip():
            self.popup.show_error("没有可翻译的文本，请先选中内容或在主窗口输入文字。")
            self._set_header_status("等待输入", "warning")
            return
        self._busy = True
        self._set_busy_ui(True)
        self._set_header_status("正在翻译", "primary")
        logger.info("operation.queued kind=manual characters=%d", len(text.strip()))
        self.popup.show_loading(text)
        config = self._current_config()
        threading.Thread(
            target=self._translate_worker,
            args=(config, text),
            name="manual-translate",
            daemon=True,
        ).start()

    def capture_selection(self, automatic: bool = False) -> None:
        kind = "selection-auto" if automatic else "selection"
        if self._busy:
            logger.info("operation.ignored kind=%s reason=busy", kind)
            return
        self._busy = True
        self._set_busy_ui(True)
        self._set_header_status("正在读取选区", "primary")
        logger.info("operation.queued kind=%s", kind)
        threading.Thread(
            target=self._selection_worker,
            args=(self._current_config(), kind, automatic),
            name=f"{kind}-translate",
            daemon=True,
        ).start()

    def capture_screenshot(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._set_busy_ui(True)
        self._set_header_status("等待截图", "primary")
        logger.info("operation.queued kind=screenshot")
        self.root.iconify()
        sequence = clipboard_sequence_number()
        self.popup.withdraw()
        try:
            launch_screen_clip()
        except OSError as exc:
            self._busy = False
            self._set_busy_ui(False)
            self._set_header_status("截图不可用", "danger")
            self.popup.show_error(f"无法启动 Windows 截图工具：{exc}")
            return
        threading.Thread(
            target=self._screenshot_worker,
            args=(self._current_config(), sequence),
            name="screenshot-translate",
            daemon=True,
        ).start()

    def _translate_worker(self, config: AppConfig, text: str) -> None:
        started = time.perf_counter()
        try:
            result = self._client(config).translate(text, config.source_language, config.target_language)
            logger.info("operation.complete kind=manual elapsed_ms=%.1f", self._elapsed_ms(started))
            self.events.put(("translation", result))
        except Exception as exc:
            logger.exception("operation.failed kind=manual elapsed_ms=%.1f", self._elapsed_ms(started))
            self.events.put(("error", self._friendly_error(exc)))

    def _selection_worker(self, config: AppConfig, kind: str, automatic: bool) -> None:
        started = time.perf_counter()
        try:
            if automatic:
                time.sleep(0.06)
            capture_started = time.perf_counter()
            text = copy_selected_text()
            logger.info(
                "selection.capture.complete kind=%s characters=%d elapsed_ms=%.1f",
                kind,
                len(text),
                self._elapsed_ms(capture_started),
            )
            if not text and automatic:
                logger.info("operation.cancelled kind=%s reason=no_text_selection", kind)
                self.events.put(("operation_cancelled", None))
                return
            self.events.put(("loading_text", text))
            result = self._client(config).translate(text, config.source_language, config.target_language)
            logger.info("operation.complete kind=%s elapsed_ms=%.1f", kind, self._elapsed_ms(started))
            self.events.put(("translation", result))
        except Exception as exc:
            logger.exception("operation.failed kind=%s elapsed_ms=%.1f", kind, self._elapsed_ms(started))
            self.events.put(("error", self._friendly_error(exc)))

    def _screenshot_worker(self, config: AppConfig, sequence: int) -> None:
        started = time.perf_counter()
        try:
            capture_started = time.perf_counter()
            image = wait_for_clipboard_image(sequence)
            logger.info(
                "screenshot.capture.complete image_bytes=%d elapsed_ms=%.1f",
                len(image),
                self._elapsed_ms(capture_started),
            )
            self.events.put(("loading_text", "正在识别截图中的文字…"))
            result = self._client(config).recognize_and_translate(image, config.source_language, config.target_language)
            logger.info("operation.complete kind=screenshot elapsed_ms=%.1f", self._elapsed_ms(started))
            self.events.put(("translation", result))
        except Exception as exc:
            logger.exception("operation.failed kind=screenshot elapsed_ms=%.1f", self._elapsed_ms(started))
            self.events.put(("error", self._friendly_error(exc)))

    def open_log_directory(self) -> None:
        try:
            os.startfile(LOG_DIR)
        except OSError as exc:
            messagebox.showerror("无法打开日志目录", str(exc), parent=self.root)

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "hotkey":
                    if payload == "selection":
                        self.capture_selection()
                    elif payload == "screenshot":
                        self.capture_screenshot()
                    elif payload == "toggle_auto_selection":
                        self.toggle_auto_selection()
                elif event == "mouse_selection":
                    self.capture_selection(automatic=True)
                elif event == "loading_text":
                    self.popup.show_loading(str(payload))
                elif event == "translation":
                    self._busy = False
                    self._set_busy_ui(False)
                    self._set_header_status("服务就绪", "success")
                    self.popup.show_translation(payload)  # type: ignore[arg-type]
                elif event == "error":
                    self._busy = False
                    self._set_busy_ui(False)
                    self._set_header_status("请求失败", "danger")
                    self.popup.show_error(str(payload))
                elif event == "operation_cancelled":
                    self._busy = False
                    self._set_busy_ui(False)
                    self._set_header_status("服务就绪", "success")
        except queue.Empty:
            pass
        self.root.after(80, self._process_events)

    def _register_hotkeys(self, show_error: bool) -> None:
        try:
            self.hotkeys.start(
                {
                    "selection": self.config.text_hotkey,
                    "screenshot": self.config.screenshot_hotkey,
                    "toggle_auto_selection": self.config.auto_selection_hotkey,
                }
            )
            self._set_header_status("服务就绪", "success")
        except HotkeyError as exc:
            self._set_header_status("快捷键不可用", "warning")
            if show_error:
                raise

    def _configure_mouse_selection(self, show_error: bool) -> None:
        self.mouse_selection.stop()
        if not self.config.auto_selection_enabled:
            logger.info("mouse_selection.disabled")
            self._update_auto_selection_status()
            return
        try:
            self.mouse_selection.start()
            logger.info(
                "mouse_selection.enabled minimum_drag_pixels=%d",
                self.mouse_selection.minimum_distance,
            )
            self._update_auto_selection_status()
        except MouseHookError:
            logger.exception("mouse_selection.start_failed")
            if show_error:
                raise

    def _update_hotkey_labels(self) -> None:
        self.text_action.set_hotkey(self.config.text_hotkey)
        self.screen_action.set_hotkey(self.config.screenshot_hotkey)

    def toggle_auto_selection(self) -> None:
        previous = self.config.auto_selection_enabled
        desired = not previous
        self.config.auto_selection_enabled = desired
        self.auto_selection_var.set(desired)
        try:
            self._configure_mouse_selection(show_error=True)
            save_config(self.config)
        except (MouseHookError, OSError) as exc:
            self.config.auto_selection_enabled = previous
            self.auto_selection_var.set(previous)
            self._configure_mouse_selection(show_error=False)
            self._set_header_status("划词开关失败", "danger")
            self.popup.show_error(f"无法切换划词翻译：{exc}")
            logger.exception("mouse_selection.toggle_failed desired=%s", desired)
            return
        self._update_auto_selection_status()
        state_text = "划词翻译已开启" if desired else "划词翻译已关闭"
        self._set_header_status(state_text, "success" if desired else "primary")
        logger.info("mouse_selection.toggled source=hotkey enabled=%s", desired)

    def _update_auto_selection_status(self) -> None:
        if not hasattr(self, "auto_selection_status"):
            return
        enabled = self.config.auto_selection_enabled
        self.auto_selection_status.configure(
            text="●  划词翻译已开启" if enabled else "○  划词翻译已关闭",
            fg=COLORS["success"] if enabled else COLORS["subtle"],
            bg=COLORS["success_soft"] if enabled else COLORS["surface_alt"],
        )

    def _set_busy_ui(self, busy: bool) -> None:
        self.translate_button.set_enabled(not busy)
        self.text_action.set_enabled(not busy)
        self.screen_action.set_enabled(not busy)

    def _set_header_status(self, text: str, tone: str) -> None:
        palette = {
            "success": (COLORS["success_soft"], COLORS["success"]),
            "primary": (COLORS["primary_soft"], COLORS["primary"]),
            "warning": ("#FFF4E5", COLORS["warning"]),
            "danger": ("#FDECEC", COLORS["danger"]),
        }
        background, foreground = palette[tone]
        self.header_status.configure(
            text=f"●  {text}",
            bg=background,
            fg=foreground,
        )

    def _current_config(self) -> AppConfig:
        self.config.source_language = LANGUAGES.get(self.source_var.get(), "auto")
        self.config.target_language = LANGUAGES.get(self.target_var.get(), "zh")
        return replace(self.config)

    @staticmethod
    def _client(config: AppConfig) -> BaiduClient:
        return BaiduClient(config.app_id, config.secret_key, config.ocr_api_key, config.ocr_secret_key)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        if isinstance(exc, (BaiduError, TimeoutError, HotkeyError)):
            return str(exc)
        return f"操作未完成：{exc}"

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return (time.perf_counter() - started) * 1000

    def shutdown(self) -> None:
        self.mouse_selection.stop()
        self.hotkeys.stop()
        self.root.destroy()


def run() -> None:
    log_path = setup_logging()
    logger.info("application.start version=0.1.0 log_path=%s", log_path)
    set_dpi_awareness()
    root = tk.Tk()
    root.report_callback_exception = lambda exc_type, exc, trace: logger.error(
        "tk_callback.failed", exc_info=(exc_type, exc, trace)
    )
    app = SideTranslateApp(root)
    root.bind("<Control-q>", lambda _event: app.shutdown())
    root.mainloop()
