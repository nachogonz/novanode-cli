"""NovaNode Design Tokens — semantic color and style values.

Single source of truth for the visual system. All components import from here.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ColorTokens:
    """Base color palette — never used directly in components."""

    # Core backgrounds
    BACKGROUND = "#050706"
    SURFACE_0 = "#080B09"
    SURFACE_1 = "#0D110E"
    SURFACE_2 = "#121713"

    # Primary accent (Nova lime)
    ACCENT = "#75FF00"
    ACCENT_DIM = "#50C900"
    ACCENT_MUTED = "#2E4A1A"

    # Secondary accents
    CYAN = "#00D9FF"
    CYAN_DIM = "#00A8CC"

    # Semantic states
    WARNING = "#FFB000"
    WARNING_DIM = "#CC8D00"
    DANGER = "#FF3B30"
    DANGER_DIM = "#CC2E26"
    SUCCESS = "#34D399"
    SUCCESS_DIM = "#1FA67A"

    # Text hierarchy
    TEXT_PRIMARY = "#E7ECE8"
    TEXT_SECONDARY = "#9AA39C"
    TEXT_MUTED = "#626A64"
    TEXT_DISABLED = "#3A3F3C"

    # Borders
    BORDER = "#242A25"
    BORDER_MUTED = "#1A1F1B"
    BORDER_FOCUS = "#75FF00"
    BORDER_ACTIVE = "#50C900"

    # Usage-specific gradients
    USAGE_EMPTY = "#141A16"
    USAGE_LOW = "#75FF00"
    USAGE_MEDIUM = "#FFB000"
    USAGE_HIGH = "#FF8C00"
    USAGE_CRITICAL = "#FF3B30"

    # Overlay/scrim
    SCRIM = "#000000CC"
    OVERLAY_BG = "#0A0D0B"


@dataclass(frozen=True)
class SemanticTokens:
    """Semantic aliases — components use these exclusively."""

    # Backgrounds
    background: str = ColorTokens.BACKGROUND
    surface: str = ColorTokens.SURFACE_1
    surface_hover: str = ColorTokens.SURFACE_2
    surface_active: str = ColorTokens.SURFACE_2

    # Text
    text: str = ColorTokens.TEXT_PRIMARY
    text_muted: str = ColorTokens.TEXT_SECONDARY
    text_disabled: str = ColorTokens.TEXT_DISABLED
    text_accent: str = ColorTokens.ACCENT

    # Accents
    accent: str = ColorTokens.ACCENT
    accent_dim: str = ColorTokens.ACCENT_DIM
    accent_bg: str = ColorTokens.ACCENT_MUTED

    # States
    warning: str = ColorTokens.WARNING
    warning_bg: str = "#2D260A"
    danger: str = ColorTokens.DANGER
    danger_bg: str = "#2D1515"
    success: str = ColorTokens.SUCCESS
    success_bg: str = "#0E281C"
    info: str = ColorTokens.CYAN
    info_bg: str = "#0A242D"

    # Borders
    border: str = ColorTokens.BORDER
    border_muted: str = ColorTokens.BORDER_MUTED
    border_focus: str = ColorTokens.BORDER_FOCUS
    border_active: str = ColorTokens.BORDER_ACTIVE

    # Usage bars
    usage_track: str = ColorTokens.USAGE_EMPTY
    usage_low: str = ColorTokens.USAGE_LOW
    usage_medium: str = ColorTokens.USAGE_MEDIUM
    usage_high: str = ColorTokens.USAGE_HIGH
    usage_critical: str = ColorTokens.USAGE_CRITICAL

    # Overlay
    scrim: str = ColorTokens.SCRIM
    overlay_bg: str = ColorTokens.OVERLAY_BG


@dataclass(frozen=True)
class SpacingTokens:
    """Consistent spacing scale."""

    xs: int = 1
    sm: int = 2
    md: int = 3
    lg: int = 4
    xl: int = 6
    xxl: int = 8


@dataclass(frozen=True)
class TypographyTokens:
    """Text style definitions."""

    # Weights available in terminal: normal, bold
    # Sizes simulated via case/brightness
    pass


# Global instances
COLORS = ColorTokens()
SEMANTIC = SemanticTokens()
SPACING = SpacingTokens()
TYPOGRAPHY = TypographyTokens()


def usage_color_for_percent(pct: int) -> str:
    """Return semantic color for a usage percentage."""
    if pct >= 95:
        return SEMANTIC.usage_critical
    if pct >= 80:
        return SEMANTIC.usage_high
    if pct >= 60:
        return SEMANTIC.usage_medium
    return SEMANTIC.usage_low


def usage_state_for_percent(pct: int) -> str:
    """Return state name for a usage percentage."""
    if pct >= 95:
        return "critical"
    if pct >= 80:
        return "high"
    if pct >= 60:
        return "medium"
    return "low"