"""Tinted line icons (inline SVG) and Windows 11 rounded popup menus."""

from __future__ import annotations

import ctypes
import sys
from functools import lru_cache

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QMenu

_HEAD = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='{c}' "
         "stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'>")
_PATHS = {
    "server": "<rect x='3' y='4' width='18' height='7' rx='2'/><rect x='3' y='13' width='18' height='7' rx='2'/>"
              "<path d='M7 7.5h.01M7 16.5h.01'/>",
    "model": "<rect x='5' y='5' width='14' height='14' rx='2'/><rect x='9' y='9' width='6' height='6' rx='1'/>"
             "<path d='M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3'/>",
    "test": "<rect x='9' y='3' width='6' height='11' rx='3'/><path d='M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8'/>",
    "info": "<circle cx='12' cy='12' r='9'/><path d='M12 11v5M12 8h.01'/>",
    "settings": "<circle cx='12' cy='12' r='3'/><path d='M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3"
                "M4.9 19.1L7 17M17 7l2.1-2.1'/>",
    "restart": "<path d='M3 12a9 9 0 1 0 3-6.7L3 8'/><path d='M3 3v5h5'/>",
    "copy": "<rect x='8' y='8' width='12' height='12' rx='2'/><path d='M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 "
            "2 2h2'/>",
    "folder": "<path d='M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/>",
    "pulse": "<path d='M3 12h4l3-8 4 16 3-8h4'/>",
    "quit": "<path d='M6 6l12 12M18 6L6 18'/>",
    "check": "<path d='M5 12.5l4.5 4.5L19 7.5'/>",
    "power": "<path d='M18.4 6.6a9 9 0 1 1-12.8 0'/><path d='M12 2v10'/>",
}


@lru_cache(maxsize=None)
def line_icon(name: str, color: str, selected_color: str | None = None) -> QIcon:
    icon = QIcon()
    for mode, tint in ((QIcon.Mode.Normal, color), (QIcon.Mode.Selected, selected_color or color)):
        svg = _HEAD.format(c=tint) + _PATHS[name] + "</svg>"
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        for size in (16, 18, 20, 24):
            pixmap = QPixmap(size * 2, size * 2)
            pixmap.setDevicePixelRatio(2)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter, QRectF(0, 0, size, size))
            painter.end()
            icon.addPixmap(pixmap, mode)
    return icon


def round_corners(widget) -> None:
    """Windows 11: small rounded corners with the native shadow (DWMWA_WINDOW_CORNER_PREFERENCE)."""
    if sys.platform != "win32":
        return
    pref = ctypes.c_int(3)
    try:
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(widget.winId()), 33, ctypes.byref(pref), ctypes.sizeof(pref))
    except (AttributeError, OSError):
        pass


class RoundedMenu(QMenu):
    def showEvent(self, event):  # noqa: N802 - Qt API
        super().showEvent(event)
        round_corners(self)
