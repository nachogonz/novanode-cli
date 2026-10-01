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


def meter(value, width=22):
    number = usage.pct_num(value)
    if number is None:
        return Text("─" * width, style=SEMANTIC.border), "—"
    filled = round(number / 100 * width)
    bar = Text("━" * filled, style=usage_color_for_percent(number))
    bar.append("─" * (width - filled), style=SEMANTIC.usage_track)
    return bar, f"{number:g}%"


class ProviderCard(Vertical):
    DEFAULT_CSS = """
    ProviderCard { height: auto; padding: 1 2; margin: 0 1 1 0;
                   background: #0D110E; border: tall #242A25; }
    ProviderCard Static { height: auto; }
    """

    def __init__(self, row, **kwargs):
        super().__init__(**kwargs)
        self.row = row

    def compose(self) -> ComposeResult:
        row = self.row
        yield Static(Text(row.get("name", "Provider"), style="bold #E7ECE8"))
        yield Static(Text(f"v{row.get('version', 'n/a')}", style=SEMANTIC.text_muted))
        if row.get("usage_status") == "unavailable":
            yield Static(Text("× Usage data temporarily unavailable", style=SEMANTIC.warning))
            yield Static("Retry refresh; other profiles are unaffected.")
            return
        for index in (1, 2):
            value = row.get(f"used{index}")
            bar, label = meter(value)
            line = Text(f"{row.get(f'p{index}', ''):<8}", style=SEMANTIC.text)
            line.append_text(bar)
            line.append(f"  {label}", style=SEMANTIC.text if label != "—" else SEMANTIC.text_muted)
            yield Static(line)
            note = ("not included in this plan" if usage.pct_num(value) is None
                    else f"resets {row.get(f'reset{index}', 'n/a')}")
            yield Static(Text(" " * 8 + note, style=SEMANTIC.text_muted))


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
        for title, value in (("5H", average(rows, "used1")),
                             ("WEEKLY", average(rows, "used2")),
                             ("ALL", combined)):
            bar, label = meter(value, 32)
            line = Text(f"{title:<8}", style=SEMANTIC.text)
            line.append_text(bar)
            line.append(f"  {label}", style=SEMANTIC.text)
            with_card.mount(Static(line))
        reporting = sum(any(usage.pct_num(row.get(key)) is not None
                            for key in ("used1", "used2")) for row in rows)
        suffix = f" · {reporting} reporting live usage" if reporting != len(rows) else ""
        with_card.mount(Static(f"{len(rows)} connected profiles{suffix}"))
        with_card.mount(Static("Add another with `usage connect`"))

    def action_refresh(self) -> None:
        content = self.query_one("#usage-content", VerticalScroll)
        content.remove_children()
        content.mount(Static("Refreshing usage data…"))
        self.load_usage()

    def action_connect(self) -> None:
        # Reuse the legacy connection hub rather than inventing another flow.
        with self.app.suspend():
            usage_connect.interactive_hub()
        self.action_refresh()

    def action_quit(self) -> None:
        target = getattr(self.app, "_initial_target", "hub")
        if target == "hub" and len(self.app.screen_stack) > 1:
            self.app.pop_screen()
        else:
            self.app.exit()
