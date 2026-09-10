import ctypes
import datetime
import json
import sys
import tkinter as tk
import traceback
from ctypes import wintypes
from pathlib import Path


# ---------------------------------------------------------------------------
# Rate schedule (exact spec):
# Peak = 01:00-04:00 and 06:00-10:00 UTC, Monday-Friday (UTC day).
# All other hours are off-peak. No holiday exceptions.
# ---------------------------------------------------------------------------


def is_peak(now_utc: datetime.datetime) -> bool:
    hour = now_utc.hour
    if not ((1 <= hour < 4) or (6 <= hour < 10)):
        return False
    return now_utc.weekday() < 5


def next_switch(now_utc: datetime.datetime):
    """Return (switch_time, target_state) for the next peak/off-peak boundary."""
    current = is_peak(now_utc)
    day0 = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    for days in range(0, 8):
        day = day0 + datetime.timedelta(days=days)
        for h in (1, 4, 6, 10):
            cand = day + datetime.timedelta(hours=h)
            if cand > now_utc and is_peak(cand) != current:
                return cand, "PEAK" if is_peak(cand) else "OFF-PEAK"
    return None, None


def fmt_countdown(delta: datetime.timedelta) -> str:
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# ---------------------------------------------------------------------------
# Windows plumbing
# ---------------------------------------------------------------------------

OFF_BG = "#2e9e4f"
ON_BG = "#c94436"
FG = "#ffffff"
DEFAULT_POS = (40, 40)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "OffPeakClock"

_instance_mutex = None


def _claim_single_instance() -> bool:
    """Return False if another OffPeakClock instance is already running."""
    global _instance_mutex
    try:
        _instance_mutex = ctypes.windll.kernel32.CreateMutexW(
            None, False, "OffPeakClock")
        return (bool(_instance_mutex)
                and ctypes.windll.kernel32.GetLastError() != 183)
    except Exception:
        return True


def config_path() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    return base / "offpeak_clock.json"


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _clamp_pos(pos) -> tuple:
    """Validate + keep the window inside the monitor nearest to the saved spot."""
    try:
        x, y = int(pos[0]), int(pos[1])
    except Exception:
        return DEFAULT_POS
    try:
        hmon = ctypes.windll.user32.MonitorFromPoint(wintypes.POINT(x, y), 2)
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return DEFAULT_POS
        work = info.rcWork
    except Exception:
        return DEFAULT_POS
    m = 24
    if work.right - work.left <= 2 * m or work.bottom - work.top <= 2 * m:
        return work.left + m, work.top + m
    return (min(max(x, work.left + m), work.right - m),
            min(max(y, work.top + m), work.bottom - m))


def _autostart_enabled() -> bool:
    try:
        key = wintypes.HKEY()
        if ctypes.windll.advapi32.RegOpenKeyExW(0x80000001, RUN_KEY, 0, 0x0001,
                                                ctypes.byref(key)):
            return False
        try:
            size = wintypes.DWORD(2048)
            return ctypes.windll.advapi32.RegQueryValueExW(
                key, RUN_VALUE, None, None, None, ctypes.byref(size)) == 0
        finally:
            ctypes.windll.advapi32.RegCloseKey(key)
    except Exception:
        return False


def _set_autostart(enabled: bool) -> bool:
    try:
        key = wintypes.HKEY()
        if ctypes.windll.advapi32.RegOpenKeyExW(0x80000001, RUN_KEY, 0, 0x0002,
                                                ctypes.byref(key)):
            return False
        try:
            if enabled:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    cmd = f'"{sys.executable}" "{Path(__file__).resolve()}"'
                ctypes.windll.advapi32.RegSetValueExW(
                    key, RUN_VALUE, 0, 1, cmd, (len(cmd) + 1) * 2)
            else:
                ctypes.windll.advapi32.RegDeleteValueW(key, RUN_VALUE)
        finally:
            ctypes.windll.advapi32.RegCloseKey(key)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class PeakClock:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._after_id = None
        self._save_job = None
        self._closing = False
        self._dragging = False
        self._drag_off = (0, 0)

        cfg = self._load_config()
        self.topmost = tk.BooleanVar(value=cfg.get("topmost", True))
        self.autostart = tk.BooleanVar(value=_autostart_enabled())
        x, y = _clamp_pos(cfg.get("pos", DEFAULT_POS))

        root.title("Peak Clock")
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.overrideredirect(True)
        root.attributes("-topmost", self.topmost.get())
        root.geometry(f"+{x}+{y}")
        root.attributes("-alpha", 0.92)

        self.label = tk.Label(
            root,
            font=("Consolas", 10, "bold"),
            fg=FG,
            padx=8,
            pady=4,
        )
        self.label.pack(fill="both", expand=True)

        self.menu = tk.Menu(root, tearoff=False)
        self.menu.add_checkbutton(label="Always on top", variable=self.topmost,
                                  command=self._apply_topmost)
        self.menu.add_checkbutton(label="Start with Windows", variable=self.autostart,
                                  command=self._apply_autostart)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self.quit)

        root.bind("<Button-1>", self._start_drag)
        root.bind("<B1-Motion>", self._on_drag)
        root.bind("<ButtonRelease-1>", self._end_drag)
        root.bind("<Button-3>", self._popup)

        root.bind("<Escape>", self.quit)
        root.bind("<Alt-F4>", self.quit)

        self.refresh()

    def _load_config(self) -> dict:
        try:
            cfg = json.loads(config_path().read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                return {}
            pos = cfg.get("pos")
            if not (isinstance(pos, (list, tuple)) and len(pos) == 2
                    and all(isinstance(v, (int, float)) for v in pos)):
                cfg.pop("pos", None)
            for key in ("topmost",):
                if key in cfg and not isinstance(cfg[key], bool):
                    cfg.pop(key, None)
            # Drop legacy keys from pre-exact-spec versions.
            for key in ("holidays_off", "holidays", "holiday_rules"):
                cfg.pop(key, None)
            return cfg
        except Exception:
            return {}

    def _save_config(self):
        try:
            cfg = {}
            try:
                cfg = json.loads(config_path().read_text(encoding="utf-8"))
                if not isinstance(cfg, dict):
                    cfg = {}
            except Exception:
                cfg = {}
            cfg.update({
                "pos": (self.root.winfo_x(), self.root.winfo_y()),
                "topmost": bool(self.topmost.get()),
            })
            # Drop legacy keys from pre-exact-spec versions.
            for key in ("holidays_off", "holidays", "holiday_rules"):
                cfg.pop(key, None)
            config_path().write_text(json.dumps(cfg), encoding="utf-8")
        except Exception:
            pass

    def _schedule_save(self):
        if self._save_job is not None:
            try:
                self.root.after_cancel(self._save_job)
            except tk.TclError:
                pass
        self._save_job = self.root.after(300, self._save_config)

    def _apply_topmost(self):
        self.root.attributes("-topmost", self.topmost.get())
        self._schedule_save()

    def _apply_autostart(self):
        if not _set_autostart(self.autostart.get()):
            self.autostart.set(not self.autostart.get())

    def _popup(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _start_drag(self, event):
        self._dragging = True
        self._drag_off = (event.x_root - self.root.winfo_x(),
                          event.y_root - self.root.winfo_y())

    def _on_drag(self, event):
        self.root.geometry(f"+{event.x_root - self._drag_off[0]}+{event.y_root - self._drag_off[1]}")

    def _end_drag(self, event):
        self._dragging = False
        self._schedule_save()

    def quit(self, _event=None):
        if self._closing:
            return
        self._closing = True
        self._save_config()
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _fit_window(self):
        if self._dragging:
            return
        self.root.update_idletasks()
        w = self.label.winfo_reqwidth()
        h = self.label.winfo_reqheight()
        self.root.geometry(f"{w}x{h}+{self.root.winfo_x()}+{self.root.winfo_y()}")

    def refresh(self):
        self._after_id = None
        if self._closing:
            return
        try:
            if not self.root.winfo_exists():
                return
            now = datetime.datetime.now(datetime.timezone.utc)
            peak = is_peak(now)
            bg = ON_BG if peak else OFF_BG
            self.root.configure(bg=bg)
            self.label.configure(bg=bg, fg=FG)
            status = "PEAK" if peak else "OFF-PEAK"
            local = now.astimezone()
            switch, target = next_switch(now)
            countdown = ""
            if switch is not None:
                delta = switch - now
                countdown = f"  \u2192 {target} in {fmt_countdown(delta)} ({switch.astimezone().strftime('%a %H:%M')} local)"
            self.label.configure(
                text=f"{now.strftime('%Y-%m-%d %H:%M:%S')} UTC  |  {local.strftime('%H:%M')} local\n{status}{countdown}"
            )
            self._fit_window()
        except Exception:
            traceback.print_exc()
        finally:
            if not self._closing:
                try:
                    delay = 1000 - (datetime.datetime.now().microsecond // 1000)
                    if delay < 50:
                        delay += 1000
                    self._after_id = self.root.after(delay, self.refresh)
                except tk.TclError:
                    self._after_id = None


if __name__ == "__main__":
    if not _claim_single_instance():
        sys.exit(0)
    enable_dpi_awareness()
    root = tk.Tk()
    PeakClock(root)
    root.mainloop()