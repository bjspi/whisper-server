"""Setting rows and cards like WhisperTyper's modern settings: title + description left, control right."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

COMBO_WIDTH = 300
FIELD_WIDTH = 300
NUMBER_WIDTH = 110


class SettingRow(QWidget):
    def __init__(self, title: str, description: str = "", control: QWidget | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("settingRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        # Attach the layout first: a widget made visible before it has a parent pops up as its own window.
        layout.addLayout(texts, 1)
        self.title = QLabel(title)
        self.title.setProperty("rowTitle", True)
        texts.addWidget(self.title)
        self.description = QLabel(description)
        self.description.setObjectName("rowDescription")
        self.description.setWordWrap(True)
        texts.addWidget(self.description)
        self.description.setVisible(bool(description))
        if control is not None:
            layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)


class Card(QFrame):
    """White rounded card; rows are separated by hairline dividers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 2, 0, 2)
        self._layout.setSpacing(0)
        self._count = 0

    def add(self, widget: QWidget) -> QWidget:
        if self._count:
            line = QFrame()
            line.setObjectName("rowDivider")
            line.setFixedHeight(1)
            wrap = QHBoxLayout()
            wrap.setContentsMargins(16, 0, 16, 0)
            wrap.addWidget(line)
            self._layout.addLayout(wrap)
        self._layout.addWidget(widget)
        self._count += 1
        return widget

    def row(self, title: str, description: str = "", control: QWidget | None = None) -> SettingRow:
        return self.add(SettingRow(title, description, control))


def card_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("cardTitle")
    return label


def controls(*widgets: QWidget, spacing: int = 8) -> QWidget:
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for w in widgets:
        layout.addWidget(w)
    return box
