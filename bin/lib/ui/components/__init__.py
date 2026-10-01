"""NovaNode UI Components — reusable Textual widgets."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Label, Static
from textual.reactive import reactive
from textual import events
from textual.message import Message

from ..icons import ICONS
from ..tokens import SEMANTIC, usage_color_for_percent, usage_state_for_percent


class NovaHeader(Container):
    """Application header with title and contextual subtitle."""

    DEFAULT_CSS = """
    NovaHeader {
        layout: horizontal;
        height: 3;
        padding: 0 2;
    }
    """

    def __init__(self, title: str = "NOVANODE", subtitle: str = "", **kwargs):
        super().__init__(**kwargs)
        self._title = title
        self._subtitle = subtitle

    def compose(self) -> ComposeResult:
        yield Label(f"◆ {self._title}", classes="NovaHeaderTitle")
        if self._subtitle:
            yield Label(self._subtitle, classes="NovaHeaderSubtitle")

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle = subtitle
        subtitle_widget = self.query_one(".NovaHeaderSubtitle", Label)
        subtitle_widget.update(subtitle)


class NovaFooter(Container):
    """Persistent footer with keyboard hints."""

    DEFAULT_CSS = """
    NovaFooter {
        layout: horizontal;
        height: 1;
        padding: 0 2;
        dock: bottom;
    }
    """

    def __init__(self, hints: list[tuple[str, str]] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._hints = hints or []

    def compose(self) -> ComposeResult:
        for key, desc in self._hints:
            # markup=False — otherwise `[R]` is parsed as Rich style markup.
            yield Label(f"[{key}]", classes="NovaFooterKey", markup=False)
            yield Label(f" {desc} ", classes="NovaFooterDesc", markup=False)

    def set_hints(self, hints: list[tuple[str, str]]) -> None:
        self._hints = hints
        self.remove_children()
        self.mount_all([self._make_hint(key, desc) for key, desc in hints])

    def _make_hint(self, key: str, desc: str) -> Horizontal:
        h = Horizontal()
        h.mount(Label(f"[{key}]", classes="NovaFooterKey", markup=False))
        h.mount(Label(f" {desc} ", classes="NovaFooterDesc", markup=False))
        return h


class NovaSection(Container):
    """Content section with title."""

    DEFAULT_CSS = """
    NovaSection {
        layout: vertical;
        margin: 1 2;
        padding: 1 2;
    }
    """

    def __init__(self, title: str = "", **kwargs):
        super().__init__(**kwargs)
        self._title = title

    def compose(self) -> ComposeResult:
        if self._title:
            yield Label(self._title.upper(), classes="NovaSectionTitle")


class NovaCard(Container, can_focus=True):
    """Base card component with focus styling."""

    DEFAULT_CSS = """
    NovaCard {
        layout: vertical;
        padding: 1 2;
        margin: 0 0 1 0;
        min-height: 5;
    }
    """

    BORDER_FOCUS = "#75FF00"
    BORDER_DEFAULT = "#242A25"

    def __init__(self, title: str = "", subtitle: str = "", **kwargs):
        super().__init__(**kwargs)
        self._title = title
        self._subtitle = subtitle

    def compose(self) -> ComposeResult:
        if self._title:
            yield Label(self._title, classes="NovaCardTitle")
        if self._subtitle:
            yield Label(self._subtitle, classes="NovaCardSubtitle")


class NovaUsageBar(Widget):
    """Usage progress bar with semantic coloring."""

    DEFAULT_CSS = """
    NovaUsageBar {
        layout: horizontal;
        height: 3;
        margin: 0 0 1 0;
    }
    NovaUsageBarLabel {
        width: 14;
        content-align: right middle;
        padding-right: 1;
    }
    NovaUsageBarTrack {
        width: 1fr;
        height: 1;
        margin-top: 1;
    }
    NovaUsageBarFill {
        height: 1;
        transition: width 200ms ease-out, background 200ms ease-out;
    }
    NovaUsageBarValue {
        width: 6;
        text-style: bold;
        text-align: right;
        content-align: center middle;
    }
    NovaUsageBarReset {
        margin-top: 1;
    }
    """

    percent = reactive(0)
    label = reactive("")
    reset_text = reactive("")
    state = reactive("low")

    def __init__(
        self,
        label: str = "",
        percent: int = 0,
        reset_text: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.label = label
        self.percent = max(0, min(100, percent))
        self.reset_text = reset_text
        self.state = usage_state_for_percent(self.percent)

    def compose(self) -> ComposeResult:
        yield Label(self.label.upper(), classes="NovaUsageBarLabel")
        with Horizontal(classes="NovaUsageBarTrack"):
            yield Static("", classes="NovaUsageBarFill", id="fill")
        yield Label(f"{self.percent}%", classes="NovaUsageBarValue", id="value")
        if self.reset_text:
            yield Label(self.reset_text, classes="NovaUsageBarReset")

    def watch_percent(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        self.state = usage_state_for_percent(percent)
        fill = self.query_one("#fill", Static)
        value = self.query_one("#value", Label)
        fill.styles.width = f"{percent}%"
        fill.remove_class("--medium", "--high", "--critical")
        value.remove_class("--medium", "--high", "--critical")
        if self.state == "medium":
            fill.add_class("--medium")
            value.add_class("--medium")
        elif self.state == "high":
            fill.add_class("--high")
            value.add_class("--high")
        elif self.state == "critical":
            fill.add_class("--critical")
            value.add_class("--critical")
        value.update(f"{percent}%")

    def watch_label(self, label: str) -> None:
        self.query_one(".NovaUsageBarLabel", Label).update(label.upper())

    def watch_reset_text(self, text: str) -> None:
        try:
            self.query_one(".NovaUsageBarReset", Label).update(text)
        except Exception:
            if text:
                self.mount(Label(text, classes="NovaUsageBarReset"))


class NovaBadge(Label):
    """Semantic badge component."""

    DEFAULT_CSS = """
    NovaBadge {
        padding: 0 1;
        text-style: bold;
        height: 1;
        content-align: center middle;
    }
    """

    def __init__(self, text: str, variant: str = "default", **kwargs):
        super().__init__(text, **kwargs)
        self.variant = variant
        self.add_class(f"--{variant}")


class NovaStatusDot(Label):
    """Connection status indicator."""

    DEFAULT_CSS = """
    NovaStatusDot {
        width: 2;
        height: 1;
        content-align: center middle;
    }
    """

    def __init__(self, state: str = "disconnected", **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._update()

    def _update(self) -> None:
        icons = {
            "connected": f"{ICONS.DOT_FILLED}",
            "connecting": f"{ICONS.DOT_LOADING}",
            "disconnected": f"{ICONS.DOT_EMPTY}",
            "error": f"{ICONS.CROSS_MARK}",
            "shadowed": f"{ICONS.DOT_SHADOWED}",
        }
        self.update(icons.get(self.state, ICONS.DOT_EMPTY))
        self.remove_class("--connected", "--connecting", "--disconnected", "--error", "--shadowed")
        self.add_class(f"--{self.state}")

    def set_state(self, state: str) -> None:
        self.state = state
        self._update()


class NovaMenuItem(Container, can_focus=True):
    """Selectable menu item with label, shortcut, and optional badge."""

    DEFAULT_CSS = """
    NovaMenuItem {
        layout: horizontal;
        height: 3;
        padding: 0 2;
        margin: 0 1;
    }
    NovaMenuItemLabel { width: 1fr; }
    NovaMenuItemShortcut {
        width: auto;
        text-style: bold;
        padding-left: 2;
        content-align: right middle;
    }
    NovaMenuItemBadge { margin-left: 2; }
    """

    def __init__(
        self,
        label: str,
        shortcut: str = "",
        badge: str = "",
        badge_variant: str = "default",
        subtitle: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._label = label
        self._shortcut = shortcut
        self._badge = badge
        self._badge_variant = badge_variant
        self._subtitle = subtitle

    def compose(self) -> ComposeResult:
        yield Label(self._label, classes="NovaMenuItemLabel", markup=False)
        if self._shortcut:
            yield Label(f"  [{self._shortcut}]", classes="NovaMenuItemShortcut", markup=False)
        if self._badge:
            yield NovaBadge(self._badge, variant=self._badge_variant, classes="NovaMenuItemBadge")
        if self._subtitle:
            yield Label(f"   {self._subtitle}", classes="NovaCardMeta", markup=False)


class NovaAction(Container, can_focus=True):
    """Focusable action row — single activation event for click/Enter/shortcut."""

    DEFAULT_CSS = """
    NovaAction {
        layout: horizontal;
        height: auto;
        min-height: 3;
        padding: 0 1;
        margin: 0 1;
        background: transparent;
        border-left: heavy transparent;
        color: #E7ECE8;
    }
    NovaAction:hover {
        background: transparent;
        border-left: heavy transparent;
    }
    NovaAction:focus {
        background: transparent;
        border-left: heavy #75FF00;
    }
    NovaActionLabel { width: auto; }
    NovaActionShortcut {
        width: auto;
        text-style: bold;
        padding-left: 2;
        content-align: right middle;
    }
    NovaActionBadge { margin-left: 2; }
    NovaActionDescription {
        width: auto;
        color: #626A64;
        margin-left: 2;
    }
    """

    def __init__(
        self,
        label: str,
        action_id: str,
        shortcut: str = "",
        description: str = "",
        badge: str = "",
        badge_variant: str = "default",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._label = label
        self._action_id = action_id
        self._shortcut = shortcut
        self._description = description
        self._badge = badge
        self._badge_variant = badge_variant
        self.id = f"action-{action_id}"

    def compose(self) -> ComposeResult:
        # markup=False — otherwise `[U]`, `[S]` are read as Rich style tags
        # and the shortcut disappears. Explicit spacing in text so the label,
        # shortcut, and description read with clear gaps even when Textual
        # collapses margins between adjacent auto-width labels.
        yield Label(self._label, classes="NovaActionLabel", markup=False)
        if self._shortcut:
            yield Label(f"  [{self._shortcut}]", classes="NovaActionShortcut", markup=False)
        if self._badge:
            yield NovaBadge(self._badge, variant=self._badge_variant, classes="NovaActionBadge")
        if self._description:
            yield Label(f"   {self._description}", classes="NovaActionDescription", markup=False)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.focus()
        self.press()

    def on_key(self, event: events.Key) -> None:
        if event.key in ("enter", "space"):
            event.stop()
            self.press()

    def press(self) -> None:
        self.post_message(self.Activated(self._action_id, self))

    class Activated(Message):
        def __init__(self, action_id: str, source: "NovaAction"):
            super().__init__()
            self.action_id = action_id
            self.source = source


class NovaMenuDivider(Static):
    """Menu divider line."""

    DEFAULT_CSS = """
    NovaMenuDivider {
        height: 1;
        margin: 0 2;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)


class NovaMenuHeading(Label):
    """Menu section heading."""

    DEFAULT_CSS = """
    NovaMenuHeading {
        padding: 1 2 0 2;
        text-style: bold uppercase;
        letter-spacing: 1;
    }
    """

    def __init__(self, text: str, **kwargs):
        super().__init__(text.upper(), **kwargs)


class NovaKeyHint(Horizontal):
    """Single keyboard hint: [KEY] Description."""

    DEFAULT_CSS = """
    NovaKeyHint {
        height: 1;
    }
    NovaKeyHintKey {
        width: auto;
        text-style: bold;
        padding: 0 1;
        margin-right: 1;
        content-align: center middle;
    }
    NovaKeyHintDesc {
        width: auto;
        content-align: left middle;
        margin-right: 2;
    }
    """

    def __init__(self, key: str, desc: str, **kwargs):
        super().__init__(**kwargs)
        self.mount(Label(f" {key} ", classes="NovaKeyHintKey"))
        self.mount(Label(desc, classes="NovaKeyHintDesc"))


class NovaSpinner(Label):
    """Animated spinner."""

    DEFAULT_CSS = """
    NovaSpinner {
        width: 3;
        height: 1;
        content-align: center middle;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(ICONS.DOT_LOADING, **kwargs)
        self._frames = ["◐", "◓", "◑", "◒"]
        self._index = 0

    def on_mount(self) -> None:
        self.set_interval(0.1, self._animate)

    def _animate(self) -> None:
        self._index = (self._index + 1) % len(self._frames)
        self.update(self._frames[self._index])


class NovaEmptyState(Container):
    """Empty state with icon, title, and message."""

    DEFAULT_CSS = """
    NovaEmptyState {
        layout: vertical;
        width: 100%;
        height: 100%;
        content-align: center middle;
    }
    NovaEmptyStateIcon {
        margin-bottom: 1;
    }
    NovaEmptyStateTitle {
        text-style: bold;
        margin-bottom: 1;
    }
    NovaEmptyStateMessage {
        text-align: center;
    }
    """

    def __init__(
        self,
        icon: str = ICONS.CIRCLE,
        title: str = "No items",
        message: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._icon = icon
        self._title = title
        self._message = message

    def compose(self) -> ComposeResult:
        yield Label(self._icon, classes="NovaEmptyStateIcon")
        yield Label(self._title, classes="NovaEmptyStateTitle")
        if self._message:
            yield Label(self._message, classes="NovaEmptyStateMessage")


class NovaToast(Container):
    """Transient notification toast."""

    DEFAULT_CSS = """
    NovaToast {
        layout: horizontal;
        padding: 1 2;
        width: auto;
        max-width: 60;
    }
    NovaToastIcon { width: 3; content-align: center middle; }
    NovaToastMessage { width: 1fr; }
    """

    def __init__(self, message: str, variant: str = "default", **kwargs):
        super().__init__(**kwargs)
        self.variant = variant
        self._message = message
        self.add_class(f"--{variant}")

    def compose(self) -> ComposeResult:
        icons = {
            "success": ICONS.CHECK,
            "warning": ICONS.TRIANGLE_WARN,
            "error": ICONS.CROSS_MARK,
            "default": ICONS.DOT_FILLED,
        }
        yield Label(icons.get(self.variant, ICONS.DOT_FILLED), classes="NovaToastIcon")
        yield Label(self._message, classes="NovaToastMessage")


class NovaModal(Container):
    """Modal dialog overlay."""

    DEFAULT_CSS = """
    NovaModal {
        layer: overlay;
        layout: vertical;
        width: 60%;
        max-width: 80;
        max-height: 80%;
        padding: 2;
        margin: 2;
    }
    NovaModalTitle { margin-bottom: 1; text-style: bold; }
    NovaModalBody { margin-bottom: 2; }
    NovaModalButtons {
        layout: horizontal;
        width: 100%;
        content-align: right middle;
    }
    NovaModalButton {
        margin-left: 2;
        padding: 0 3;
        height: 3;
    }
    """

    def __init__(
        self,
        title: str,
        body: str,
        buttons: list[tuple[str, str, str]] | None = None,
        **kwargs,
    ):
        """
        buttons: list of (label, action_id, variant)
        variant: "primary", "danger", "default"
        """
        super().__init__(**kwargs)
        self._title = title
        self._body = body
        self._buttons = buttons or [
            ("Cancel", "cancel", "default"),
            ("Continue", "confirm", "primary"),
        ]

    def compose(self) -> ComposeResult:
        yield Label(self._title, classes="NovaModalTitle")
        yield Label(self._body, classes="NovaModalBody")
        with Horizontal(classes="NovaModalButtons"):
            for label, action_id, variant in self._buttons:
                btn = Label(f" {label} ", classes="NovaModalButton", id=f"btn-{action_id}")
                btn.add_class(f"--{variant}")
                yield btn
