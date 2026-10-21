"""Look of WhisperTyper's modern design: soft grey canvas, white cards, one blue accent, light/dark."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QApplication

MODERN_LIGHT = {
    "bg": "#f3f5f8", "panel": "#ffffff", "panel2": "#f1f4f8", "text": "#1f2329",
    "muted": "#6b727c", "border": "#e3e7ed", "field": "#ffffff", "field_border": "#cfd5dd",
    "accent": "#2f7de1", "accent_hover": "#2a72cf", "accent_press": "#2565b8",
    "on_accent": "#ffffff", "warn": "#cf6a3f", "danger": "#e5484d", "ok": "#2e9e5b", "hover": "#edf0f4",
    "heading": "#15191e", "sidebar": "#eaedf2", "sidebar_border": "#dfe3e9", "nav_text": "#3a4049",
    "nav_hover": "#e0e5ec", "nav_selected": "#1f5fb8", "menu_bg": "#f9f9fb", "menu_border": "#e0e3e8",
    "menu_selected": "#e8ebf0", "switch_off": "#c5ccd6", "selection": "#bcd5f5", "divider": "#eef1f4",
}
MODERN_DARK = {
    "bg": "#1b1d21", "panel": "#25282d", "panel2": "#2c3036", "text": "#e6e8eb",
    "muted": "#9aa1ab", "border": "#33373e", "field": "#1f2226", "field_border": "#40454d",
    "accent": "#4c94ef", "accent_hover": "#5ea0f2", "accent_press": "#3d84de",
    "on_accent": "#ffffff", "warn": "#e08b4a", "danger": "#ff5a52", "ok": "#4cc47f", "hover": "#2f333a",
    "heading": "#f2f4f6", "sidebar": "#202327", "sidebar_border": "#2d3036", "nav_text": "#c9cdd3",
    "nav_hover": "#2b2f35", "nav_selected": "#7fb2f5", "menu_bg": "#2b2d31", "menu_border": "#3a3d43",
    "menu_selected": "#383c43", "switch_off": "#4a4f57", "selection": "#2f5a91", "divider": "#2e3238",
}

_QSS = """
* { outline: none; }
QWidget { background-color: %(bg)s; color: %(text)s; font-size: 10pt; }
QLabel, QFrame, QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget { background: transparent; }
QScrollArea { border: none; }

QFrame#sidebar { background: %(sidebar)s; border: none; border-right: 1px solid %(sidebar_border)s; }
QLabel#brandName { font-size: 12pt; font-weight: 600; color: %(heading)s; }
QLabel#brandVersion { color: %(muted)s; font-size: 8pt; }
QListWidget#nav { background: transparent; border: none; padding: 0; }
QListWidget#nav::item {
    padding: 8px 10px; margin: 1px 0; border-radius: 8px; color: %(nav_text)s; border: 1px solid transparent;
}
QListWidget#nav::item:hover { background: %(nav_hover)s; }
QListWidget#nav::item:selected { background: %(panel)s; color: %(nav_selected)s; border-color: %(border)s; }
QLabel#pageTitle { font-size: 17pt; font-weight: 600; color: %(heading)s; }
QLabel#pageSubtitle { color: %(muted)s; font-size: 9pt; padding-bottom: 6px; }
QLabel#cardTitle { color: %(muted)s; font-weight: 600; font-size: 8pt; padding: 14px 0 6px 4px; }
QFrame#card { background: %(panel)s; border: 1px solid %(border)s; border-radius: 12px; }
QFrame#rowDivider { background: %(divider)s; border: none; }
QWidget#settingRow, QWidget#cardBody { background: transparent; }
QLabel[rowTitle="true"] { font-weight: 600; color: %(text)s; }
QLabel[rowTitle="true"]:disabled, QLabel:disabled { color: %(muted)s; }
QLabel#rowDescription { color: %(muted)s; font-size: 9pt; }
QLabel#mono { font-family: Consolas, "Cascadia Mono", monospace; }
QLabel[state="ok"] { color: %(ok)s; font-weight: 600; }
QLabel[state="loading"], QLabel[state="starting"] { color: %(accent)s; font-weight: 600; }
QLabel[state="down"], QLabel[state="conflict"] { color: %(danger)s; font-weight: 600; }
QFrame#footer { background: %(panel)s; border: none; border-top: 1px solid %(border)s; }

QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: %(field)s; color: %(text)s; border: 1px solid %(field_border)s;
    border-radius: 8px; padding: 4px 8px;
    selection-background-color: %(selection)s; selection-color: %(text)s;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid %(accent)s; }
QComboBox { padding-right: 32px; }
QComboBox:editable { padding-right: 4px; }
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: top right; width: 28px;
    border: none; border-left: 1px solid %(field_border)s;
    border-top-right-radius: 7px; border-bottom-right-radius: 7px; background: %(panel2)s;
}
QComboBox QAbstractItemView {
    background: %(panel)s; color: %(text)s; border: 1px solid %(border)s;
    selection-background-color: %(selection)s; selection-color: %(text)s; outline: none;
}

QPushButton {
    background: %(panel)s; color: %(text)s; border: 1px solid %(field_border)s; border-radius: 8px; padding: 5px 14px;
}
QPushButton:hover { background: %(hover)s; }
QPushButton:pressed { background: %(panel2)s; }
QPushButton:disabled { color: %(muted)s; }
QPushButton#primary {
    background: %(accent)s; color: %(on_accent)s; border: 1px solid %(accent)s;
    font-weight: 600; min-width: 110px; padding: 7px 18px;
}
QPushButton#primary:hover { background: %(accent_hover)s; border-color: %(accent_hover)s; }
QPushButton#primary:pressed { background: %(accent_press)s; }
QPushButton#primary:disabled { background: %(switch_off)s; border-color: %(switch_off)s; }

QCheckBox { spacing: 10px; background: transparent; }
QCheckBox::indicator { width: 34px; height: 20px; border: none; background: transparent; }

QTableWidget {
    background: %(panel)s; border: 1px solid %(border)s; border-radius: 12px; padding: 4px;
    selection-background-color: %(selection)s; selection-color: %(text)s; alternate-background-color: %(panel2)s;
}
QTableWidget::item { padding: 6px 10px; border: none; }
QHeaderView::section {
    background: transparent; color: %(muted)s; border: none; border-bottom: 1px solid %(divider)s;
    padding: 6px 10px; font-weight: 600; font-size: 8pt;
}

QMenu { background: %(menu_bg)s; border: 1px solid %(menu_border)s; padding: 6px; font-size: 9pt; }
QMenu::item { padding: 7px 40px 7px 18px; border-radius: 6px; }
QMenu::icon { left: 10px; }
QMenu::item:selected { background: %(menu_selected)s; color: %(text)s; }
QMenu::item:disabled { color: %(muted)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 4px 10px; }
QWidget#trayHeader { background: transparent; }
QLabel#trayTitle { font-weight: 600; color: %(heading)s; font-size: 10pt; }
QLabel#trayStatus { color: %(muted)s; font-size: 8pt; }

QToolTip {
    background-color: %(panel)s; color: %(text)s; border: 1px solid %(border)s; padding: 7px 9px; border-radius: 8px;
}
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: %(border)s; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


def is_dark(app: QApplication) -> bool:
    try:
        scheme = app.styleHints().colorScheme()
        if scheme in (Qt.ColorScheme.Dark, Qt.ColorScheme.Light):
            return scheme == Qt.ColorScheme.Dark
    except AttributeError:
        pass
    return app.palette().window().color().lightness() < 128


def palette(dark: bool) -> dict[str, str]:
    return MODERN_DARK if dark else MODERN_LIGHT


def _switch_svg(track: str, on: bool, opacity: float = 1.0) -> str:
    knob_x = 24 if on else 10
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 34 20' opacity='{opacity}'>"
            f"<rect x='0.5' y='1' width='33' height='18' rx='9' fill='{track}'/>"
            f"<circle cx='{knob_x}' cy='10' r='6.5' fill='#ffffff'/></svg>")


def _arrow_svg(color: str) -> str:
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'><path fill='none' stroke='{color}' "
            f"stroke-width='2' stroke-linecap='round' stroke-linejoin='round' d='M2.5 4l3.5 4 3.5-4'/></svg>")


def stylesheet(dark: bool, cache_dir: Path) -> str:
    """QSS plus the switch and arrow images (Qt loads QSS images from files, not data URIs)."""
    c = palette(dark)
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = "d" if dark else "l"
    assets = {
        "off": _switch_svg(c["switch_off"], False), "on": _switch_svg(c["accent"], True),
        "off_dis": _switch_svg(c["switch_off"], False, 0.45), "on_dis": _switch_svg(c["accent"], True, 0.45),
        "down": _arrow_svg(c["accent"]),
    }
    paths = {}
    for name, svg in assets.items():
        file = cache_dir / f"{name}_{suffix}.svg"
        if not file.is_file() or file.read_text(encoding="utf-8") != svg:
            file.write_text(svg, encoding="utf-8")
        paths[name] = str(file).replace(os.sep, "/")
    return _QSS % c + f"""
QCheckBox::indicator {{ image: url({paths['off']}); }}
QCheckBox::indicator:checked {{ image: url({paths['on']}); }}
QCheckBox::indicator:disabled {{ image: url({paths['off_dis']}); }}
QCheckBox::indicator:checked:disabled {{ image: url({paths['on_dis']}); }}
QComboBox::down-arrow {{ image: url({paths['down']}); width: 14px; height: 14px; }}
QSpinBox {{ padding-right: 8px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
"""


STATE_COLORS = {"ok": "#2e9e5b", "loading": "#2f7de1", "starting": "#8a9099", "down": "#e5484d", "conflict": "#e5484d"}


def app_icon(state: str | None = None, size: int = 64) -> QIcon:
    """Blue rounded tile with a white microphone; a coloured status dot when ``state`` is given."""
    scale = 2
    px = QPixmap(size * scale, size * scale)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size * scale / 64, size * scale / 64)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2f7de1"))
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(24, 11, 16, 27), 8, 8)
    pen = QPen(QColor("#ffffff"), 4.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    arc = QPainterPath()
    arc.moveTo(17, 30)
    arc.cubicTo(17, 50, 47, 50, 47, 30)
    p.drawPath(arc)
    p.drawLine(QPointF(32, 45), QPointF(32, 53))
    p.drawLine(QPointF(24, 53), QPointF(40, 53))
    if state:
        p.setPen(QPen(QColor("#ffffff"), 3))
        p.setBrush(QColor(STATE_COLORS.get(state, "#8a9099")))
        p.drawEllipse(QRectF(38, 38, 24, 24))
    p.end()
    px.setDevicePixelRatio(scale)
    return QIcon(px)
