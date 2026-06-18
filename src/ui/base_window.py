import ctypes
import sys
from typing import override

from PyQt6.QtCore import Qt, QRectF, QPoint
from PyQt6.QtGui import (
    QPainter,
    QBrush,
    QColor,
    QPainterPath,
    QFont,
    QGuiApplication,
    QMouseEvent,
    QPaintEvent,
)
from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QMainWindow,
)


def apply_mica(hwnd: int, backdrop_type: int = 3) -> bool:
    """Apply Windows 11 Mica (type=2) or Acrylic (type=3) backdrop via DWM.
    Returns True if applied, False on unsupported Windows or failure.
    DWMWA_SYSTEMBACKDROP_TYPE = 38; backdrop values: 2=Mica, 3=Acrylic.
    Must be called after the window is shown (winId() valid).
    """
    if sys.platform != "win32":
        return False
    try:
        if sys.getwindowsversion().build < 22621:  # Win11 22H2+
            return False
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(ctypes.c_int(backdrop_type)),
            ctypes.sizeof(ctypes.c_int),
        )
        return True
    except OSError:
        return False


class BaseWindow(QMainWindow):
    _show_title_bar: bool
    is_dragging: bool
    main_widget: QWidget
    main_layout: QVBoxLayout
    start_position: QPoint

    def __init__(
        self, title: str, width: int, height: int, show_title_bar: bool = True
    ):
        super().__init__()
        self._show_title_bar = show_title_bar
        self.is_dragging = False
        self.start_position = QPoint()
        self.initUI(title, width, height)
        self.setWindowPosition()

    def initUI(self, title: str, width: int, height: int) -> None:
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(width, height)

        self.main_widget = QWidget(self)
        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(10, 10, 10, 10)

        if self._show_title_bar:
            title_bar = QWidget()
            title_bar_layout = QHBoxLayout(title_bar)
            title_bar_layout.setContentsMargins(0, 0, 0, 0)

            title_label = QLabel("WhisperWriter")
            title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_label.setStyleSheet("color: #cdd6f4;")

            close_button_widget = QWidget()
            close_button_layout = QHBoxLayout(close_button_widget)
            close_button_layout.setContentsMargins(0, 0, 0, 0)

            close_button = QPushButton("×")
            close_button.setFixedSize(25, 25)
            close_button.setStyleSheet("""
                QPushButton { background-color: transparent; border: none; color: #cdd6f4; font-size: 16pt; }
                QPushButton:hover { color: #ff6b6b; }
            """)
            close_button.clicked.connect(self.handleCloseButton)
            close_button_layout.addWidget(
                close_button, alignment=Qt.AlignmentFlag.AlignRight
            )

            title_bar_layout.addWidget(QWidget(), 1)
            title_bar_layout.addWidget(title_label, 3)
            title_bar_layout.addWidget(close_button_widget, 1)
            self.main_layout.addWidget(title_bar)

        self.setCentralWidget(self.main_widget)

    def setWindowPosition(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        center_point = screen.availableGeometry().center()
        frame_geometry = self.frameGeometry()
        frame_geometry.moveCenter(center_point)
        self.move(frame_geometry.topLeft())

    def handleCloseButton(self) -> None:
        self.close()

    @override
    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            return
        event = a0
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self.start_position = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    @override
    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            return
        event = a0
        if self.is_dragging:
            self.move(event.globalPosition().toPoint() - self.start_position)
            event.accept()

    @override
    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        self.is_dragging = False

    @override
    def paintEvent(self, a0: QPaintEvent | None) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 20, 20)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor(255, 255, 255, 220)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)
