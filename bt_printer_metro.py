#!/usr/bin/env python3
"""
Bluetooth Thermal Printer GUI - Linux
Windows 8 "Metro" (Modern UI) edition.
Flat tiles, pictograms, light typography, dark / light theme.
Backend and printing logic are unchanged - the look was rebuilt and these
were added on top: live preview, templates + history library, progress
strip, toast notifications and dropped-connection detection.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import tkinter.font as tkfont
import threading, socket, subprocess, re, time, os, math, json, select

try:
    import asyncio
    from bleak import BleakClient
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False

try:
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageTk, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


BLE_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
BLE_CHAR_UUID    = "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"
BLE_PACKET_SIZE  = 20


# =====================================================================
# Metro palette + themes
# =====================================================================
# Classic Windows 8 tile colours (identical in both themes)
TILE = {
    "blue":    "#2d89ef",
    "green":   "#00a300",
    "purple":  "#603cba",
    "orange":  "#da532c",
    "teal":    "#00aba9",
    "crimson": "#b91d47",
    "red":     "#e51400",
}

TOAST_COLORS = {
    "info":    TILE["blue"],
    "success": TILE["green"],
    "warn":    TILE["orange"],
    "error":   TILE["crimson"],
}

THEMES = {
    "dark": {
        "bg": "#1f1f1f", "bg_alt": "#2a2a2a",
        "field": "#2e2e2e", "field_hi": "#383838",
        "btn": "#3c3c3c", "btn_hi": "#4d4d4d",
        "border": "#686868", "border_hi": "#a0a0a0",
        "text": "#ffffff", "text_dim": "#d4d4d4", "text_muted": "#9a9a9a",
        "accent": "#2d89ef", "accent_hi": "#4a9df5", "accent_lo": "#1b5fb0",
        "on_accent": "#ffffff",
        "green": "#4cc94c", "red": "#ff6a5c", "yellow": "#ffc40d",
        "mauve": "#b17ee8",
        "canvas": "#141414",
        "disabled_bg": "#2b2b2b", "disabled_fg": "#6c6c6c",
    },
    "light": {
        "bg": "#f4f4f4", "bg_alt": "#e6e6e6",
        "field": "#ffffff", "field_hi": "#f0f6ff",
        "btn": "#dcdcdc", "btn_hi": "#cdcdcd",
        "border": "#9d9d9d", "border_hi": "#5a5a5a",
        "text": "#1a1a1a", "text_dim": "#3c3c3c", "text_muted": "#767676",
        "accent": "#2d89ef", "accent_hi": "#1f78dd", "accent_lo": "#1650a0",
        "on_accent": "#ffffff",
        "green": "#00a300", "red": "#d11414", "yellow": "#c98a00",
        "mauve": "#7a2fc4",
        "canvas": "#dedede",
        "disabled_bg": "#e4e4e4", "disabled_fg": "#a8a8a8",
    },
}

C = dict(THEMES["dark"])

def set_theme(name):
    C.clear()
    C.update(THEMES[name])


def shade(color, f):
    """f > 1 lightens toward white, f < 1 darkens toward black."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    if f >= 1:
        k = f - 1
        r, g, b = (int(v + (255 - v) * k) for v in (r, g, b))
    else:
        r, g, b = (int(v * f) for v in (r, g, b))
    return "#%02x%02x%02x" % (r, g, b)


def themed(widget, **attrs):
    """Apply theme colors AND register for live theme switching."""
    widget._theme_attrs = attrs
    for k, v in attrs.items():
        try: widget.config(**{k: C[v]})
        except Exception: pass
    return widget


def retheme_tree(root):
    def _walk(w):
        attrs = getattr(w, "_theme_attrs", None)
        if attrs:
            for k, v in attrs.items():
                try: w.config(**{k: C[v]})
                except Exception: pass
        redraw = getattr(w, "redraw", None)
        if callable(redraw):
            try: redraw()
            except Exception: pass
        for c in w.winfo_children():
            _walk(c)
    _walk(root)


# ---------------------------------------------------------------------
# Typography (resolved at runtime - Segoe UI if present, else the
# closest open metric-compatible / humanist sans on the system)
# ---------------------------------------------------------------------
F_TITLE   = ("Sans", 30)
F_H2      = ("Sans", 18)
F_SUB     = ("Sans", 10)
F_LABEL   = ("Sans", 8)
F_BODY    = ("Sans", 10)
F_BODY_B  = ("Sans", 10, "bold")
F_MONO    = ("Monospace", 10)
F_LOG     = ("Monospace", 9)
F_TINY    = ("Sans", 9)
F_TILE    = ("Sans", 12)
F_TILE_S  = ("Sans", 10)


def init_fonts(root):
    global F_TITLE, F_H2, F_SUB, F_LABEL, F_BODY, F_BODY_B
    global F_MONO, F_LOG, F_TINY, F_TILE, F_TILE_S
    fams = {f.lower(): f for f in tkfont.families(root)}

    def pick(cands, fallback):
        for c in cands:
            if c.lower() in fams:
                return fams[c.lower()]
        return fallback

    base  = pick(["Segoe UI", "Selawik", "Open Sans", "Noto Sans", "Inter",
                  "Cantarell", "Ubuntu", "DejaVu Sans"], "Sans")
    light = pick(["Segoe UI Light", "Selawik Light", "Open Sans Light",
                  "Noto Sans Light", "Lato Light", "Roboto Light",
                  "Ubuntu Light", "Cantarell Light"], base)
    semi  = pick(["Segoe UI Semibold", "Selawik Semibold",
                  "Open Sans SemiBold", "Noto Sans SemiBold"], None)
    mono  = pick(["Cascadia Mono", "Cascadia Code", "Consolas",
                  "JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono"],
                 "Monospace")

    F_TITLE  = (light, 30)
    F_H2     = (light, 18)
    F_SUB    = (base, 10)
    F_LABEL  = (base, 8)
    F_BODY   = (base, 10)
    F_BODY_B = (semi, 10) if semi else (base, 10, "bold")
    F_MONO   = (mono, 10)
    F_LOG    = (mono, 9)
    F_TINY   = (base, 9)
    F_TILE   = (semi, 12) if semi else (base, 12, "bold")
    F_TILE_S = (semi, 10) if semi else (base, 10, "bold")


# =====================================================================
# Backend  (unchanged)
# =====================================================================
class ClassicPrinter:
    def __init__(self, mac, channel=1):
        self.mac, self.channel, self.sock = mac, channel, None
    def connect(self):
        if not hasattr(socket, "AF_BLUETOOTH"):
            raise RuntimeError("Python was not built with Bluetooth sockets.")
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                                   socket.BTPROTO_RFCOMM)
        self.sock.settimeout(15)
        self.sock.connect((self.mac, self.channel))
        self.sock.settimeout(5)
    def disconnect(self):
        if self.sock:
            try: self.sock.close()
            except Exception: pass
        self.sock = None
    def write(self, data):
        if not self.sock: raise RuntimeError("Not connected")
        self.sock.sendall(data)
    def is_connected(self): return self.sock is not None


class BLEPrinter:
    def __init__(self, mac):
        self.mac = mac
        self.client = None; self._loop = None; self._thread = None
        self._char_uuid = None
    def connect(self):
        if not BLEAK_AVAILABLE:
            raise RuntimeError("bleak not installed")
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        async def _do():
            self.client = BleakClient(self.mac, timeout=20.0)
            await self.client.connect()
            await self._find_characteristic()
        asyncio.run_coroutine_threadsafe(_do(), self._loop).result(timeout=30)
        if not self.client.is_connected:
            raise RuntimeError("Failed to connect")
    async def _find_characteristic(self):
        for svc in self.client.services:
            for c in svc.characteristics:
                if c.uuid.lower() == BLE_CHAR_UUID.lower():
                    self._char_uuid = c.uuid; return
        for svc in self.client.services:
            for c in svc.characteristics:
                if "write" in " ".join(c.properties).lower():
                    self._char_uuid = c.uuid; return
        raise RuntimeError("No writable BLE characteristic")
    def disconnect(self):
        if not self._loop: return
        try:
            if self.client and self.client.is_connected:
                async def _do(): await self.client.disconnect()
                asyncio.run_coroutine_threadsafe(_do(), self._loop).result(timeout=10)
        except Exception: pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
        except Exception: pass
        self.client = self._loop = self._thread = self._char_uuid = None
    def write(self, data):
        if not self.client or not self._loop:
            raise RuntimeError("Not connected")
        async def _do():
            if self._char_uuid is None:
                await self._find_characteristic()
            for i in range(0, len(data), BLE_PACKET_SIZE):
                await self.client.write_gatt_char(
                    self._char_uuid, data[i:i+BLE_PACKET_SIZE], response=False)
                await asyncio.sleep(0.02)
        asyncio.run_coroutine_threadsafe(_do(), self._loop).result(timeout=30)
    def is_connected(self):
        return self.client is not None and self.client.is_connected


def find_rfcomm_channel(mac):
    try:
        r = subprocess.run(["sdptool", "browse", mac],
                            capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            current = ""
            for line in r.stdout.split("\n"):
                if "Service Name:" in line: current = line
                if "Channel:" in line and current:
                    if any(k in current for k in ("SPP", "Serial", "Printer", "print")):
                        try: return int(line.split(":")[1].strip())
                        except Exception: pass
            for line in r.stdout.split("\n"):
                if "Channel:" in line:
                    try: return int(line.split(":")[1].strip())
                    except Exception: pass
    except Exception: pass
    return 1


# =====================================================================
# Metro pictograms (drawn with canvas lines - no icon fonts / emoji)
# =====================================================================
def draw_icon(cv, name, cx, cy, s, color, w=2, cut=None, tag="icon"):
    """Draw a thin-stroke Metro pictogram. s = half-size in pixels."""
    def line(*pts, **extra):
        opts = dict(fill=color, width=w, tags=tag, joinstyle="miter")
        opts.update(extra)
        cv.create_line(*pts, **opts)

    def rect(x1, y1, x2, y2):
        cv.create_rectangle(x1, y1, x2, y2, outline=color, width=w, tags=tag)

    if name == "printer":
        rect(cx - s * .55, cy - s, cx + s * .55, cy - s * .35)
        rect(cx - s, cy - s * .35, cx + s, cy + s * .45)
        rect(cx - s * .55, cy + s * .45, cx + s * .55, cy + s)
        cv.create_oval(cx + s * .5, cy - s * .12, cx + s * .72, cy + s * .1,
                       fill=color, outline=color, tags=tag)
    elif name == "doc":
        line(cx - s * .7, cy - s, cx + s * .2, cy - s, cx + s * .7, cy - s * .5,
             cx + s * .7, cy + s, cx - s * .7, cy + s, cx - s * .7, cy - s)
        line(cx + s * .2, cy - s, cx + s * .2, cy - s * .5, cx + s * .7, cy - s * .5)
        for k in (0.0, 0.35, 0.7):
            line(cx - s * .4, cy + s * k, cx + s * .4, cy + s * k)
    elif name == "image":
        rect(cx - s, cy - s * .75, cx + s, cy + s * .75)
        cv.create_oval(cx + s * .2, cy - s * .5, cx + s * .55, cy - s * .15,
                       outline=color, width=w, tags=tag)
        line(cx - s, cy + s * .5, cx - s * .35, cy - s * .05, cx + s * .05, cy + s * .35,
             cx + s * .4, cy + s * .1, cx + s, cy + s * .55)
    elif name == "hex":
        line(cx - s * .35, cy - s * .6, cx - s * .95, cy, cx - s * .35, cy + s * .6)
        line(cx + s * .35, cy - s * .6, cx + s * .95, cy, cx + s * .35, cy + s * .6)
        line(cx + s * .15, cy - s * .8, cx - s * .15, cy + s * .8)
    elif name == "up":
        line(cx, cy + s * .9, cx, cy - s * .9)
        line(cx - s * .6, cy - s * .3, cx, cy - s * .9, cx + s * .6, cy - s * .3)
    elif name == "down":
        line(cx, cy - s * .9, cx, cy + s * .9)
        line(cx - s * .6, cy + s * .3, cx, cy + s * .9, cx + s * .6, cy + s * .3)
    elif name == "sun":
        r = s * .42
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=w, tags=tag)
        for a in range(8):
            ang = a * math.pi / 4
            line(cx + math.cos(ang) * s * .68, cy + math.sin(ang) * s * .68,
                 cx + math.cos(ang) * s * .98, cy + math.sin(ang) * s * .98)
    elif name == "eye":
        line(cx - s, cy, cx - s * .5, cy - s * .5, cx, cy - s * .65, cx + s * .5, cy - s * .5,
             cx + s, cy, cx + s * .5, cy + s * .5, cx, cy + s * .65, cx - s * .5, cy + s * .5,
             cx - s, cy, smooth=True)
        r = s * .27
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=w, tags=tag)
    elif name == "list":
        for k in (-0.6, 0, 0.6):
            cv.create_rectangle(cx - s, cy + s * k - s * .1, cx - s * .78, cy + s * k + s * .1,
                                fill=color, outline=color, tags=tag)
            line(cx - s * .4, cy + s * k, cx + s, cy + s * k)
    elif name == "moon":
        r = s * .85
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline=color, tags=tag)
        cut = cut or "#000000"
        cv.create_oval(cx - r * .35, cy - r * 1.15, cx + r * 1.35, cy + r * .55,
                       fill=cut, outline=cut, tags=tag)


# =====================================================================
# Metro widgets
# =====================================================================
class MetroTile(tk.Canvas):
    """Flat coloured live tile with a pictogram. Shrinks slightly on press."""
    def __init__(self, parent, text, icon, color, command,
                 width=150, height=150, layout="v", bg_key="bg"):
        tk.Canvas.__init__(self, parent, width=width, height=height,
                           bd=0, highlightthickness=0, cursor="hand2")
        self._theme_attrs = {"bg": bg_key}
        self.config(bg=C[bg_key])
        self._tw, self._th = width, height
        self._text, self._icon, self._color = text, icon, color
        self._command, self._layout = command, layout
        self._hover = self._down = False
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, down=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(down=True))
        self.bind("<ButtonRelease-1>", self._on_release)
        self.redraw()

    def _set(self, **kw):
        if "hover" in kw: self._hover = kw["hover"]
        if "down" in kw: self._down = kw["down"]
        self.redraw()

    def _on_release(self, e):
        was = self._down
        self._set(down=False)
        if was and 0 <= e.x < self._tw and 0 <= e.y < self._th and self._command:
            self._command()

    def redraw(self):
        self.delete("all")
        w, h = self._tw, self._th
        ins = 4 if self._down else 0
        if self._down:   fill = shade(self._color, 0.86)
        elif self._hover: fill = shade(self._color, 1.10)
        else:            fill = self._color
        self.create_rectangle(ins, ins, w - ins, h - ins, fill=fill, outline="")
        if self._hover and not self._down:
            self.create_rectangle(1, 1, w - 1, h - 1,
                                  outline=shade(self._color, 1.45), width=2)
        k = (w - 2 * ins) / w
        if self._layout == "h":
            s = h * 0.20 * k
            draw_icon(self, self._icon, h / 2, h / 2, s, "#ffffff")
            self.create_text(h - 2, h / 2, text=self._text, anchor="w",
                             fill="#ffffff", font=F_TILE_S)
        else:
            s = min(w, h) * 0.145 * k
            draw_icon(self, self._icon, w / 2, h * 0.41, s, "#ffffff")
            self.create_text(12 + ins, h - 11 - ins, text=self._text, anchor="sw",
                             fill="#ffffff", font=F_TILE)


class IconButton(tk.Canvas):
    """Metro circular app-bar button with a pictogram."""
    def __init__(self, parent, icon, command=None, size=44, bg_key="bg"):
        tk.Canvas.__init__(self, parent, width=size, height=size, bd=0,
                           highlightthickness=0, cursor="hand2")
        self._theme_attrs = {"bg": bg_key}
        self._bg_key = bg_key
        self.config(bg=C[bg_key])
        self._icon, self._command, self._size = icon, command, size
        self._hover = self._down = False
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, down=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(down=True))
        self.bind("<ButtonRelease-1>", self._on_release)
        self.redraw()

    def _set(self, **kw):
        if "hover" in kw: self._hover = kw["hover"]
        if "down" in kw: self._down = kw["down"]
        self.redraw()

    def _on_release(self, e):
        was = self._down
        self._set(down=False)
        if was and self._command and 0 <= e.x < self._size and 0 <= e.y < self._size:
            self._command()

    def set_icon(self, name):
        self._icon = name
        self.redraw()

    def redraw(self):
        self.delete("all")
        s = self._size
        if self._down:    fill, fg = C["text"], C[self._bg_key]
        elif self._hover: fill, fg = C["btn"], C["text"]
        else:             fill, fg = "", C["text"]
        self.create_oval(2, 2, s - 2, s - 2, outline=C["text"], width=2, fill=fill)
        draw_icon(self, self._icon, s / 2, s / 2, s * 0.22, fg,
                  cut=fill or C[self._bg_key])


class MetroButton(tk.Label):
    """Flat rectangular button. kinds: primary, secondary, danger, seg, link."""
    def __init__(self, parent, text, command=None, kind="secondary",
                 padx=20, pady=8, font=None, bg_key="bg"):
        if font is None:
            font = F_BODY_B if kind in ("primary", "danger") else F_BODY
        tk.Label.__init__(self, parent, text=text, font=font, padx=padx, pady=pady,
                          bd=0, relief="flat", highlightthickness=2,
                          cursor="hand2", takefocus=0)
        self._command, self._kind, self._bg_key = command, kind, bg_key
        self._hover = self._down = self._disabled = self._selected = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._apply()

    # --- state handling (keeps the tk.Button-style API the app relies on)
    def configure(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        state = kw.pop("state", None)
        if kw:
            tk.Label.configure(self, **kw)
        if state is not None:
            self._disabled = (state == "disabled")
            self._apply()
    config = configure

    def set_kind(self, kind):
        self._kind = kind
        tk.Label.configure(self, font=F_BODY_B if kind in ("primary", "danger") else F_BODY)
        self._apply()

    def set_selected(self, flag):
        self._selected = bool(flag)
        self._apply()

    def redraw(self):
        self._apply()

    def _on_enter(self, e): self._hover = True; self._apply()
    def _on_leave(self, e): self._hover = False; self._down = False; self._apply()
    def _on_press(self, e):
        if self._disabled: return
        self._down = True; self._apply()
    def _on_release(self, e):
        was = self._down
        self._down = False
        self._apply()
        if (was and not self._disabled and self._command
                and 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()):
            self._command()

    def _apply(self):
        k, hov, dn = self._kind, self._hover, self._down
        if self._disabled:
            bg, fg, bd = C["disabled_bg"], C["disabled_fg"], C["disabled_bg"]
        elif k == "primary":
            bg = C["accent_lo"] if dn else (C["accent_hi"] if hov else C["accent"])
            fg, bd = C["on_accent"], bg
        elif k == "danger":
            base = TILE["red"]
            bg = shade(base, .8) if dn else (shade(base, 1.12) if hov else base)
            fg, bd = "#ffffff", bg
        elif k == "seg":
            if dn:
                bg, fg = C["accent_lo"], C["on_accent"]
            elif self._selected:
                bg, fg = (C["accent_hi"] if hov else C["accent"]), C["on_accent"]
            else:
                bg, fg = (C["btn_hi"] if hov else C["btn"]), C["text_dim"]
            bd = bg
        elif k == "link":
            bg = C[self._bg_key]
            fg = C["accent_lo"] if dn else (C["accent"] if hov else C["text_muted"])
            bd = bg
        else:  # secondary
            if dn:
                bg, fg, bd = C["text"], C["bg"], C["text"]
            elif hov:
                bg, fg, bd = C["btn_hi"], C["text"], C["border_hi"]
            else:
                bg, fg, bd = C["btn"], C["text"], C["btn"]
        tk.Label.configure(self, bg=bg, fg=fg, highlightbackground=bd,
                           cursor="arrow" if self._disabled else "hand2")


class MetroCheck(tk.Frame):
    """Square Metro checkbox bound to a BooleanVar."""
    def __init__(self, parent, text, var, bg_key="bg"):
        tk.Frame.__init__(self, parent, bd=0, highlightthickness=0, cursor="hand2")
        self._theme_attrs = {"bg": bg_key}
        self._bg_key, self._var, self._hover = bg_key, var, False
        self._box = tk.Canvas(self, width=22, height=22, bd=0,
                              highlightthickness=0, cursor="hand2")
        self._box.pack(side="left")
        self._lbl = tk.Label(self, text=text, font=F_BODY, bd=0, cursor="hand2")
        self._lbl.pack(side="left", padx=(8, 0))
        for w in (self, self._box, self._lbl):
            w.bind("<Button-1>", self._toggle)
            w.bind("<Enter>", lambda e: self._set_hover(True))
            w.bind("<Leave>", lambda e: self._set_hover(False))
        var.trace_add("write", lambda *a: self._safe_redraw())
        self.redraw()

    def _safe_redraw(self):
        try: self.redraw()
        except Exception: pass

    def _set_hover(self, flag):
        self._hover = flag; self.redraw()

    def _toggle(self, _e=None):
        self._var.set(not self._var.get())

    def redraw(self):
        bg = C[self._bg_key]
        self.config(bg=bg)
        self._lbl.config(bg=bg, fg=C["text"])
        b = self._box
        b.config(bg=bg)
        b.delete("all")
        if self._var.get():
            col = C["accent_hi"] if self._hover else C["accent"]
            b.create_rectangle(1, 1, 21, 21, fill=col, outline=col)
            b.create_line(6, 11, 10, 15, 16, 7, fill="#ffffff", width=2)
        else:
            b.create_rectangle(2, 2, 20, 20, fill=C["field"], width=2,
                               outline=C["border_hi"] if self._hover else C["border"])


class MetroSwitch(tk.Frame):
    """Windows 8 style toggle switch bound to a BooleanVar."""
    def __init__(self, parent, text, var, bg_key="bg"):
        tk.Frame.__init__(self, parent, bd=0, highlightthickness=0, cursor="hand2")
        self._theme_attrs = {"bg": bg_key}
        self._bg_key, self._var, self._hover = bg_key, var, False
        self._cv = tk.Canvas(self, width=46, height=22, bd=0,
                             highlightthickness=0, cursor="hand2")
        self._cv.pack(side="left")
        self._lbl = tk.Label(self, text=text, font=F_BODY, bd=0, cursor="hand2")
        self._lbl.pack(side="left", padx=(12, 0))
        for w in (self, self._cv, self._lbl):
            w.bind("<Button-1>", self._toggle)
            w.bind("<Enter>", lambda e: self._set_hover(True))
            w.bind("<Leave>", lambda e: self._set_hover(False))
        var.trace_add("write", lambda *a: self._safe_redraw())
        self.redraw()

    def _safe_redraw(self):
        try: self.redraw()
        except Exception: pass

    def _set_hover(self, flag):
        self._hover = flag; self.redraw()

    def _toggle(self, _e=None):
        self._var.set(not self._var.get())

    def redraw(self):
        bg = C[self._bg_key]
        self.config(bg=bg)
        self._lbl.config(bg=bg, fg=C["text"])
        cv = self._cv
        cv.config(bg=bg)
        cv.delete("all")
        if self._var.get():
            col = C["accent_hi"] if self._hover else C["accent"]
            cv.create_rectangle(1, 1, 45, 21, fill=col, outline=col)
            cv.create_rectangle(33, 5, 41, 17, fill="#ffffff", outline="")
        else:
            cv.create_rectangle(2, 2, 44, 20, fill="", width=2,
                                outline=C["border_hi"] if self._hover else C["border"])
            cv.create_rectangle(6, 6, 14, 16, fill=C["text"], outline="")


class MetroSlider(tk.Canvas):
    """Thin-track Metro slider with a block thumb and an inline value read-out."""
    PAD, VAL_W = 8, 48

    def __init__(self, parent, from_, to, resolution, variable,
                 command=None, width=240, bg_key="bg"):
        tk.Canvas.__init__(self, parent, width=width, height=30, bd=0,
                           highlightthickness=0, cursor="hand2")
        self._theme_attrs = {"bg": bg_key}
        self.config(bg=C[bg_key])
        self._lo, self._hi, self._res = from_, to, resolution
        self._var, self._command = variable, command
        self._active = False
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_mouse)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.redraw()

    def _geom(self):
        w = self.winfo_width()
        if w <= 1:
            w = int(self.cget("width"))
        return self.PAD, w - self.VAL_W - self.PAD, w

    def _on_press(self, e):
        self._active = True; self._on_mouse(e)

    def _on_release(self, e):
        self._active = False; self.redraw()

    def _on_mouse(self, e):
        x0, x1, _ = self._geom()
        frac = min(1.0, max(0.0, (e.x - x0) / max(1, (x1 - x0))))
        v = self._lo + frac * (self._hi - self._lo)
        v = round(round(v / self._res) * self._res, 4)
        v = min(self._hi, max(self._lo, v))
        self._var.set(v)
        self.redraw()
        if self._command:
            self._command(v)

    def redraw(self):
        self.delete("all")
        x0, x1, w = self._geom()
        cy = 15
        v = float(self._var.get())
        frac = (v - self._lo) / (self._hi - self._lo)
        tx = x0 + frac * (x1 - x0)
        self.create_rectangle(x0, cy - 2, x1, cy + 2, fill=C["border"], outline="")
        self.create_rectangle(x0, cy - 2, tx, cy + 2, fill=C["accent"], outline="")
        thumb = C["accent_hi"] if self._active else C["text"]
        self.create_rectangle(tx - 5, cy - 11, tx + 5, cy + 11, fill=thumb, outline="")
        self.create_text(w - 2, cy, text=f"{v:.2f}", anchor="e",
                         fill=C["text_dim"], font=F_TINY)


# ---------------------------------------------------------------------
# Form helpers
# ---------------------------------------------------------------------
def make_section(parent, title):
    f = themed(tk.Frame(parent), bg="bg")
    themed(tk.Label(f, text=title, font=F_H2, anchor="w"),
           fg="text", bg="bg").pack(anchor="w", pady=(0, 8))
    return f


def make_label(parent, text, bg="bg"):
    return themed(tk.Label(parent, text=text, font=F_LABEL, anchor="w"),
                  fg="text_muted", bg=bg)


def make_entry(parent, **kw):
    kw.setdefault("font", F_BODY)
    e = tk.Entry(parent, relief="flat", bd=0, highlightthickness=2, **kw)
    themed(e, bg="field", fg="text", insertbackground="text",
           selectbackground="accent", selectforeground="on_accent",
           highlightbackground="border", highlightcolor="accent")
    e.bind("<Enter>", lambda ev: e.config(highlightbackground=C["border_hi"]))
    e.bind("<Leave>", lambda ev: e.config(highlightbackground=C["border"]))
    return e


def make_textarea(parent, height=6, font=None, width=20, undo=True,
                  padx=12, pady=10):
    """Bordered text area with a thin Metro scrollbar. Returns (box, text, scrollbar)."""
    box = tk.Frame(parent, bd=0, highlightthickness=2)
    themed(box, bg="field", highlightbackground="border")
    text = tk.Text(box, height=height, width=width, relief="flat", bd=0,
                   font=font or F_MONO, padx=padx, pady=pady,
                   highlightthickness=0, wrap="word", undo=undo)
    themed(text, bg="field", fg="text", insertbackground="text",
           selectbackground="accent", selectforeground="on_accent")
    sb = ttk.Scrollbar(box, orient="vertical", style="Metro.Vertical.TScrollbar",
                       command=text.yview)
    text.config(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y", padx=(0, 2), pady=2)
    text.pack(side="left", fill="both", expand=True)
    text.bind("<FocusIn>", lambda e: box.config(highlightbackground=C["accent"]))
    text.bind("<FocusOut>", lambda e: box.config(highlightbackground=C["border"]))
    return box, text, sb


# =====================================================================
# Image editor
# =====================================================================
class ImageEditor(tk.Toplevel):
    PRINTER_WIDTH = 384

    def __init__(self, parent, path):
        super().__init__(parent)
        self.title("Image Editor")
        self.geometry("980x860")
        self.configure(bg=C["bg"])
        self.transient(parent); self.grab_set()

        self.original = Image.open(path).convert("L")
        self.crop_box = None
        self.drag_start = None
        self.drag_item = None
        self.scale = 1.0
        self.offset = (0, 0)
        self.result = None

        self._build()
        self.update_idletasks()
        self.after(150, self._refresh_preview)
        self.after(250, self._refresh_raster)

    def _build(self):
        body = themed(tk.Frame(self), bg="bg")
        body.pack(fill="both", expand=True, padx=36, pady=(26, 28))

        themed(tk.Label(body, text="image editor", font=F_H2, anchor="w"),
               fg="text", bg="bg").pack(anchor="w")
        themed(tk.Label(body, text="Drag on the image to crop  ·  tune brightness and contrast",
                        font=F_SUB, anchor="w"),
               fg="text_muted", bg="bg").pack(anchor="w", pady=(0, 12))

        # --- Canvas (image + crop overlay) ---
        outer_c = tk.Frame(body, bd=0, highlightthickness=2)
        themed(outer_c, bg="canvas", highlightbackground="border")
        outer_c.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(outer_c, bg=C["canvas"], highlightthickness=0,
                                cursor="crosshair", width=600, height=400)
        themed(self.canvas, bg="canvas")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_down)
        self.canvas.bind("<B1-Motion>", self._on_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_up)
        self.canvas.bind("<Configure>", lambda e: self._refresh_preview())

        # --- Controls ---
        ctrl = themed(tk.Frame(body), bg="bg")
        ctrl.pack(fill="x", pady=(16, 0))

        row1 = themed(tk.Frame(ctrl), bg="bg")
        row1.pack(fill="x")
        MetroButton(row1, "Reset crop", self._reset_crop, pady=6).pack(side="left", padx=(0, 8))
        MetroButton(row1, "Fit to width", self._fit_width, pady=6).pack(side="left", padx=(0, 8))
        self.crop_label = themed(tk.Label(row1, text="Crop: none", font=F_TINY),
                                  fg="text_muted", bg="bg")
        self.crop_label.pack(side="left", padx=12)

        self.dither_var = tk.StringVar(value="floyd")
        cb = ttk.Combobox(row1, textvariable=self.dither_var, width=11,
                          state="readonly", font=F_BODY,
                          values=["floyd", "threshold", "none"])
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_raster())
        make_label(row1, "DITHER").pack(side="right", padx=(0, 10))

        row2 = themed(tk.Frame(ctrl), bg="bg")
        row2.pack(fill="x", pady=(14, 0))

        colb = themed(tk.Frame(row2), bg="bg"); colb.pack(side="left", padx=(0, 36))
        make_label(colb, "BRIGHTNESS").pack(anchor="w")
        self.bright_var = tk.DoubleVar(value=1.0)
        self.bright_scale = MetroSlider(colb, 0.3, 2.0, 0.05, self.bright_var,
                                        command=lambda v: self._refresh_raster(), width=300)
        self.bright_scale.pack(anchor="w")

        colc = themed(tk.Frame(row2), bg="bg"); colc.pack(side="left")
        make_label(colc, "CONTRAST").pack(anchor="w")
        self.contrast_var = tk.DoubleVar(value=1.0)
        self.contrast_scale = MetroSlider(colc, 0.3, 2.0, 0.05, self.contrast_var,
                                          command=lambda v: self._refresh_raster(), width=300)
        self.contrast_scale.pack(anchor="w")

        # --- Raster preview ---
        prev = themed(tk.Frame(body), bg="bg")
        prev.pack(fill="x", pady=(16, 0))
        make_label(prev, "PRINT PREVIEW  (WHAT WILL COME OUT)").pack(anchor="w", pady=(0, 4))
        prev_box = tk.Frame(prev, bd=0, highlightthickness=2)
        themed(prev_box, bg="canvas", highlightbackground="border")
        prev_box.pack(fill="x")
        self.raster_canvas = tk.Canvas(prev_box, bg=C["canvas"], height=170,
                                       width=600, highlightthickness=0)
        themed(self.raster_canvas, bg="canvas")
        self.raster_canvas.pack(fill="x")

        # --- Actions ---
        actions = themed(tk.Frame(body), bg="bg")
        actions.pack(fill="x", pady=(18, 0))
        MetroButton(actions, "Print", self._accept, kind="primary",
                    padx=34).pack(side="right")
        MetroButton(actions, "Cancel", self.destroy).pack(side="right", padx=(0, 10))
        self.size_label = themed(tk.Label(actions, text="", font=F_TINY),
                                  fg="text_muted", bg="bg")
        self.size_label.pack(side="left")

    def _canvas_to_orig(self, cx, cy):
        ox, oy = self.offset
        return (cx - ox) / self.scale, (cy - oy) / self.scale

    def _on_down(self, e):
        self.drag_start = self._canvas_to_orig(e.x, e.y)
        if self.drag_item: self.canvas.delete(self.drag_item)
        self.drag_item = self.canvas.create_rectangle(
            e.x, e.y, e.x, e.y, outline=C["accent"], width=2, dash=(4, 2))

    def _on_move(self, e):
        if not self.drag_start: return
        ox, oy = self.offset
        x1 = ox + self.drag_start[0] * self.scale
        y1 = oy + self.drag_start[1] * self.scale
        self.canvas.coords(self.drag_item, x1, y1, e.x, e.y)

    def _on_up(self, e):
        if not self.drag_start: return
        end_x, end_y = self._canvas_to_orig(e.x, e.y)
        x1, y1 = self.drag_start
        self.drag_start = None
        if self.drag_item:
            self.canvas.delete(self.drag_item); self.drag_item = None

        l = max(0, int(min(x1, end_x)))
        t = max(0, int(min(y1, end_y)))
        r = min(self.original.width, int(max(x1, end_x)))
        b = min(self.original.height, int(max(y1, end_y)))

        if r - l < 8 or b - t < 8: return
        self.crop_box = (l, t, r, b)
        self.crop_label.config(text=f"Crop: {r-l}×{b-t}")
        self._refresh_preview(); self._refresh_raster()

    def _reset_crop(self):
        self.crop_box = None
        self.crop_label.config(text="Crop: none")
        self._refresh_preview(); self._refresh_raster()

    def _fit_width(self):
        img = self.original
        if self.crop_box:
            _, t, _, b = self.crop_box
        else:
            t, b = 0, img.height
        self.crop_box = (0, t, img.width, b)
        self.crop_label.config(text=f"Crop: {img.width}×{b-t}")
        self._refresh_preview(); self._refresh_raster()

    def _refresh_preview(self):
        try:
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            if cw <= 10 or ch <= 10:
                self.after(100, self._refresh_preview); return

            img = self.original.copy()
            ratio = min(cw / img.width, ch / img.height, 1.0)
            self.scale = ratio
            dw = max(1, int(img.width * ratio))
            dh = max(1, int(img.height * ratio))
            disp = img.convert("RGB").resize((dw, dh))
            self._disp_img = ImageTk.PhotoImage(disp)

            self.canvas.delete("all")
            self.offset = ((cw - dw) // 2, (ch - dh) // 2)
            self.canvas.create_image(*self.offset, anchor="nw", image=self._disp_img)

            if self.crop_box:
                l, t, r, b = self.crop_box
                ox, oy = self.offset
                self.canvas.create_rectangle(
                    ox + l * ratio, oy + t * ratio,
                    ox + r * ratio, oy + b * ratio,
                    outline=C["accent"], width=2, dash=(4, 2))
        except Exception as e:
            print("Preview error:", e)

    def _compute_raster(self):
        img = self.original.copy()
        if self.crop_box: img = img.crop(self.crop_box)
        if img.width > self.PRINTER_WIDTH:
            r = self.PRINTER_WIDTH / img.width
            img = img.resize((self.PRINTER_WIDTH, max(1, int(img.height * r))))
        img = ImageEnhance.Brightness(img).enhance(self.bright_var.get())
        img = ImageEnhance.Contrast(img).enhance(self.contrast_var.get())
        if self.dither_var.get() == "threshold":
            img = img.point(lambda p: 0 if p < 128 else 255, "L").convert("1")
        else:
            img = img.convert("1")
        return img

    def _refresh_raster(self):
        try:
            cw = self.raster_canvas.winfo_width()
            if cw <= 10:
                self.after(100, self._refresh_raster); return
            img = self._compute_raster()
            if img.width == 0 or img.height == 0: return
            ch = 170
            ratio = min(cw / img.width, ch / img.height, 1.0)
            dw = max(1, int(img.width * ratio))
            dh = max(1, int(img.height * ratio))
            disp = img.convert("RGB").resize((dw, dh))
            self._raster_img = ImageTk.PhotoImage(disp)
            self.raster_canvas.delete("all")
            x = max(0, (cw - dw) // 2)
            self.raster_canvas.create_image(x, 0, anchor="nw", image=self._raster_img)
            self.size_label.config(
                text=f"{img.width}×{img.height} px · {img.width//8} bytes/row")
        except Exception as e:
            print("Raster preview error:", e)
            self.size_label.config(text=f"Error: {e}")

    def _accept(self):
        try: self.result = self._compute_raster()
        except Exception as e:
            messagebox.showerror("Error", str(e)); return
        self.destroy()


# =====================================================================
# Feedback widgets: progress strip + toasts
# =====================================================================
class MetroProgress(tk.Canvas):
    """Windows 8 progress strip: sliding dots (busy) or a thin bar (determinate)."""
    def __init__(self, parent, height=6, bg_key="bg"):
        tk.Canvas.__init__(self, parent, height=height, bd=0, highlightthickness=0)
        self._theme_attrs = {"bg": bg_key}
        self.config(bg=C[bg_key])
        self._mode, self._frac, self._t = "idle", 0.0, 0.0
        self._job = self._hide_job = None
        self.bind("<Configure>", lambda e: self.redraw())

    def start(self):
        self._cancel_hide()
        self._mode = "busy"
        if self._job is None:
            self._tick()

    def set(self, frac):
        self._cancel_hide()
        self._stop_anim()
        self._mode, self._frac = "bar", max(0.0, min(1.0, frac))
        self.redraw()

    def finish(self):
        self.set(1.0)
        self._hide_job = self.after(600, self.stop)

    def stop(self):
        self._cancel_hide()
        self._stop_anim()
        self._mode = "idle"
        self.redraw()

    def _cancel_hide(self):
        if self._hide_job is not None:
            try: self.after_cancel(self._hide_job)
            except Exception: pass
            self._hide_job = None

    def _stop_anim(self):
        if self._job is not None:
            try: self.after_cancel(self._job)
            except Exception: pass
            self._job = None

    def _tick(self):
        self._t = (self._t + 0.011) % 1.0
        self.redraw()
        self._job = self.after(30, self._tick)

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), int(self.cget("height"))
        if w <= 1 or self._mode == "idle":
            return
        if self._mode == "bar":
            self.create_rectangle(0, 0, w, h, fill=C["bg_alt"], outline="")
            self.create_rectangle(0, 0, w * self._frac, h, fill=C["accent"], outline="")
        else:
            for i in range(5):
                u = (self._t - i * 0.05) % 1.0
                p = 0.5 + 4 * (u - 0.5) ** 3      # slow in the middle, fast at the edges
                x = p * w
                self.create_rectangle(x - 2, 1, x + 2, h - 1, fill=C["accent"], outline="")


class Toast(tk.Frame):
    """Windows 8 toast: a solid colour block with a title, text and optional action."""
    W = 340

    def __init__(self, parent, title, message, color, on_close, action=None):
        tk.Frame.__init__(self, parent, bg=color, bd=0, highlightthickness=0,
                          cursor="hand2")
        self.on_close = on_close
        wrap = self.W - 32 - 26
        body = tk.Frame(self, bg=color, bd=0)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        body.grid_columnconfigure(0, weight=1, minsize=wrap)

        t = tk.Label(body, text=title, font=F_BODY_B, bg=color, fg="#ffffff",
                     anchor="w", justify="left", wraplength=wrap)
        t.grid(row=0, column=0, sticky="w")
        x = tk.Canvas(body, width=14, height=14, bg=color, highlightthickness=0,
                      bd=0, cursor="hand2")
        x.create_line(2, 2, 12, 12, fill="#ffffff", width=2)
        x.create_line(12, 2, 2, 12, fill="#ffffff", width=2)
        x.grid(row=0, column=1, sticky="ne", padx=(8, 0))
        widgets = [self, body, t, x]

        if message:
            m = tk.Label(body, text=message, font=F_TINY, bg=color, fg="#ffffff",
                         anchor="w", justify="left", wraplength=wrap)
            m.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
            widgets.append(m)

        if action:
            label, callback = action
            a = tk.Label(body, text=label, font=F_TINY, bg=color, fg="#ffffff",
                         padx=14, pady=3, highlightthickness=1,
                         highlightbackground="#ffffff", cursor="hand2")
            a.grid(row=2, column=0, sticky="w", pady=(10, 0))
            a.bind("<Enter>", lambda e: a.config(bg="#ffffff", fg=color))
            a.bind("<Leave>", lambda e: a.config(bg=color, fg="#ffffff"))
            a.bind("<Button-1>", lambda e: (self.on_close(self), callback()))

        for w in widgets:
            w.bind("<Button-1>", lambda e: self.on_close(self))


# =====================================================================
# Library (templates + history) storage
# =====================================================================
def describe_settings(s):
    """One-line human summary of a saved formatting snapshot."""
    parts = [str(s.get("align", "left")).title(),
             f'{s.get("font_family", "Mono")} {s.get("font_size", 20)}']
    flags = [n for k, n in (("bold", "Bold"), ("underline", "Underline"),
                            ("inverse", "Inverse"), ("double", "Double"),
                            ("cut", "Cut")) if s.get(k)]
    if flags:
        parts.append(", ".join(flags))
    parts.append("raster" if s.get("raster", True) else "native text")
    return "  ·  ".join(parts)


def first_line(item, limit=40):
    for ln in str(item.get("text", "")).splitlines():
        ln = ln.strip()
        if ln:
            return ln if len(ln) <= limit else ln[:limit - 1] + "…"
    return ""


class Library:
    """Templates and print history, persisted as JSON in ~/.config/bt_printer/."""
    MAX_HISTORY = 50

    def __init__(self, path=None):
        self.path = path or os.path.join(os.path.expanduser("~"), ".config",
                                         "bt_printer", "library.json")
        self.data = {"templates": [], "history": []}
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k in ("templates", "history"):
                items = raw.get(k, [])
                self.data[k] = [i for i in items
                                if isinstance(i, dict) and "text" in i]
        except (OSError, ValueError, AttributeError):
            pass    # first run or unreadable file -> start empty

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def _next_id(self):
        ids = [i.get("id", 0) for k in self.data for i in self.data[k]
               if isinstance(i.get("id", 0), int)]
        return (max(ids) if ids else 0) + 1

    def add_template(self, name, text, settings):
        item = {"id": self._next_id(), "name": name,
                "created": time.strftime("%Y-%m-%d %H:%M"),
                "text": text, "settings": settings}
        self.data["templates"].insert(0, item)
        self.save()
        return item

    def add_history(self, text, settings):
        hist = self.data["history"]
        stamp = time.strftime("%Y-%m-%d %H:%M")
        if hist and hist[0].get("text") == text and hist[0].get("settings") == settings:
            hist[0]["created"] = stamp          # same print again: just bump the time
        else:
            hist.insert(0, {"id": self._next_id(), "created": stamp,
                            "text": text, "settings": settings})
            del hist[self.MAX_HISTORY:]
        self.save()

    def delete(self, kind, item_id):
        self.data[kind] = [i for i in self.data[kind] if i.get("id") != item_id]
        self.save()

    def clear_history(self):
        self.data["history"] = []
        self.save()


# =====================================================================
# Library UI: list view, library window, preview window
# =====================================================================
class MetroList(tk.Frame):
    """Two-line list view (title + muted subtitle) with accent selection."""
    ROW_H = 58

    def __init__(self, parent, on_select=None, on_activate=None, width=300):
        tk.Frame.__init__(self, parent, bd=0, highlightthickness=2)
        themed(self, bg="field", highlightbackground="border")
        self._on_select, self._on_activate = on_select, on_activate
        self._items, self._sel, self._hover = [], -1, -1
        self._region_h = 1
        self._fnt = None
        self.cv = tk.Canvas(self, width=width, height=300, bd=0, highlightthickness=0,
                            yscrollincrement=self.ROW_H // 2)
        self.sb = ttk.Scrollbar(self, orient="vertical",
                                style="Metro.Vertical.TScrollbar", command=self.cv.yview)
        self.cv.config(yscrollcommand=self.sb.set)
        self.sb.pack(side="right", fill="y", padx=(0, 2), pady=2)
        self.cv.pack(side="left", fill="both", expand=True)
        self.cv.bind("<Configure>", lambda e: self.redraw())
        self.cv.bind("<Button-1>", self._click)
        self.cv.bind("<Double-Button-1>", self._double)
        self.cv.bind("<Motion>", self._motion)
        self.cv.bind("<Leave>", lambda e: self._set_hover(-1))
        self.cv.bind("<MouseWheel>",
                     lambda e: self.cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.cv.bind("<Button-4>", lambda e: self.cv.yview_scroll(-1, "units"))
        self.cv.bind("<Button-5>", lambda e: self.cv.yview_scroll(1, "units"))

    def set_items(self, rows):
        self._items, self._sel, self._hover = list(rows), -1, -1
        self.cv.yview_moveto(0)
        self.redraw()

    def select(self, i, notify=True):
        if not (0 <= i < len(self._items)):
            self._sel = -1
        else:
            self._sel = i
            top, bottom = i * self.ROW_H, (i + 1) * self.ROW_H
            y0, vh = self.cv.canvasy(0), self.cv.winfo_height()
            if top < y0:
                self.cv.yview_moveto(top / self._region_h)
            elif bottom > y0 + vh:
                self.cv.yview_moveto((bottom - vh) / self._region_h)
        self.redraw()
        if notify and self._on_select:
            self._on_select(self._sel)

    def _row_at(self, y):
        i = int(self.cv.canvasy(y) // self.ROW_H)
        return i if 0 <= i < len(self._items) else -1

    def _click(self, e):
        i = self._row_at(e.y)
        if i >= 0:
            self.select(i)

    def _double(self, e):
        i = self._row_at(e.y)
        if i >= 0 and self._on_activate:
            self._on_activate(i)

    def _motion(self, e):
        self._set_hover(self._row_at(e.y))

    def _set_hover(self, i):
        if i != self._hover:
            self._hover = i
            self.redraw()

    def _fit(self, text, font, maxw):
        if font.measure(text) <= maxw:
            return text
        while text and font.measure(text + "…") > maxw:
            text = text[:-1]
        return text + "…"

    def redraw(self):
        cv = self.cv
        cv.delete("all")
        cv.config(bg=C["field"])
        w, vh = max(cv.winfo_width(), 50), max(cv.winfo_height(), 50)
        self._region_h = max(len(self._items) * self.ROW_H, vh)
        cv.config(scrollregion=(0, 0, w, self._region_h))
        if not self._items:
            cv.create_text(w / 2, 64, text="Nothing here yet", fill=C["text_muted"],
                           font=F_BODY)
            return
        if self._fnt is None:
            self._fnt = (tkfont.Font(font=F_BODY_B), tkfont.Font(font=F_TINY))
        f1, f2 = self._fnt
        for i, (title, sub) in enumerate(self._items):
            y = i * self.ROW_H
            if i == self._sel:
                bg, fg, fg2 = C["accent"], C["on_accent"], "#dcebfc"
            elif i == self._hover:
                bg, fg, fg2 = C["field_hi"], C["text"], C["text_muted"]
            else:
                bg, fg, fg2 = C["field"], C["text"], C["text_muted"]
            cv.create_rectangle(0, y, w, y + self.ROW_H, fill=bg, outline="")
            cv.create_text(16, y + 13, text=self._fit(title, f1, w - 32), anchor="nw",
                           fill=fg, font=F_BODY_B)
            cv.create_text(16, y + 35, text=self._fit(sub, f2, w - 32), anchor="nw",
                           fill=fg2, font=F_TINY)


class LibraryWindow(tk.Toplevel):
    """Pivot window with 'templates' and 'history'."""
    def __init__(self, app, tab="templates"):
        tk.Toplevel.__init__(self, app.root)
        self.app = app
        self.title("Library")
        self.geometry("900x640")
        self.minsize(780, 560)
        self.configure(bg=C["bg"])
        themed(self, bg="bg")
        self.transient(app.root)
        self.tab, self._items, self._cur = tab, [], None
        self._pivot = {}
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda e: self.close())
        self.set_tab(tab)

    def _build(self):
        body = themed(tk.Frame(self), bg="bg")
        body.pack(fill="both", expand=True, padx=36, pady=(26, 28))

        piv = themed(tk.Frame(body), bg="bg"); piv.pack(fill="x")
        for key in ("templates", "history"):
            lab = tk.Label(piv, text=key, font=(F_TITLE[0], 26), bd=0, cursor="hand2")
            lab.pack(side="left", padx=(0, 28))
            lab.bind("<Button-1>", lambda e, k=key: self.set_tab(k))
            self._pivot[key] = lab

        self.sub = themed(tk.Label(body, text="", font=F_SUB, anchor="w"),
                          fg="text_muted", bg="bg")
        self.sub.pack(anchor="w", pady=(2, 16))

        main = themed(tk.Frame(body), bg="bg"); main.pack(fill="both", expand=True)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)
        self.lst = MetroList(main, on_select=self._on_select,
                             on_activate=lambda i: self._use())
        self.lst.grid(row=0, column=0, sticky="ns", padx=(0, 26))

        det = themed(tk.Frame(main), bg="bg"); det.grid(row=0, column=1, sticky="nsew")
        self.d_title = themed(tk.Label(det, text="", font=F_H2, anchor="w"),
                              fg="text", bg="bg")
        self.d_title.pack(anchor="w")
        self.d_meta = themed(tk.Label(det, text="", font=F_TINY, anchor="w"),
                             fg="text_muted", bg="bg")
        self.d_meta.pack(anchor="w", pady=(0, 10))
        box, self.d_text, _sb = make_textarea(det, height=10, font=F_MONO, width=20,
                                              undo=False)
        box.pack(fill="both", expand=True)
        self.d_text.config(state="disabled")

        self.actions = themed(tk.Frame(body), bg="bg")
        self.actions.pack(fill="x", pady=(18, 0))

    def redraw(self):
        self._paint_pivot()

    def _paint_pivot(self):
        for key, lab in self._pivot.items():
            lab.config(bg=C["bg"], fg=C["text"] if key == self.tab else C["text_muted"])

    def set_tab(self, tab):
        self.tab = tab
        self._paint_pivot()
        self.sub.config(text="Saved snippets together with their formatting"
                        if tab == "templates" else
                        f"Your last {Library.MAX_HISTORY} text prints")
        self._build_actions()
        self.refresh()

    def _build_actions(self):
        for w in self.actions.winfo_children():
            w.destroy()
        a = self.actions
        if self.tab == "templates":
            make_label(a, "NAME").pack(side="left", padx=(0, 8))
            self.name_var = tk.StringVar()
            make_entry(a, textvariable=self.name_var, width=22
                       ).pack(side="left", ipady=6)
            MetroButton(a, "Save current text", self._save_template,
                        padx=18, pady=8).pack(side="left", padx=(10, 0))
            right = [("Use", self._use, "primary"), ("Print", self._print, "secondary"),
                     ("Delete", self._delete, "secondary")]
        else:
            MetroButton(a, "Clear all", self._clear_all, pady=8).pack(side="left")
            right = [("Use", self._use, "primary"), ("Reprint", self._print, "secondary"),
                     ("Delete", self._delete, "secondary")]
        self.status = themed(tk.Label(a, text="", font=F_TINY), fg="text_muted", bg="bg")
        self.status.pack(side="left", padx=16)
        for text, cmd, kind in right:
            MetroButton(a, text, cmd, kind=kind, padx=24, pady=8
                        ).pack(side="right", padx=(10, 0) if text != "Use" else 0)

    def _say(self, msg, kind="muted"):
        key = {"error": "red", "success": "green"}.get(kind, "text_muted")
        self.status.config(text=msg, fg=C[key])

    def refresh(self):
        kind = self.tab
        self._items = list(self.app.library.data[kind])
        rows = []
        for it in self._items:
            if kind == "templates":
                rows.append((it.get("name") or "Untitled",
                             f'{it.get("created", "")}  ·  {first_line(it, 28)}'))
            else:
                rows.append((first_line(it) or "(empty)", it.get("created", "")))
        self.lst.set_items(rows)
        self.lst.select(0 if rows else -1)

    def _on_select(self, i):
        self._cur = self._items[i] if 0 <= i < len(self._items) else None
        it = self._cur
        if it is None:
            self.d_title.config(text="")
            self.d_meta.config(text="")
            text = ""
        else:
            if self.tab == "templates":
                self.d_title.config(text=it.get("name") or "Untitled")
            else:
                self.d_title.config(text="Printed " + it.get("created", ""))
            self.d_meta.config(text=describe_settings(it.get("settings", {})))
            text = it.get("text", "")
        self.d_text.config(state="normal")
        self.d_text.delete("1.0", "end")
        self.d_text.insert("1.0", text)
        self.d_text.config(state="disabled")

    def _use(self):
        if self._cur is None:
            return
        self.app.load_into_editor(self._cur)
        self.close()

    def _print(self):
        if self._cur is None:
            return
        item = self._cur
        self.app.load_into_editor(item)
        self.close()
        self.app.print_text()

    def _delete(self):
        if self._cur is None:
            return
        try:
            self.app.library.delete(self.tab, self._cur["id"])
        except OSError as e:
            self._say(f"Could not delete: {e}", "error"); return
        self.refresh()

    def _clear_all(self):
        if not self.app.library.data["history"]:
            return
        if messagebox.askyesno("Clear history", "Delete all print history?", parent=self):
            try:
                self.app.library.clear_history()
            except OSError as e:
                self._say(f"Could not clear: {e}", "error"); return
            self.refresh()

    def _save_template(self):
        text = self.app.text_input.get("1.0", "end-1c")
        if not text.strip():
            self._say("Nothing to save - the content box is empty", "error"); return
        name = (self.name_var.get().strip()
                or first_line({"text": text}, 28) or "Untitled")
        try:
            self.app.library.add_template(name, text, self.app._snapshot_settings())
        except OSError as e:
            self._say(f"Could not save: {e}", "error"); return
        self.name_var.set("")
        self.refresh()
        self._say(f"Saved “{name}”", "success")

    def close(self):
        if self.app._library_win is self:
            self.app._library_win = None
        self.destroy()


class PreviewWindow(tk.Toplevel):
    """Live paper preview - re-renders as you type or change formatting."""
    def __init__(self, app):
        tk.Toplevel.__init__(self, app.root)
        self.app = app
        self.title("Print preview")
        root = app.root
        root.update_idletasks()
        sw = root.winfo_screenwidth()
        x = root.winfo_x() + root.winfo_width() + 8
        if x + 500 > sw:
            x = max(0, sw - 500)
        self.geometry(f"500x780+{x}+{max(0, root.winfo_y())}")
        self.minsize(460, 480)
        self.configure(bg=C["bg"])
        themed(self, bg="bg")
        self.transient(root)
        self._job, self._photo, self._pimg, self._msg = None, None, None, ""
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda e: self.close())
        self.render()

    def _build(self):
        body = themed(tk.Frame(self), bg="bg")
        body.pack(fill="both", expand=True, padx=30, pady=(24, 26))
        themed(tk.Label(body, text="preview", font=F_H2, anchor="w"),
               fg="text", bg="bg").pack(anchor="w")
        themed(tk.Label(body, text="Updates as you type  ·  paper is 384 dots (48 mm) wide",
                        font=F_SUB, anchor="w"), fg="text_muted", bg="bg"
               ).pack(anchor="w", pady=(0, 6))
        self.note = themed(tk.Label(body, text="", font=F_TINY, anchor="w",
                                    justify="left", wraplength=420),
                           fg="yellow", bg="bg")
        self.note.pack(anchor="w")

        box = tk.Frame(body, bd=0, highlightthickness=2)
        themed(box, bg="canvas", highlightbackground="border")
        box.pack(fill="both", expand=True, pady=(8, 0))
        self.cv = tk.Canvas(box, bd=0, highlightthickness=0, width=300, height=300)
        sb = ttk.Scrollbar(box, orient="vertical", style="Metro.Vertical.TScrollbar",
                           command=self.cv.yview)
        self.cv.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 2), pady=2)
        self.cv.pack(side="left", fill="both", expand=True)
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.cv.bind("<MouseWheel>",
                     lambda e: self.cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.cv.bind("<Button-4>", lambda e: self.cv.yview_scroll(-1, "units"))
        self.cv.bind("<Button-5>", lambda e: self.cv.yview_scroll(1, "units"))

        foot = themed(tk.Frame(body), bg="bg"); foot.pack(fill="x", pady=(16, 0))
        self.info = themed(tk.Label(foot, text="", font=F_TINY), fg="text_muted", bg="bg")
        self.info.pack(side="left")
        MetroButton(foot, "Print", self.app.print_text, kind="primary",
                    padx=28).pack(side="right")
        MetroButton(foot, "Close", self.close).pack(side="right", padx=(0, 10))

    def redraw(self):
        self.draw()

    def schedule(self):
        if self._job is not None:
            try: self.after_cancel(self._job)
            except Exception: pass
        self._job = self.after(220, self.render)

    def render(self):
        self._job = None
        app = self.app
        self.note.config(text="" if app.raster_var.get() else
                         "Native text mode: the printer uses its own font, so this "
                         "preview is only an approximation.")
        text = app.text_input.get("1.0", "end-1c")
        self._pimg = None
        if not text.strip():
            self._msg = "Type something in the content box\nto see the printout here."
            self.info.config(text="")
        else:
            try:
                img = app._render_text_image(text)
                self._pimg = ImageOps.colorize(img.convert("L"),
                                               black="#1b1b1b", white="#fcfbf6")
                self.info.config(
                    text=f"{img.width}×{img.height} px  ·  about {img.height / 8:.0f} mm of paper")
            except (tk.TclError, ValueError):
                self._msg = "Waiting for a valid number\nin the formatting fields…"
                self.info.config(text="")
            except Exception as e:
                self._msg = f"Can't render yet:\n{e}"
                self.info.config(text="")
        self.draw()

    def draw(self):
        cv = self.cv
        cv.delete("all")
        cv.config(bg=C["canvas"])
        cw = max(cv.winfo_width(), 100)
        img = self._pimg
        if img is None:
            cv.create_text(cw / 2, 120, text=self._msg, fill=C["text_muted"],
                           font=F_BODY, justify="center")
            cv.config(scrollregion=(0, 0, cw, 10))
            return
        x0, y0 = max(16, (cw - img.width) // 2), 24
        self._photo = ImageTk.PhotoImage(img)
        shadow = shade(C["canvas"], 0.8)
        cv.create_rectangle(x0 + 4, y0 + 4, x0 + img.width + 4, y0 + img.height + 4,
                            fill=shadow, outline="")
        cv.create_image(x0, y0, anchor="nw", image=self._photo)
        yb, step = y0 + img.height, 12                      # torn paper edge
        for k in range(img.width // step):
            xa = x0 + k * step
            cv.create_polygon(xa, yb + 1, xa + step / 2, yb - 7, xa + step, yb + 1,
                              fill=C["canvas"], outline="")
        cv.config(scrollregion=(0, 0, cw, yb + 40))

    def close(self):
        if self.app._preview_win is self:
            self.app._preview_win = None
        self.destroy()


# =====================================================================
# Main app
# =====================================================================
class PrinterApp:
    def __init__(self, root):
        self.root = root
        init_fonts(root)
        self.root.title("Thermal Printer")
        self.root.geometry("1120x930")
        self.root.minsize(1060, 880)
        themed(self.root, bg="bg")
        self.connection = None
        self.conn_type = tk.StringVar(value="classic")
        self.theme_name = "dark"
        self._combos = []
        self._toasts = []
        self._lost = False
        self._sending = False
        self._blink_running = False
        self._blink_state = False
        self._preview_win = None
        self._library_win = None
        self.library = Library()
        self._setup_ttk()
        self.progress = MetroProgress(self.root)
        self.progress.pack(fill="x")
        self._build_header()
        self._build_body()
        self._watch_preview_vars()
        self.root.after(2000, self._poll_link)

    # ---------- ttk styling (comboboxes + scrollbars) ----------
    def _setup_ttk(self):
        style = ttk.Style(); style.theme_use("clam")
        style.configure("TCombobox",
                         fieldbackground=C["field"], background=C["btn"],
                         foreground=C["text"], arrowcolor=C["text"],
                         bordercolor=C["border"], lightcolor=C["field"],
                         darkcolor=C["field"], insertcolor=C["text"],
                         selectbackground=C["field"], selectforeground=C["text"],
                         borderwidth=2, relief="flat", arrowsize=15, padding=6)
        style.map("TCombobox",
                   fieldbackground=[("readonly", C["field"]),
                                    ("disabled", C["disabled_bg"])],
                   foreground=[("readonly", C["text"])],
                   background=[("active", C["btn_hi"]), ("readonly", C["btn"])],
                   bordercolor=[("focus", C["accent"]), ("hover", C["border_hi"])],
                   lightcolor=[("focus", C["field"])],
                   darkcolor=[("focus", C["field"])],
                   arrowcolor=[("active", C["accent"])],
                   selectbackground=[("readonly", C["field"])],
                   selectforeground=[("readonly", C["text"])])

        style.layout("Metro.Vertical.TScrollbar",
                      [("Vertical.Scrollbar.trough",
                        {"sticky": "ns",
                         "children": [("Vertical.Scrollbar.thumb",
                                       {"expand": "1", "sticky": "nswe"})]})])
        style.configure("Metro.Vertical.TScrollbar",
                         background=C["border"], troughcolor=C["field"],
                         bordercolor=C["field"], lightcolor=C["border"],
                         darkcolor=C["border"], gripcount=0, relief="flat",
                         width=10)
        style.map("Metro.Vertical.TScrollbar",
                   background=[("pressed", C["accent"]), ("active", C["border_hi"])],
                   lightcolor=[("pressed", C["accent"]), ("active", C["border_hi"])],
                   darkcolor=[("pressed", C["accent"]), ("active", C["border_hi"])])

        self.root.option_add("*TCombobox*Listbox.background", C["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", C["on_accent"])
        self.root.option_add("*TCombobox*Listbox.font", F_BODY)
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)
        self.root.option_add("*TCombobox*Listbox.relief", "flat")

    def _style_popdowns(self):
        """Re-colour already-created combobox drop-down lists after a theme switch."""
        for cb in getattr(self, "_combos", []):
            try:
                pop = self.root.tk.call("ttk::combobox::PopdownWindow", str(cb))
                self.root.tk.call(f"{pop}.f.l", "configure",
                                  "-background", C["field"], "-foreground", C["text"],
                                  "-selectbackground", C["accent"],
                                  "-selectforeground", C["on_accent"])
            except Exception:
                pass

    # ---------- Header ----------
    def _build_header(self):
        header = themed(tk.Frame(self.root), bg="bg")
        header.pack(fill="x", padx=48, pady=(34, 20))

        left = themed(tk.Frame(header), bg="bg")
        left.pack(side="left")

        logo = tk.Canvas(left, width=68, height=68, bg=TILE["blue"],
                         highlightthickness=0, bd=0)
        logo.pack(side="left", padx=(0, 20))
        draw_icon(logo, "printer", 34, 34, 18, "#ffffff", w=2)

        titles = themed(tk.Frame(left), bg="bg")
        titles.pack(side="left")
        themed(tk.Label(titles, text="Thermal Printer", font=F_TITLE, anchor="w"),
                fg="text", bg="bg").pack(anchor="w")
        themed(tk.Label(titles, text="Bluetooth ESC/POS  ·  Classic & BLE", font=F_SUB,
                        anchor="w"),
                fg="text_muted", bg="bg").pack(anchor="w")

        right = themed(tk.Frame(header), bg="bg")
        right.pack(side="right")

        self.theme_btn = IconButton(right, "sun", self.toggle_theme, size=44)
        self.theme_btn.pack(side="right", padx=(22, 0))

        pill = themed(tk.Frame(right), bg="bg")
        pill.pack(side="right")
        self.status_dot = tk.Canvas(pill, width=12, height=12,
                                    highlightthickness=0, bd=0)
        themed(self.status_dot, bg="bg")
        self.status_dot.pack(side="left", padx=(0, 9))
        self.status_circle = self.status_dot.create_rectangle(
            0, 0, 12, 12, fill=C["red"], outline="")
        self.status_text = themed(tk.Label(pill, text="Disconnected", font=F_BODY_B),
                                   fg="text_muted", bg="bg")
        self.status_text.pack(side="left")

    def toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        set_theme(self.theme_name)
        retheme_tree(self.root)
        self._setup_ttk()
        self._style_popdowns()
        self.theme_btn.set_icon("moon" if self.theme_name == "light" else "sun")
        self._set_status(self.connection is not None and self.connection.is_connected(),
                         self._lost)
        for tag, key in [("info","text_dim"),("success","green"),
                         ("error","red"),("sent","accent"),("dim","text_muted")]:
            self.log.tag_config(tag, foreground=C[key])

    # ---------- Body ----------
    def _build_body(self):
        body = themed(tk.Frame(self.root), bg="bg")
        body.pack(fill="both", expand=True, padx=48, pady=(0, 34))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0)
        body.grid_rowconfigure(0, weight=1)

        left = themed(tk.Frame(body), bg="bg")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 44))
        right = themed(tk.Frame(body), bg="bg")
        right.grid(row=0, column=1, sticky="ns")

        self._build_connection_card(left)
        self._build_content_card(left)
        self._build_options_card(left)
        self._build_actions(right)
        self._build_log(right)

    def _build_connection_card(self, parent):
        sec = make_section(parent, "connection")
        sec.pack(fill="x", pady=(0, 22))

        grid = themed(tk.Frame(sec), bg="bg"); grid.pack(fill="x")
        grid.grid_columnconfigure(3, weight=1)
        make_label(grid, "MAC ADDRESS").grid(row=0, column=0, sticky="w", pady=(0, 4))
        make_label(grid, "MODE").grid(row=0, column=1, sticky="w", pady=(0, 4))
        make_label(grid, "CHANNEL").grid(row=0, column=2, sticky="w", pady=(0, 4))

        self.mac_entry = make_entry(grid, width=19, font=F_MONO)
        self.mac_entry.grid(row=1, column=0, sticky="w", ipady=6, padx=(0, 20))

        seg = themed(tk.Frame(grid), bg="bg")
        seg.grid(row=1, column=1, sticky="w", padx=(0, 20))
        self.seg_buttons = {}
        for val, label in [("classic", "Classic SPP"), ("ble", "BLE")]:
            b = MetroButton(seg, label, command=lambda v=val: self._set_conn_type(v),
                            kind="seg", padx=16, pady=7)
            b.pack(side="left", padx=(0, 2))
            self.seg_buttons[val] = b
        self._refresh_segment()

        self.channel_var = tk.StringVar(value="2")
        make_entry(grid, width=4, textvariable=self.channel_var, justify="center"
                   ).grid(row=1, column=2, sticky="w", ipady=6, padx=(0, 20))

        self.connect_btn = MetroButton(grid, "Connect", self.toggle_connect,
                                       kind="primary", padx=30, pady=9)
        self.connect_btn.grid(row=1, column=3, sticky="e")

        r2 = themed(tk.Frame(sec), bg="bg"); r2.pack(fill="x", pady=(14, 0))
        self.scan_btn = MetroButton(r2, "Scan devices", self.scan_devices, pady=9)
        self.scan_btn.pack(side="left", padx=(0, 12))
        self.device_combo = ttk.Combobox(r2, width=40, state="readonly", font=F_MONO)
        self.device_combo.pack(side="left", fill="x", expand=True)
        self.device_combo.bind("<<ComboboxSelected>>", self._on_device_selected)
        self._combos.append(self.device_combo)

    def _set_conn_type(self, val):
        self.conn_type.set(val); self._refresh_segment()

    def _refresh_segment(self):
        for val, btn in self.seg_buttons.items():
            btn.set_selected(self.conn_type.get() == val)

    def _build_content_card(self, parent):
        sec = make_section(parent, "content")
        sec.pack(fill="both", expand=True, pady=(0, 22))
        box, self.text_input, _sb = make_textarea(sec, height=6, font=F_MONO, width=20)
        box.pack(fill="both", expand=True)

    def _build_options_card(self, parent):
        sec = make_section(parent, "formatting")
        sec.pack(fill="x")

        grid = themed(tk.Frame(sec), bg="bg"); grid.pack(fill="x")
        for col, txt in enumerate(["ALIGNMENT", "FONT", "SIZE", "LINE SPACING ×", "FEED LINES"]):
            make_label(grid, txt).grid(row=0, column=col, sticky="w", pady=(0, 4))

        self.align_var = tk.StringVar(value="left")
        cb1 = ttk.Combobox(grid, textvariable=self.align_var, width=9, state="readonly",
                           values=["left", "center", "right"], font=F_BODY)
        cb1.grid(row=1, column=0, sticky="w", padx=(0, 18))

        self.font_family_var = tk.StringVar(value="Mono")
        cb2 = ttk.Combobox(grid, textvariable=self.font_family_var, width=9,
                           state="readonly", values=["Mono", "Sans", "Serif"],
                           font=F_BODY)
        cb2.grid(row=1, column=1, sticky="w", padx=(0, 18))
        self._combos.extend([cb1, cb2])

        self.font_size_var = tk.IntVar(value=20)
        make_entry(grid, width=5, textvariable=self.font_size_var,
                   justify="center").grid(row=1, column=2, sticky="w", ipady=6, padx=(0, 18))

        self.line_spacing_var = tk.DoubleVar(value=1.0)
        make_entry(grid, width=7, textvariable=self.line_spacing_var,
                   justify="center").grid(row=1, column=3, sticky="w", ipady=6, padx=(0, 18))

        self.feed_var = tk.IntVar(value=3)
        make_entry(grid, width=5, textvariable=self.feed_var,
                   justify="center").grid(row=1, column=4, sticky="w", ipady=6)

        checks = themed(tk.Frame(sec), bg="bg"); checks.pack(fill="x", pady=(18, 0))
        self.bold_var = tk.BooleanVar()
        MetroCheck(checks, "Bold", self.bold_var).pack(side="left", padx=(0, 26))
        self.underline_var = tk.BooleanVar()
        MetroCheck(checks, "Underline", self.underline_var).pack(side="left", padx=(0, 26))
        self.inverse_var = tk.BooleanVar()
        MetroCheck(checks, "Inverse", self.inverse_var).pack(side="left", padx=(0, 26))
        self.double_var = tk.BooleanVar()
        MetroCheck(checks, "Double", self.double_var).pack(side="left", padx=(0, 26))
        self.cut_var = tk.BooleanVar()
        MetroCheck(checks, "Cut", self.cut_var).pack(side="left")

        switches = themed(tk.Frame(sec), bg="bg"); switches.pack(fill="x", pady=(16, 0))
        self.raster_var = tk.BooleanVar(value=True)
        MetroSwitch(switches, "Render text as image (raster) — recommended",
                    self.raster_var).pack(anchor="w")
        self.compat_var = tk.BooleanVar(value=True)
        MetroSwitch(switches, "Append \\n\\r\\0 terminator",
                    self.compat_var).pack(anchor="w", pady=(10, 0))

    def _build_actions(self, parent):
        sec = make_section(parent, "actions")
        sec.pack(fill="x", pady=(0, 22))
        grid = themed(tk.Frame(sec), bg="bg"); grid.pack(anchor="w")
        G = 6

        MetroTile(grid, "Print", "printer", TILE["blue"], self.print_text,
                  width=306, height=150).grid(row=0, column=0, columnspan=2, pady=(0, G))
        MetroTile(grid, "Test page", "doc", TILE["green"], self.print_test
                  ).grid(row=1, column=0, padx=(0, G), pady=(0, G))
        MetroTile(grid, "Image…", "image", TILE["purple"], self.print_image
                  ).grid(row=1, column=1, pady=(0, G))
        MetroTile(grid, "Raw hex…", "hex", TILE["orange"], self.print_raw
                  ).grid(row=2, column=0, padx=(0, G))

        col = themed(tk.Frame(grid), bg="bg"); col.grid(row=2, column=1)
        MetroTile(col, "Pull paper", "up", TILE["teal"], self.feed_forward,
                  width=150, height=72, layout="h").pack(pady=(0, G))
        MetroTile(col, "Push paper", "down", TILE["crimson"], self.feed_backward,
                  width=150, height=72, layout="h").pack()

        MetroTile(grid, "Preview", "eye", TILE["blue"], self.open_preview,
                  width=150, height=64, layout="h").grid(row=3, column=0, padx=(0, G), pady=(G, 0))
        MetroTile(grid, "Library", "list", TILE["purple"], self.open_library,
                  width=150, height=64, layout="h").grid(row=3, column=1, pady=(G, 0))

    def _build_log(self, parent):
        sec = themed(tk.Frame(parent), bg="bg")
        sec.pack(fill="both", expand=True)

        head = themed(tk.Frame(sec), bg="bg"); head.pack(fill="x", pady=(0, 8))
        themed(tk.Label(head, text="log", font=F_H2, anchor="w"),
               fg="text", bg="bg").pack(side="left")
        MetroButton(head, "Clear", self._clear_log, kind="link",
                    padx=8, pady=2, font=F_TINY).pack(side="right")

        box, self.log, _sb = make_textarea(sec, height=5, font=F_LOG, width=10,
                                           undo=False, padx=10, pady=8)
        box.pack(fill="both", expand=True)
        self.log.config(state="disabled")

        for tag, key in [("info","text_dim"),("success","green"),
                         ("error","red"),("sent","accent"),("dim","text_muted")]:
            self.log.tag_config(tag, foreground=C[key])

    def log_msg(self, msg, tag="info"):
        self.log.config(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] ", "dim")
        self.log.insert("end", f"{msg}\n", tag)
        self.log.see("end"); self.log.config(state="disabled")

    def _clear_log(self):
        self.log.config(state="normal"); self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _set_status(self, connected, lost=False):
        if connected:
            self.status_dot.itemconfig(self.status_circle, fill=C["green"])
            self.status_text.config(text="Connected", fg=C["green"])
        elif lost:
            self.status_dot.itemconfig(self.status_circle, fill=C["red"])
            self.status_text.config(text="Connection lost", fg=C["red"])
        else:
            self.status_dot.itemconfig(self.status_circle, fill=C["red"])
            self.status_text.config(text="Disconnected", fg=C["text_muted"])

    # =================================================================
    # Feedback: toasts, progress, dropped-connection detection
    # =================================================================
    def _ui(self, fn, *args):
        """Run a UI call on the main thread (safe to call from worker threads)."""
        if threading.current_thread() is threading.main_thread():
            fn(*args)
        else:
            self.root.after(0, lambda: fn(*args))

    def toast(self, title, message="", kind="info", action=None, timeout=None):
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, lambda: self.toast(title, message, kind, action, timeout))
            return
        while len(self._toasts) >= 4:
            self._dismiss_toast(self._toasts[0][0])
        t = Toast(self.root, title, message,
                  TOAST_COLORS.get(kind, TOAST_COLORS["info"]),
                  self._dismiss_toast, action)
        ms = timeout if timeout is not None else (
            9000 if (kind in ("error", "warn") or action) else 4500)
        job = self.root.after(ms, lambda: self._dismiss_toast(t))
        self._toasts.append([t, job])
        self._layout_toasts()

    def _dismiss_toast(self, t):
        for entry in list(self._toasts):
            if entry[0] is t:
                try: self.root.after_cancel(entry[1])
                except Exception: pass
                self._toasts.remove(entry)
                try: t.destroy()
                except Exception: pass
                break
        self._layout_toasts()

    def _layout_toasts(self):
        self.root.update_idletasks()
        y = 24
        for t, _job in reversed(self._toasts):
            t.place(relx=1.0, rely=1.0, anchor="se", x=-24, y=-y, width=Toast.W)
            t.lift()
            self.root.update_idletasks()
            y += t.winfo_reqheight() + 8

    def _link_alive(self):
        """True while the printer link looks healthy (never touches the data stream)."""
        c = self.connection
        if c is None:
            return False
        try:
            if isinstance(c, ClassicPrinter):
                s = c.sock
                if s is None:
                    return False
                r, _w, x = select.select([s], [], [s], 0)
                if x:
                    return False
                if r:       # readable: either printer data or a hang-up (EOF)
                    try:
                        return s.recv(1, socket.MSG_PEEK) != b""
                    except (BlockingIOError, InterruptedError, socket.timeout):
                        return True
                return True
            return bool(c.is_connected())
        except (OSError, ValueError):
            return False

    def _poll_link(self):
        try:
            if self.connection is not None and not self._sending and not self._link_alive():
                self._on_link_lost()
        except Exception as e:
            print("link check error:", e)
        finally:
            self.root.after(2000, self._poll_link)

    def _verify_link(self):
        if self.connection is not None and not self._link_alive():
            self._on_link_lost()

    def _on_link_lost(self):
        conn, self.connection = self.connection, None
        if conn is not None:
            def _quiet():
                try: conn.disconnect()
                except Exception: pass
            threading.Thread(target=_quiet, daemon=True).start()
        self._lost = True
        self.connect_btn.config(text="Connect", state="normal")
        self.connect_btn.set_kind("primary")
        self._set_status(False, True)
        self.log_msg("Connection lost - the printer stopped responding", "error")
        self.toast("Printer disconnected",
                   "The Bluetooth link was lost. Check that the printer is on and in range.",
                   "error", action=("Reconnect", self.connect), timeout=15000)
        if not self._blink_running:
            self._blink()

    def _blink(self):
        if not self._lost:
            self._blink_running = False
            return
        self._blink_running = True
        self._blink_state = not self._blink_state
        self.status_dot.itemconfig(self.status_circle,
                                   fill=C["red"] if self._blink_state else C["bg"])
        self.root.after(600, self._blink)

    # ---------- live preview + library glue ----------
    def _num(self, var, cast, default):
        try: return cast(var.get())
        except Exception: return default

    def _snapshot_settings(self):
        return {
            "align": self.align_var.get(),
            "font_family": self.font_family_var.get(),
            "font_size": self._num(self.font_size_var, int, 20),
            "line_spacing": self._num(self.line_spacing_var, float, 1.0),
            "feed": self._num(self.feed_var, int, 3),
            "bold": bool(self.bold_var.get()),
            "underline": bool(self.underline_var.get()),
            "inverse": bool(self.inverse_var.get()),
            "double": bool(self.double_var.get()),
            "cut": bool(self.cut_var.get()),
            "raster": bool(self.raster_var.get()),
        }

    def load_into_editor(self, item):
        s = item.get("settings") or {}
        pairs = [(self.align_var, "align"), (self.font_family_var, "font_family"),
                 (self.font_size_var, "font_size"), (self.line_spacing_var, "line_spacing"),
                 (self.feed_var, "feed"), (self.bold_var, "bold"),
                 (self.underline_var, "underline"), (self.inverse_var, "inverse"),
                 (self.double_var, "double"), (self.cut_var, "cut"),
                 (self.raster_var, "raster")]
        for var, key in pairs:
            if key in s:
                try: var.set(s[key])
                except Exception: pass
        self.text_input.delete("1.0", "end")
        self.text_input.insert("1.0", item.get("text", ""))
        self._preview_changed()
        self.log_msg("Loaded into the editor", "dim")

    def _add_history(self, text, settings):
        try:
            self.library.add_history(text, settings)
        except OSError as e:
            self.log_msg(f"Could not save history: {e}", "error")
            return
        win = self._library_win
        if win is not None and win.tab == "history":
            win.refresh()

    def _watch_preview_vars(self):
        for v in (self.align_var, self.font_family_var, self.font_size_var,
                  self.line_spacing_var, self.bold_var, self.underline_var,
                  self.inverse_var, self.double_var, self.raster_var):
            v.trace_add("write", lambda *a: self._preview_changed())
        for ev in ("<KeyRelease>", "<<Paste>>", "<<Cut>>", "<<Undo>>", "<<Redo>>"):
            self.text_input.bind(ev, lambda e: self._preview_changed(), add="+")

    def _preview_changed(self):
        win = self._preview_win
        if win is not None:
            win.schedule()

    def open_preview(self):
        if not PIL_AVAILABLE:
            self.toast("Pillow missing", "Install it with:  pip install Pillow", "error")
            return
        if self._preview_win is not None:
            self._preview_win.lift(); self._preview_win.render(); return
        self._preview_win = PreviewWindow(self)

    def open_library(self, tab="templates"):
        if self._library_win is not None:
            self._library_win.lift(); self._library_win.set_tab(tab); return
        self._library_win = LibraryWindow(self, tab)

    # =================================================================
    # Everything below is the original working logic (unchanged)
    # =================================================================
    def scan_devices(self):
        self.scan_btn.config(state="disabled")
        self.log_msg("Scanning for devices (10s)…")
        def _scan():
            try:
                subprocess.run(["bluetoothctl", "--timeout", "10", "scan", "on"],
                               capture_output=True, timeout=20)
                r = subprocess.run(["bluetoothctl", "devices"],
                                   capture_output=True, text=True, timeout=5)
                devices = []
                for line in r.stdout.strip().split("\n"):
                    m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.*)", line)
                    if m: devices.append(f"{m.group(1)}  {m.group(2)}")
                self.root.after(0, lambda: self._update_device_list(devices))
            except Exception as e:
                self.root.after(0, lambda: self.log_msg(f"Scan error: {e}", "error"))
            finally:
                self.root.after(0, lambda: self.scan_btn.config(state="normal"))
        threading.Thread(target=_scan, daemon=True).start()

    def _update_device_list(self, devices):
        self.device_combo["values"] = devices
        self.log_msg(f"Found {len(devices)} device(s)", "success")
        for d in devices: self.log_msg(f"  {d}", "dim")

    def _on_device_selected(self, _evt):
        v = self.device_combo.get()
        if not v: return
        mac = v.split()[0]
        self.mac_entry.delete(0, "end"); self.mac_entry.insert(0, mac)
        if self.conn_type.get() == "classic":
            ch = find_rfcomm_channel(mac)
            self.channel_var.set(str(ch))
            self.log_msg(f"Detected SPP channel {ch}", "dim")

    def toggle_connect(self):
        if self.connection and self.connection.is_connected():
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        mac = self.mac_entry.get().strip()
        if not mac:
            self.toast("No MAC address", "Enter or select a MAC address first.", "warn")
            return
        self.connect_btn.config(state="disabled")
        self.log_msg(f"Connecting to {mac} ({self.conn_type.get()})…")
        def _worker():
            try:
                if self.conn_type.get() == "classic":
                    ch = int(self.channel_var.get() or 1)
                    conn = ClassicPrinter(mac, channel=ch)
                else:
                    conn = BLEPrinter(mac)
                conn.connect()
                self.connection = conn
                self.root.after(0, self._on_connected)
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda: self._on_connect_error(err))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_connected(self):
        self._lost = False
        self.connect_btn.config(state="normal", text="Disconnect")
        self.connect_btn.set_kind("danger")
        self._set_status(True); self.log_msg("Connected", "success")
        self.toast("Connected", self.mac_entry.get().strip(), "success")

    def _on_connect_error(self, err):
        self.connect_btn.config(state="normal")
        self._set_status(False, self._lost)
        self.log_msg(f"Connection failed: {err}", "error")
        self.toast("Connection failed", err, "error", action=("Retry", self.connect))

    def disconnect(self):
        if self.connection:
            try: self.connection.disconnect()
            except Exception as e: self.log_msg(f"Disconnect error: {e}", "error")
        self.connection = None
        self._lost = False
        self.connect_btn.config(text="Connect", state="normal")
        self.connect_btn.set_kind("primary")
        self._set_status(False); self.log_msg("Disconnected", "dim")

    def _send(self, data, label="", native_text=False):
        if not self.connection or not self.connection.is_connected():
            self.toast("Not connected", "Connect to a printer first.", "warn")
            return False
        try:
            if native_text and self.compat_var.get():
                data = data + b"\x0a\x0d\x00"
            self._sending = True
            total, step = len(data), 1024
            big = total > 4096
            self._ui(self.progress.set if big else self.progress.start,
                     *((0.0,) if big else ()))
            for i in range(0, total, step):
                self.connection.write(data[i:i + step])    # same bytes, sent in chunks
                if big:
                    self._ui(self.progress.set, min(1.0, (i + step) / total))
            self._ui(self.progress.finish)
            self.log_msg(f"Sent {len(data)} bytes {label}", "sent")
            self.toast("Sent to printer", f"{len(data)} bytes {label}".strip(),
                       "success", timeout=3000)
            return True
        except Exception as e:
            self._ui(self.progress.stop)
            self.log_msg(f"Send error: {e}", "error")
            self.toast("Send failed", str(e), "error")
            self.root.after(0, self._verify_link)
            return False
        finally:
            self._sending = False

    # ---------- Paper feed ----------
    def feed_forward(self):
        if not self.connection or not self.connection.is_connected():
            self.toast("Not connected", "Connect to a printer first.", "warn"); return
        try:
            # `\n` is LF - printer advances paper. Most compatible command.
            self.connection.write(b"\n" * 5)
            self.log_msg("Feed forward: 5 newlines sent", "sent")
        except Exception as e:
            self.log_msg(f"Feed error: {e}", "error")

    def feed_backward(self):
        if not self.connection or not self.connection.is_connected():
            self.toast("Not connected", "Connect to a printer first.", "warn"); return
        try:
            # ESC e n = print + reverse feed n lines
            self.connection.write(b"\x1b\x65\x03")
            self.log_msg("Feed backward: ESC e 3 sent", "sent")
        except Exception as e:
            self.log_msg(f"Feed error: {e}", "error")

    def _build_escpos(self, text):
        align = {"left": 0, "center": 1, "right": 2}[self.align_var.get()]
        d = bytearray()
        d += b"\x1b\x40\x1b\x74\x00"
        d += b"\x1b\x61" + bytes([align])
        d += b"\x1b\x45" + bytes([1 if self.bold_var.get() else 0])
        d += b"\x1b\x2d" + bytes([1 if self.underline_var.get() else 0])
        d += b"\x1d\x42" + bytes([1 if self.inverse_var.get() else 0])
        d += b"\x1d\x21" + bytes([0x11 if self.double_var.get() else 0x00])
        ls = max(0.5, min(4.0, float(self.line_spacing_var.get() or 1.0)))
        d += b"\x1b\x33" + bytes([int(30 * ls) & 0xFF])
        norm = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
        d += norm.encode("cp437", errors="replace")
        d += b"\r\n"
        d += b"\x1b\x45\x00\x1b\x2d\x00\x1d\x42\x00\x1d\x21\x00\x1b\x61\x00\x1b\x32"
        for _ in range(int(self.feed_var.get() or 0)): d += b"\n"
        if self.cut_var.get(): d += b"\x1d\x56\x00"
        return bytes(d)

    def _font_path(self, family):
        base = {
            "Mono":  ["/usr/share/fonts/TTF/DejaVuSansMono.ttf",
                       "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                       "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"],
            "Sans":  ["/usr/share/fonts/TTF/DejaVuSans.ttf",
                       "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                       "/usr/share/fonts/dejavu/DejaVuSans.ttf"],
            "Serif": ["/usr/share/fonts/TTF/DejaVuSerif.ttf",
                       "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                       "/usr/share/fonts/dejavu/DejaVuSerif.ttf"],
        }[family]
        for p in base:
            if os.path.exists(p): return p
        return None

    def _render_text_image(self, text):
        """Render text to the 1-bit image that gets printed.
        Single source of truth: the live preview calls this too."""
        base_size = int(self.font_size_var.get() or 20)
        size = base_size * (2 if self.double_var.get() else 1)
        bold = bool(self.bold_var.get())
        underline = bool(self.underline_var.get())
        inverse = bool(self.inverse_var.get())
        ls = max(0.5, min(4.0, float(self.line_spacing_var.get() or 1.0)))
        align = self.align_var.get()

        path = self._font_path(self.font_family_var.get())
        if path: font = ImageFont.truetype(path, size)
        else:
            try: font = ImageFont.truetype("DejaVuSansMono.ttf", size)
            except Exception: font = ImageFont.load_default()

        width = 384; max_w = width - 8
        lines = []
        for raw in text.split("\n"):
            if raw == "":
                lines.append(""); continue
            while raw:
                fit = 0
                for i in range(1, len(raw) + 1):
                    try: w = font.getlength(raw[:i])
                    except AttributeError: w = font.getsize(raw[:i])[0]
                    if w > max_w: break
                    fit = i
                if fit == 0: fit = 1
                lines.append(raw[:fit]); raw = raw[fit:]

        try:
            asc, desc = font.getmetrics()
            line_h = int((asc + desc) * ls) + 2
        except Exception:
            asc = int(size * 0.8); line_h = int(size * 1.3 * ls)

        pad = 4
        img_h = max(len(lines) * line_h + pad * 2, line_h)
        bg_color = 0 if inverse else 1
        fg_color = 1 if inverse else 0
        img = Image.new("1", (width, img_h), bg_color)
        draw = ImageDraw.Draw(img)

        y = pad
        for line in lines:
            try: lw = font.getlength(line)
            except AttributeError:
                lw = font.getsize(line)[0] if line else 0
            if align == "left": x = pad
            elif align == "center": x = max(pad, int((width - lw) / 2))
            else: x = max(pad, width - pad - int(lw))
            draw.text((x, y), line, font=font, fill=fg_color,
                      stroke_width=1 if bold else 0, stroke_fill=fg_color)
            if underline and line:
                draw.line([(x, y + asc), (x + int(lw), y + asc)],
                          fill=fg_color, width=1)
            y += line_h
        return img

    def _print_text_raster(self, text, remember=None):
        if not PIL_AVAILABLE:
            self.toast("Pillow missing", "Install it with:  pip install Pillow", "error")
            return
        if not self.connection or not self.connection.is_connected():
            self.toast("Not connected", "Connect to a printer first.", "warn"); return
        def _worker():
            try:
                img = self._render_text_image(text)
                inverse = bool(self.inverse_var.get())

                w_bytes = (img.width + 7) // 8
                d = bytearray()
                d += b"\x1b\x40\x1d\x76\x30\x00"
                d += bytes([w_bytes & 0xff, (w_bytes >> 8) & 0xff,
                             img.height & 0xff, (img.height >> 8) & 0xff])
                px = img.load()
                for yy in range(img.height):
                    row = bytearray(w_bytes)
                    for xx in range(img.width):
                        if px[xx, yy] == (1 if inverse else 0):
                            row[xx // 8] |= 0x80 >> (xx % 8)
                    d += row
                d += b"\n\n\n"
                if self.cut_var.get(): d += b"\x1d\x56\x00"
                ok = self._send(bytes(d), f"(raster text {img.width}×{img.height})")
                if ok and remember:
                    self.root.after(0, lambda: self._add_history(*remember))
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda: self.log_msg(f"Raster error: {err}", "error"))
        threading.Thread(target=_worker, daemon=True).start()

    def print_text(self):
        txt = self.text_input.get("1.0", "end-1c")
        if not txt.strip():
            self.toast("Nothing to print", "Enter some text first.", "info"); return
        snap = self._snapshot_settings()
        if self.raster_var.get(): self._print_text_raster(txt, remember=(txt, snap))
        elif self._send(self._build_escpos(txt), "(native text)", native_text=True):
            self._add_history(txt, snap)

    def print_test(self):
        if self.raster_var.get():
            self._print_text_raster(
                "*** TEST PAGE ***\n\n"
                "Hello from Python!\n"
                "BT Thermal Printer GUI\n"
                "0123456789 !@#$%^&*()\n"
                "The quick brown fox jumps\n"
                "over the lazy dog.\n\n"
                "If you can read this,\n"
                "your printer works!"
            ); return
        d = bytearray()
        d += b"\x1b\x40\x1b\x74\x00\x1b\x61\x01\x1d\x21\x11"
        d += b"*** TEST PAGE ***\r\n\r\n\x1d\x21\x00\x1b\x61\x00"
        d += b"Hello from Python!\r\n"
        d += b"BT Thermal Printer GUI\r\n"
        d += b"0123456789 !@#$%^&*()\r\n"
        d += b"The quick brown fox jumps\r\n"
        d += b"over the lazy dog.\r\n\r\n\r\n\r\n"
        if self.cut_var.get(): d += b"\x1d\x56\x00"
        self._send(bytes(d), "(test page, native)", native_text=True)

    def print_image(self):
        if not PIL_AVAILABLE:
            self.toast("Pillow missing", "Install it with:  pip install Pillow", "error")
            return
        if not self.connection or not self.connection.is_connected():
            self.toast("Not connected", "Connect to a printer first.", "warn"); return
        path = filedialog.askopenfilename(
            title="Select image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif"), ("All", "*.*")])
        if not path: return
        editor = ImageEditor(self.root, path)
        self.root.wait_window(editor)
        if editor.result is None: return
        self._send_processed_image(editor.result)

    def _send_processed_image(self, img):
        try:
            w_bytes = (img.width + 7) // 8
            h = img.height
            d = bytearray()
            d += b"\x1b\x40\x1d\x76\x30\x00"
            d += bytes([w_bytes & 0xff, (w_bytes >> 8) & 0xff,
                         h & 0xff, (h >> 8) & 0xff])
            px = img.load()
            for y in range(h):
                row = bytearray(w_bytes)
                for x in range(img.width):
                    if px[x, y] == 0: row[x // 8] |= 0x80 >> (x % 8)
                d += row
            d += b"\n\n\n"
            if self.cut_var.get(): d += b"\x1d\x56\x00"
            self._send(bytes(d), f"(image {img.width}×{h})")
        except Exception as e:
            self.log_msg(f"Image send error: {e}", "error")

    def print_raw(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Send Raw Hex"); dlg.geometry("580x400")
        dlg.configure(bg=C["bg"]); dlg.transient(self.root); dlg.grab_set()
        body = themed(tk.Frame(dlg), bg="bg")
        body.pack(fill="both", expand=True, padx=34, pady=(28, 26))
        themed(tk.Label(body, text="raw hex", font=F_H2, anchor="w"),
                fg="text", bg="bg").pack(anchor="w")
        themed(tk.Label(body, text="Space-separated or continuous hex bytes", font=F_SUB),
                fg="text_muted", bg="bg").pack(anchor="w", pady=(0, 14))
        box, txt, _sb = make_textarea(body, height=6, font=F_MONO, width=20)
        box.pack(fill="both", expand=True)
        btn_row = themed(tk.Frame(body), bg="bg"); btn_row.pack(fill="x", pady=(20, 0))
        def _go():
            raw = (txt.get("1.0", "end").strip()
                   .replace(" ", "").replace("\n", "").replace("0x", ""))
            try: data = bytes.fromhex(raw)
            except ValueError as e:
                messagebox.showerror("Invalid hex", str(e)); return
            if self._send(data, "(raw)"): dlg.destroy()
        MetroButton(btn_row, "Send", _go, kind="primary", padx=34).pack(side="right")
        MetroButton(btn_row, "Cancel", dlg.destroy).pack(side="right", padx=(0, 10))


def main():
    root = tk.Tk()
    PrinterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()