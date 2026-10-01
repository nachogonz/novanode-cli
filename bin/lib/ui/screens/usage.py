"""Textual presentation of the rows returned by the legacy usage service."""

from concurrent.futures import ThreadPoolExecutor

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static
from textual import work

import usage
import usage_accounts
import usage_connect
from ..components import NovaFooter, NovaHeader
from ..tokens import SEMANTIC, usage_color_for_percent


def average(rows, key):
    """Use the legacy dashboard's available-value averaging convention."""
    values = [usage.pct_num(row.get(key)) for row in rows]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def meter(value, width=44):
    """Solid single-row meter. Both filled and track use the full block
    character so the bar renders as one continuous rectangle with a crisp
    color boundary at the fill point — no half-blocks, no stippled gaps."""
    number = usage.pct_num(value)
    if number is None:
        return None, "—"
    filled = max(0, min(width, round(number / 100 * width)))
    color = usage_color_for_percent(number)
    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("█" * (width - filled), style="#1A1F1B")
    return bar, f"{number:g}%"


class ProviderCard(Vertical):
    DEFAULT_CSS = """
    ProviderCard { height: auto; padding: 1 2; margin: 0 1 1 0;
                   background: #0D110E; border: tall #242A25; }
    ProviderCard Static { height: auto; }
    .meter-row { margin-top: 1; }
    .meter-reset { color: #626A64; margin-bottom: 1; }
    .tier-chip { color: #75FF00; text-style: bold; }
    """

    def __init__(self, row, **kwargs):
        super().__init__(**kwargs)
        self.row = row

    def compose(self) -> ComposeResult:
        row = self.row
        header = Text(row.get("name", "Provider"), style="bold #E7ECE8")
        tier = row.get("plan_tier")
        if tier:
            header.append("   ")
            header.append(tier, style="bold #050706 on #75FF00")
        yield Static(header)
        yield Static(Text(f"v{row.get('version', 'n/a')}", style=SEMANTIC.text_muted))
        if row.get("usage_status") == "unavailable":
            yield Static(Text("× Usage data temporarily unavailable", style=SEMANTIC.warning))
            yield Static("Retry refresh; other profiles are unaffected.")
            return
        # Always render both window rows at the same height so sibling cards
        # in a row stay flush. Windows the plan doesn't report render in a
        # muted "not in plan" state instead of collapsing the row.
        for index in (1, 2):
            value = row.get(f"used{index}")
            number = usage.pct_num(value)
            period = (row.get(f"p{index}") or ("5H" if index == 1 else "WEEKLY")).upper()
            header_line = Text()
            header_line.append(f"{period:<8}", style=SEMANTIC.text_muted)
            if number is None:
                header_line.append("not in plan", style=SEMANTIC.text_disabled)
                bar = Text("█" * 44, style="#1A1F1B")
                reset_text = "—"
            else:
                color = usage_color_for_percent(number)
                header_line.append(f"{number:g}%", style=color)
                bar, _ = meter(value)
                reset_text = row.get(f"reset{index}", "n/a")
            yield Static(header_line, classes="meter-row")
            yield Static(bar)
            yield Static(Text(f"        resets {reset_text}",
                              style=SEMANTIC.text_disabled if number is None
                              else SEMANTIC.text_muted),
                         classes="meter-reset")


class UsageScreen(Screen):
    BINDINGS = [("q", "quit", "Quit"), ("escape", "quit", "Quit"),
                ("r", "refresh", "Refresh"), ("c", "connect", "Connect")]
    DEFAULT_CSS = """
    UsageScreen { layout: vertical; }
    #usage-content { height: 1fr; padding: 0 1; }
    #usage-content Static { height: auto; }
    .profiles { height: auto; }
    .profiles > ProviderCard { width: 1fr; }
    .combined { height: auto; padding: 1 2; margin: 0 1;
                background: #0D110E; border: tall #242A25; }
    .combined Static { height: auto; }
    .combined-row { margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        yield NovaHeader("NOVANODE", "/ USAGE")
        with VerticalScroll(id="usage-content"):
            yield Static("Loading usage data…")
        yield NovaFooter([("R", "Refresh"), ("C", "Connect"),
                          ("Q", "Quit"), ("Esc", "Back")])

    def on_mount(self) -> None:
        self.load_usage()

    @work(thread=True, exclusive=True)
    def load_usage(self) -> None:
        try:
            rows = usage.fetch_usage()  # Same normalized rows as nn-usage.
        except Exception as error:
            self.app.call_from_thread(self.show_error, str(error))
        else:
            self.app.call_from_thread(self.show_rows, rows)

    def show_error(self, detail):
        self.query_one("#usage-content", VerticalScroll).remove_children()
        self.query_one("#usage-content", VerticalScroll).mount(
            Static(f"Usage unavailable: {detail}. Press R to retry."))

    def show_rows(self, rows):
        content = self.query_one("#usage-content", VerticalScroll)
        content.remove_children()
        if not rows:
            content.mount(Static("No connected providers. Run `usage connect` to add a profile."))
            return
        # Two cards per row when space permits; one per row in narrow terminals.
        columns = 2 if self.size.width >= 84 else 1
        for offset in range(0, len(rows), columns):
            content.mount(Horizontal(*(ProviderCard(row) for row in rows[offset:offset + columns]),
                                     classes="profiles"))
        all_values = [usage.pct_num(row.get(key)) for row in rows for key in ("used1", "used2")]
        all_values = [value for value in all_values if value is not None]
        combined = sum(all_values) / len(all_values) if all_values else None
        with_card = Vertical(classes="combined")
        content.mount(with_card)
        with_card.mount(Static(Text("COMBINED LOAD", style="bold #E7ECE8")))
        combined_width = max(32, min(72, self.size.width - 16))
        for title, value in (("5H", average(rows, "used1")),
                             ("WEEKLY", average(rows, "used2")),
                             ("ALL", combined)):
            bar, label = meter(value, combined_width)
            number = usage.pct_num(value)
            if number is None:
                continue  # Skip combined rows that nobody is reporting.
            color = usage_color_for_percent(number)
            header_line = Text()
            header_line.append(f"{title:<8}", style=SEMANTIC.text_muted)
            header_line.append(label, style=color)
            with_card.mount(Static(header_line, classes="combined-row"))
            with_card.mount(Static(bar))
        reporting = sum(any(usage.pct_num(row.get(key)) is not None
                            for key in ("used1", "used2")) for row in rows)
        suffix = f" · {reporting} reporting live usage" if reporting != len(rows) else ""
        with_card.mount(Static(Text(f"{len(rows)} connected profiles{suffix}",
                                    style=SEMANTIC.text_muted)))
        with_card.mount(Static(Text("Add another with `usage connect`",
                                    style=SEMANTIC.text_muted)))

    def action_refresh(self) -> None:
        content = self.query_one("#usage-content", VerticalScroll)
        content.remove_children()
        content.mount(Static("Refreshing usage data…"))
        self.load_usage()

    def action_connect(self) -> None:
        from .connect import ConnectScreen
        self.app.push_screen(ConnectScreen())

    def on_screen_resume(self) -> None:
        # Reload usage data when returning from the connect hub so new
        # profiles start reporting immediately.
        try:
            self.action_refresh()
        except Exception:
            pass

    def action_quit(self) -> None:
        target = getattr(self.app, "_initial_target", "hub")
        if target == "hub" and len(self.app.screen_stack) > 1:
            self.app.pop_screen()
        else:
            self.app.exit()
