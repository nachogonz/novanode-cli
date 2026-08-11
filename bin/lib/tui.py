import curses
import threading
import time

import config as nnconfig
import usage as usage_lib
from doctor import run_doctor
from pbx import PBX
from phone import Phone


TABS = ["USAGE", "PBX", "PHONE", "CALLS", "TRUNKS", "DEBUG"]

ORANGE = 208
GREEN = 82
RED = 196
CYAN = 51
WHITE = 231
DIM = 245
BOLD_YELLOW = 220


def fmt_duration(seconds):
    total = int(seconds)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def fmt_uptime(seconds):
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def draw_box(win, y, x, h, w, title=""):
    try:
        win.vline(y, x, curses.ACS_VLINE, h)
        win.vline(y, x + w - 1, curses.ACS_VLINE, h)
        win.hline(y, x, curses.ACS_HLINE, w)
        win.hline(y + h - 1, x, curses.ACS_HLINE, w)
        win.addch(y, x, curses.ACS_ULCORNER)
        win.addch(y, x + w - 1, curses.ACS_URCORNER)
        win.addch(y + h - 1, x, curses.ACS_LLCORNER)
        win.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
        if title:
            win.addnstr(y, x + 2, f" {title} ", w - 4)
    except curses.error:
        pass


def progress_bar(width, pct, color):
    pct = max(0.0, min(100.0, pct or 0.0))
    filled = int(round(pct / 100.0 * width))
    return [
        (color, "█" * filled),
        (DIM, "░" * (width - filled)),
    ]


class App:
    def __init__(self, stdscr, start_tab="USAGE"):
        self.stdscr = stdscr
        self.tab = start_tab if start_tab in TABS else TABS[0]
        self.cfg = nnconfig.load_config()
        self.pbx = PBX(self.cfg)
        self.phone = Phone(self.cfg)
        self.usage_rows = []
        self.usage_ts = 0
        self.usage_loading = False
        self.usage_thread = None
        self.phone_started = False
        self.last_refresh = 0
        self.status = ""
        self.status_color = DIM
        self.key_message = ""
        self.key_message_ts = 0
        self.last_tick = 0
        self.incoming_timer = 0.0
        self.done = False
        self.log = []
        self.ami_attempted = False
        self.cached_transports = []
        self.cached_endpoints = []
        self.cached_channels = []
        self.cached_registrations = []
        self.cached_context = []
        self.cached_version = "n/a"
        self.cached_uptime = 0
        self.cached_events = []
        self.pbx_thread = None
        self.cached_eps_ts = 0

    # ── helpers ──────────────────────────────────────────────────
    def log_line(self, text):
        self.log.append(text)
        if len(self.log) > 200:
            del self.log[:-200]

    def flash(self, text, color=GREEN):
        self.key_message = text
        self.key_message_ts = time.monotonic()
        self.status_color = color

    def cp(self, n):
        if not self.color_ok:
            return 0
        try:
            pair = {
                ORANGE: 1,
                GREEN: 2,
                RED: 3,
                CYAN: 4,
                WHITE: 5,
                DIM: 6,
                BOLD_YELLOW: 7,
            }.get(n, n if 1 <= n <= 7 else 0)
            return curses.color_pair(pair)
        except Exception:
            return 0

    def ensure_phone(self):
        if not self.phone_started:
            self.phone.start()
            self.phone_started = True
            self.flash(self.phone.last_event or "phone ready")

    def ensure_pbx(self):
        p = self.cfg["pbx"]
        now = time.monotonic()
        if self.pbx.connected:
            self.cached_events.extend(self.pbx.recent_events())
            self.cached_events = self.cached_events[-500:]
        if now - self.cached_eps_ts <= 5 or (self.pbx_thread and self.pbx_thread.is_alive()):
            return
        self.cached_eps_ts = now

        def poll():
            try:
                self.cached_transports = self.pbx.transports()
                self.cached_endpoints = self.pbx.endpoints_long()
                self.cached_channels = self.pbx.channels()
                self.cached_registrations = self.pbx.registrations()
                self.cached_context = self.pbx.contexts("from-nn")
                self.cached_version = self.pbx.core_version()
                self.cached_uptime = self.pbx.uptime_seconds()
                if self.cached_version != "n/a":
                    self.status = f"{p['name']} · {self.cached_version}"
                    self.status_color = GREEN
                else:
                    self.status = "PBX unavailable; run `nn pbx doctor`"
                    self.status_color = RED
            except Exception as e:
                self.status = f"poll: {e}"
                self.status_color = RED
            if self.pbx.connected:
                self.status = f"AMI up {p['host']} · {fmt_uptime(self.cached_uptime)} uptime"
                self.status_color = GREEN

        self.pbx_thread = threading.Thread(target=poll, daemon=True)
        self.pbx_thread.start()

    # ── loop ─────────────────────────────────────────────────────
    def run(self):
        curses.curs_set(0)
        self.color_ok = curses.has_colors()
        if self.color_ok:
            curses.start_color()
        for pair_id, fg in enumerate((ORANGE, GREEN, RED, CYAN, WHITE, DIM, BOLD_YELLOW), 1):
            if self.color_ok:
                try:
                    curses.init_pair(pair_id, fg, -1)
                except curses.error:
                    pass
        self.stdscr.nodelay(True)
        self.stdscr.keypad(True)
        try:
            while not self.done:
                now = time.monotonic()
                if now - self.last_refresh > 1.0:
                    self.last_refresh = now
                    self.tick()
                self.render()
                key = self.stdscr.getch()
                if key != -1:
                    self.handle_key(key)
                time.sleep(0.04)
        finally:
            if self.phone_started:
                self.phone.stop()
            self.pbx.close()

    def tick(self):
        if self.tab == "PHONE":
            self.ensure_phone()
            self.phone.tick()
        if self.tab in ("PBX", "CALLS", "TRUNKS", "DEBUG"):
            self.ensure_pbx()
        now = time.monotonic()
        if self.tab == "USAGE" and now - self.usage_ts > 15 and not self.usage_loading:
            self.start_usage_fetch()
        if self.phone_started and self.phone._simulated and self.phone.state in (Phone.STATE_IDLE, Phone.STATE_REGISTERED) and now - self.incoming_timer > 12:
            self.incoming_timer = now
            self.phone.simulate_incoming()
            self.flash("incoming call", CYAN)

    def start_usage_fetch(self):
        if self.usage_thread and self.usage_thread.is_alive():
            return
        self.usage_loading = True
        self.usage_ts = time.monotonic()

        def fetch():
            try:
                self.usage_rows = usage_lib.fetch_usage()
            except Exception:
                self.usage_rows = []
            finally:
                self.usage_loading = False

        self.usage_thread = threading.Thread(target=fetch, daemon=True)
        self.usage_thread.start()

    # ── key handling ─────────────────────────────────────────────
    def handle_key(self, key):
        if self.phone.state == Phone.STATE_INCOMING and key in (ord("a"), ord("A")):
            self.phone.answer()
            return
        if self.phone.state == Phone.STATE_INCOMING and key in (ord("d"), ord("D")):
            self.phone.hangup()
            self.flash("call declined")
            self.phone.sim_timer = 0.0
            return
        if key == ord("\t"):
            self.tab = TABS[(TABS.index(self.tab) + 1) % len(TABS)]
            if self.tab == "PHONE":
                self.ensure_phone()
            return
        if key == ord("q") or key == ord("Q"):
            self.done = True
            return
        if key == ord("1") and self.tab != "PHONE":
            self.tab = TABS[0]
            return
        if key == ord("2") and self.tab != "PHONE":
            self.tab = TABS[1]
            return
        if key == ord("3"):
            self.tab = TABS[2]
            self.ensure_phone()
            return
        if key == ord("4") and self.tab != "PHONE":
            self.tab = TABS[3]
            return
        if key == ord("5") and self.tab != "PHONE":
            self.tab = TABS[4]
            return
        if key == ord("6") and self.tab != "PHONE":
            self.tab = TABS[5]
            return
        if key == curses.KEY_F5:
            self.refresh_now()
            return
        if key == curses.KEY_F4:
            self.try_connect_ami()
            return

        if self.tab == "PHONE":
            self.handle_phone_key(key)
        else:
            self.handle_global_key(key)

    def handle_global_key(self, key):
        r = key & 0xFF
        if chr(r) in ("r", "R") and self.tab in ("PBX", "CALLS", "TRUNKS", "DEBUG"):
            self.refresh_now()
        elif chr(r) == "h":
            self.flash("Tab switch · r refresh · F5 refresh now · q quit")

    def handle_phone_key(self, key):
        if key == ord("\n") or key == ord("\r"):
            self.phone.dial()
            return
        if key == ord("\x7f") or key == 263 or key == 127:
            if self.phone.dial_buffer:
                self.phone.dial_buffer = self.phone.dial_buffer[:-1]
            return
        if key == 27:  # ESC clears dial buffer
            self.phone.dial_buffer = ""
            return
        if key in (ord("c"), ord("C")):
            self.phone.dial()
            return
        if key in (ord("h"), ord("H")):
            self.phone.hangup()
            return
        if key in (ord("m"), ord("M")):
            self.phone.toggle_mic()
            return
        if key in (ord("s"), ord("S")):
            self.phone.toggle_audio()
            return
        char = chr(key & 0xFF) if 0 <= (key & 0xFF) < 256 else ""
        if char in "0123456789*#+":
            self.phone.dial_buffer += char
            self.phone.last_event = f"digit {char}"

    def refresh_now(self):
        self.flash("refreshing…", CYAN)
        if self.tab == "USAGE":
            self.start_usage_fetch()
        self.cached_eps_ts = 0

    def try_connect_ami(self):
        p = self.cfg["pbx"]
        if self.pbx.connect_ami():
            self.flash("AMI tunnel up — live events", GREEN)
        else:
            self.flash(f"AMI: {self.pbx.last_error}", RED)

    # ── render ───────────────────────────────────────────────────
    def render(self):
        std = self.stdscr
        try:
            h, w = std.getmaxyx()
        except Exception:
            return
        std.erase()
        if h < 18 or w < 60:
            try:
                std.addnstr(0, 0, "Resize terminal to at least 60x18", max(1, w - 1), curses.A_BOLD)
                std.refresh()
            except curses.error:
                pass
            return

        subtitle = nnconfig.pbx_label(self.cfg)
        brand = " NOVANODE "
        version = " v TUI "
        y = 0
        std.addnstr(y, 0, " " * w, w, self.cp(6))
        std.addnstr(y, 0, brand, len(brand), curses.A_BOLD | self.cp(6))
        std.addnstr(y, len(brand), f"{version}", len(version), self.cp(6))
        right = subtitle
        std.addnstr(y, max(0, w - len(right) - 1), right, w, curses.A_BOLD | self.cp(1))
        y += 1

        tab_y = y
        x = 0
        for idx, t in enumerate(TABS):
            selected = t == self.tab
            label = f" {t} "
            if selected:
                std.addnstr(tab_y, x, label, w, curses.A_REVERSE | curses.A_BOLD | self.cp(2))
            else:
                std.addnstr(tab_y, x, label, w, self.cp(6))
            x += len(label)
        if self.phone.registered and self.phone.state != Phone.STATE_IDLE:
            badge = f" ● {self.phone.state}"
            std.addnstr(tab_y, max(0, len(brand) + 10), badge, w, self.cp(6))
        y += 1

        content_h = h - y - 3
        if self.tab == "USAGE":
            self.render_usage(y, max(1, content_h), w)
        elif self.tab == "PBX":
            self.render_pbx(y, max(1, content_h), w)
        elif self.tab == "PHONE":
            self.render_phone(y, max(1, content_h), w)
        elif self.tab == "CALLS":
            self.render_calls(y, max(1, content_h), w)
        elif self.tab == "TRUNKS":
            self.render_trunks(y, max(1, content_h), w)
        elif self.tab == "DEBUG":
            self.render_debug(y, max(1, content_h), w)

        status_y = h - 3
        std.addnstr(status_y, 0, " " * w, w, self.cp(6))
        meta = ""
        if self.phone.registered:
            meta = f"ext {self.phone.extension}"
        if self.phone.state == Phone.STATE_IN_CALL:
            meta += f" · call {self.phone.remote} {self.phone.duration_str()}"
        std.addnstr(status_y, 0, meta or "idle", w, self.cp(6))
        status = self.status
        if self.key_message and time.monotonic() - self.key_message_ts < 6:
            status = self.key_message
        std.addnstr(status_y, max(0, w - len(status) - 1), status, w, self.cp(self.status_color))

        hint_y = h - 2
        std.addnstr(hint_y, 0, " " * w, w, self.cp(6))
        if self.tab == "PHONE":
            hint = "1-9,*,# pad · Enter dial · c call · h hang · m mic · s audio · Tab next · q quit"
        else:
            hint = "Tab next · 1-6 jump · r refresh · F5 refresh now · q quit"
        std.addnstr(hint_y, 0, hint, w, self.cp(6))
        y = h - 1
        dots = "─" * max(0, w - 2)
        std.addnstr(y, 0, f"╰{dots}"[: max(1, w - 1)], max(1, w - 1), self.cp(1))
        std.refresh()

    # ── usage tab ────────────────────────────────────────────────
    def render_usage(self, y0, height, width):
        std = self.stdscr
        draw_box(std, y0, 0, min(height, 6), width - 2, " USAGE ")
        self._draw_usage_cards(y0 + 1, width - 4)
        self._draw_totals(y0, height)

    def _draw_cell(self, y, x, width):
        std = self.stdscr
        draw_box(std, y, x, 5, width, "")

    def _draw_usage_cards(self, y0, width):
        std = self.stdscr
        rows = self.usage_rows
        n_providers = len(rows)
        margin = 2
        gap = 2
        if n_providers == 0:
            card_w = width - 2 * margin
        else:
            card_w = (width - 2 * margin - gap * (n_providers - 1)) // n_providers
        card_w = max(24, min(card_w, 48))
        x = margin
        for idx, p in enumerate(rows):
            self._render_usage_card(y0, x, card_w, p)
            x += card_w + gap

        extras_x = margin + n_providers * (card_w + gap)
        if n_providers == 0:
            std.addnstr(y0 + 1, margin, " No usage data — run `nn-usage` once to populate.", width, self.cp(6))

    def _render_usage_card(self, y0, x, w, p):
        std = self.stdscr
        name = {"claude": "Claude Code", "codex": "Codex CLI"}.get(p["key"], p["key"])
        draw_box(std, y0, x, 8, w, name)
        ver = p["version"] or "not detected"
        std.addnstr(y0 + 1, x + 2, f"v{ver}", w - 4, self.cp(6))
        model = "—"
        row = 2
        for label, used, reset in ((p["p1"], p["used1"], p["reset1"]), (p["p2"], p["used2"], p["reset2"])):
            if label in ("n/a", "", "—"):
                continue
            pct = usage_lib.pct_num(used)
            color = GREEN if (pct is not None and pct < 100) else RED
            pad_w = w - 6
            bar = "".join(c for _, c in progress_bar(pad_w, pct, color))
            std.addnstr(y0 + row, x + 2, f"{label:<8} ", w - 4, self.cp(6))
            std.addnstr(y0 + row, x + 2 + 9, bar[:pad_w] + " " + (f"{used}%" if "%" not in str(used) else str(used)), w - 4, self.cp(color))
            row += 1

    def _draw_totals(self, y0, height):
        std = self.stdscr
        if not self.usage_rows:
            return
        pcts = []
        for p in self.usage_rows:
            for used in (p["used1"], p["used2"]):
                v = usage_lib.pct_num(used)
                if v is not None:
                    pcts.append(v)
        if not pcts:
            return
        avg = sum(pcts) / len(pcts)
        left = 100 - avg
        y = y0 + 9
        draw_box(std, y, 2, 2, min(60, self.stdscr.getmaxyx()[1] - 6), " TOTAL ")
        bar = "".join(c for _, c in progress_bar(40, avg, ORANGE if avg < 100 else RED))
        std.addnstr(y + 1, 4, f"{bar}  {avg:.0f}% avg · {left:.0f}% left", self.stdscr.getmaxyx()[1] - 6, self.cp(1))

    # ── pbx tab ──────────────────────────────────────────────────
    def render_pbx(self, y0, height, width):
        std = self.stdscr
        cfg = self.cfg
        b = self.pbx
        live = bool(cfg.get("pbx", {}).get("ssh_host"))
        draw_box(std, y0, 0, min(height, 8), width - 2, f" PBX · {nnconfig.pbx_label(cfg)} ")
        if live:
            std.addnstr(y0 + 1, 2, "● live (ssh -rx)", width - 12, self.cp(2))
            version = self.cached_version
            std.addnstr(y0 + 1, 18, f"asterisk {version}", max(8, width - 22), self.cp(6))
            up = self.cached_uptime
            std.addnstr(y0 + 1, max(2, width - 30), f"uptime {fmt_uptime(up)}", width - 4, self.cp(6))
            chans = len(self.cached_channels)
            eps = self.cached_endpoints
            std.addnstr(y0 + 3, 2, f"{len(eps)} endpoints", width - 16, self.cp(6))
            std.addnstr(y0 + 3, 24, f"{len(self.cached_transports)} transports", width - 38, self.cp(6))
            std.addnstr(y0 + 3, 44, f"{chans} active channels", width - 46, self.cp(6))
            self._render_endpoints(y0 + 5, height - 5, width)
        else:
            std.addnstr(y0 + 1, 2, "○ not configured", width - 18, self.cp(1))
            std.addnstr(y0 + 2, 2, "run `nn pbx setup` to detect the Fedora box", width - 4, self.cp(6))
            std.addnstr(y0 + 3, 2, "then `nn pbx doctor` for the six-section report", width - 4, self.cp(6))

    def _render_endpoints(self, y0, height, width):
        std = self.stdscr
        eps = self.cached_endpoints
        if not eps:
            return
        rows = min(6, len(eps))
        draw_box(std, y0, 0, rows + 3, width - 2, " ENDPOINTS ")
        y = y0 + 1
        for ep in eps[:rows]:
            name = ep.get("name", "?")
            user = ep.get("username") or ""
            state = ep.get("state") or ""
            line = f"{name:<14} {user:<10} {state}"
            std.addnstr(y, 2, line, width - 4, self.cp(6))
            y += 1

    # ── phone tab ────────────────────────────────────────────────
    def render_phone(self, y0, height, width):
        std = self.stdscr
        ph = self.phone
        cfg = self.cfg["phone"]
        left_w = min(34, width // 2 - 3)
        right_x = left_w + 2

        draw_box(std, y0, 0, min(height, 10), left_w, f" NOVA PHONE ")
        state_color = GREEN if ph.registered else (RED if ph.state == Phone.STATE_ERROR else DIM)
        std.addnstr(y0 + 1, 2, f"{((ph.display_name or 'NOVA PHONE')[:22]):<22}", left_w - 4, curses.A_BOLD | self.cp(2))
        std.addnstr(y0 + 2, 2, f"extension  {ph.extension}", left_w - 4, self.cp(6))
        number = ph.dial_buffer or ph.remote
        std.addnstr(y0 + 3, 2, f" {number:<22}", left_w - 4, curses.A_BOLD | self.cp(7))

        keys = ["1 2 3", "4 5 6", "7 8 9", "* 0 #"]
        ky = y0 + 4
        for row in keys:
            std.addnstr(ky, 2, row, left_w - 4, self.cp(6))
            ky += 1

        state_label = {
            Phone.STATE_IDLE: "idle",
            Phone.STATE_DIALING: "dialing",
            Phone.STATE_RINGING: "ringing",
            Phone.STATE_IN_CALL: "in call",
            Phone.STATE_INCOMING: "incoming",
            Phone.STATE_REGISTERING: "registering",
            Phone.STATE_REGISTERED: "registered",
            Phone.STATE_ERROR: "error",
        }[ph.state]
        std.addnstr(y0 + 9, 2, f"● {state_label}", left_w - 4, self.cp(state_color))

        if ph._simulated:
            std.addnstr(y0 + 3, left_w - 9, "(sim)", 6, self.cp(RED))

        # call trace / metr heals right panel
        if right_x + 30 < width:
            rw = width - right_x - 2
            draw_box(std, y0, right_x, min(height, 20), rw, " CALL TRACE ")
            y = y0 + 1
            if ph.state in (Phone.STATE_IN_CALL, Phone.STATE_RINGING, Phone.STATE_DIALING, Phone.STATE_INCOMING) and ph.remote:
                std.addnstr(y, right_x + 2, f"SIP   ● {'CONNECTED' if ph.state == Phone.STATE_IN_CALL else ph.state.upper()}", rw - 4, self.cp(2 if ph.state == Phone.STATE_IN_CALL else 6))
                y += 1
                std.addnstr(y, right_x + 2, f"RTP   ● {'STREAMING' if ph.state == Phone.STATE_IN_CALL else 'idle'}", rw - 4, self.cp(2 if ph.state == Phone.STATE_IN_CALL else 6))
                y += 1
                std.addnstr(y, right_x + 2, f"Codec {ph.codec}", rw - 4, self.cp(6))
                y += 1
                jitter = f"{ph.jitter_ms:.1f} ms" if ph.jitter_ms is not None else "n/a"
                std.addnstr(y, right_x + 2, f"Jitter {jitter}", rw - 4, self.cp(6))
                y += 1
                loss = f"{ph.loss_pct:.1f}%" if ph.loss_pct is not None else "n/a"
                std.addnstr(y, right_x + 2, f"Loss  {loss}", rw - 4, self.cp(6))
                y += 1
                std.addnstr(y, right_x + 2, f"Duration {ph.duration_str()}", rw - 4, self.cp(7))
            elif ph.state == Phone.STATE_IDLE:
                std.addnstr(y, right_x + 2, "no active call", rw - 4, self.cp(6))
                y += 1
                std.addnstr(y, right_x + 2, "type digits + Enter to dial", rw - 4, self.cp(6))
                y += 1
                std.addnstr(y, right_x + 2, "or wait for an incoming call", rw - 4, self.cp(6))
            elif ph.state == Phone.STATE_REGISTERING:
                std.addnstr(y, right_x + 2, "registering…", rw - 4, self.cp(6))
            elif ph.state == Phone.STATE_DIALING:
                std.addnstr(y, right_x + 2, f"dialing {ph.remote}…", rw - 4, self.cp(6))
            y += 1
            if ph._simulated:
                std.addnstr(y, right_x + 2, "simulated endpoint · no SIP client", rw - 4, self.cp(1))

        # bottom bar mic/audio
        y = y0 + 11
        mic = "MIC ●" if not ph.mic_muted else "MIC ○"
        mic_color = GREEN if not ph.mic_muted else RED
        std.addnstr(y, 2, mic, 7, self.cp(mic_color))
        std.addnstr(y, 10, "AUDIO" + (" ●" if ph.audio_on else " ○"), 9, self.cp(GREEN if ph.audio_on else RED))
        std.addnstr(y, 20, f"Duration {ph.duration_str()}", 18, self.cp(6))
        self._draw_incoming_overlay()

    def _draw_incoming_overlay(self):
        if self.phone.state != Phone.STATE_INCOMING:
            return
        std = self.stdscr
        h, w = std.getmaxyx()
        box_h, box_w = 7, 44
        y = h // 2 - box_h // 2
        x = w // 2 - box_w // 2
        draw_box(std, y, x, box_h, box_w, " INCOMING CALL ")
        std.addnstr(y + 1, x + 2, f"{self.phone.incoming_caller}", box_w - 4, curses.A_BOLD | self.cp(7))
        std.addnstr(y + 3, x + 2, "[A] Answer      [D] Decline", box_w - 4, self.cp(6))

    # ── calls ────────────────────────────────────────────────────
    def render_calls(self, y0, height, width):
        std = self.stdscr
        draw_box(std, y0, 0, min(height, 7), width - 2, " CALLS ")
        chans = self.cached_channels
        if chans:
            y = y0 + 1
            std.addnstr(y, 2, "channel            state        caller →  exten      dur", width - 4, curses.A_BOLD | self.cp(6))
            for c in chans[: max(0, min(20, height - 3))]:
                y += 1
                row = f"{c['channel'][:18]:<18} {c['state'][:12]:<12} {c['caller']:>6} → {c['exten']:>6}  {c['duration']}s"
                std.addnstr(y, 2, row, width - 4, self.cp(6))
        else:
            std.addnstr(y0 + 1, 2, "no active channels", width - 4, self.cp(6))

    # ── trunks ───────────────────────────────────────────────────
    def render_trunks(self, y0, height, width):
        std = self.stdscr
        draw_box(std, y0, 0, min(height, 7), width - 2, " TRUNKS ")
        regs = self.cached_registrations
        if regs:
            y = y0 + 1
            for r in regs[: max(0, min(20, height - 3))]:
                state = r.get("state") or ""
                first_state = state.split()[0] if state.split() else ""
                color = GREEN if first_state == "Registered" else (RED if first_state in ("Failed", "Rejected") else ORANGE)
                std.addnstr(y, 2, f"{r['obj']:<18}  {r['state']:<44}", width - 4, self.cp(color))
                y += 1
        else:
            std.addnstr(y0 + 1, 2, "no outbound registrations returned", width - 4, self.cp(6))

    # ── debug ────────────────────────────────────────────────────
    def render_debug(self, y0, height, width):
        std = self.stdscr
        draw_box(std, y0, 0, min(height, 10), width - 2, " DEBUG ")
        y = y0 + 1
        p = self.cfg["pbx"]
        std.addnstr(y, 2, f"adapter ssh -rx @ {p.get('ssh_host') or p['host']}", width - 4, self.cp(6))
        y += 1
        if self.pbx.connected:
            events = self.cached_events
            std.addnstr(y, 2, f"AMI events — {len(events)} buffered (live)", width - 4, self.cp(6))
            start = max(0, len(events) - (height - y - 2))
            for ev in events[start:]:
                y += 1
                line = f"{ev.get('Event','')} {ev.get('ChannelStateDesc', ev.get('State',''))}"
                std.addnstr(y, 2, line, width - 4, self.cp(2))
        else:
            std.addnstr(y, 2, "press F4 to enable AMI tunnel (loopback 5038) for events", width - 4, self.cp(6))
            try:
                ctx = self.cached_context
                if ctx:
                    y += 1
                    std.addnstr(y, 2, "dialplan [from-nn] present — first test: dial 3000 → LiveKit", width - 4, self.cp(6))
            except Exception:
                pass


def run_tui(stdscr, start_tab="USAGE"):
    App(stdscr, start_tab).run()
    return 0
