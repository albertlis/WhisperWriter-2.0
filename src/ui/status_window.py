import math
import os
import sys
from collections import deque
from typing import override

from PyQt6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QSizePolicy, QWidget

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from ui.base_window import BaseWindow
from utils import ConfigManager

# Tokens — see DESIGN.md
_PILL = QColor("#1C1D21")
_HAIRLINE = QColor("#33363C")
_TEXT = "#E8E6E1"
_MUTED = "#8C8F96"
_REC = QColor("#E5484D")
_LLM = QColor("#E2A336")
_IDLE_BAR = QColor("#5E6168")

_HEIGHT = 44
_RADIUS = _HEIGHT / 2
_BARS = 9


def _ui_font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI"])
    font.setPointSize(size)
    font.setWeight(weight)
    return font


class LevelMeter(QWidget):
    """Bars showing the last few mic levels; in 'busy' mode a slow travelling wave."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(_BARS * 4 - 1, 20)
        self._levels: deque[float] = deque([0.0] * _BARS, maxlen=_BARS)
        self._color: QColor = _REC
        self._busy: bool = False
        self._phase: float = 0.0
        self._timer: QTimer = QTimer(self)
        _ = self._timer.timeout.connect(self._tick)

    def set_live(self, color: QColor) -> None:
        self._busy = False
        self._color = color
        self._timer.stop()
        self._levels.extend([0.0] * _BARS)
        self.update()

    def set_busy(self, color: QColor) -> None:
        self._busy = True
        self._color = color
        self._timer.start(40)

    def stop(self) -> None:
        self._timer.stop()

    def push(self, rms: float) -> None:
        if self._busy:
            return
        # -50 dBFS..-10 dBFS → 0..1; speech sits roughly in the upper half
        db = 20 * math.log10(max(rms, 1e-6))
        self._levels.append(min(max((db + 50) / 40, 0.0), 1.0))
        self.update()

    def _tick(self) -> None:
        self._phase += 0.18
        self.update()

    @override
    def paintEvent(self, a0: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        for i in range(_BARS):
            if self._busy:
                level = 0.25 + 0.35 * (1 + math.sin(self._phase - i * 0.7)) / 2
            else:
                level = self._levels[i]
            bar_h = max(3.0, level * h)
            color = QColor(self._color if self._busy or level > 0.05 else _IDLE_BAR)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(i * 4, (h - bar_h) / 2, 3, bar_h), 1.5, 1.5)


class StatusWindow(BaseWindow):
    statusSignal: pyqtSignal = pyqtSignal(str, bool)
    closeSignal: pyqtSignal = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("WhisperWriter Status", 240, _HEIGHT, show_title_bar=False)
        self._elapsed: QElapsedTimer = QElapsedTimer()
        self._shown_seconds: int = -1

        self._fade_in_anim: QPropertyAnimation = QPropertyAnimation(
            self, b"windowOpacity"
        )
        self._fade_in_anim.setDuration(120)
        self._fade_in_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fade_out_anim: QPropertyAnimation = QPropertyAnimation(
            self, b"windowOpacity"
        )
        self._fade_out_anim.setDuration(200)
        self._fade_out_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        _ = self._fade_out_anim.finished.connect(self.hide)

        self._init_status_ui()
        _ = self.statusSignal.connect(self.updateStatus)

    def _init_status_ui(self) -> None:
        # setWindowFlags recreates the native HWND — must re-apply WA_TranslucentBackground after
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedHeight(_HEIGHT)
        self.setMinimumWidth(160)
        self.setMaximumWidth(620)

        self.main_widget.setAutoFillBackground(False)
        self.main_layout.setContentsMargins(16, 0, 18, 0)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.setContentsMargins(0, 0, 0, 0)

        self.meter: LevelMeter = LevelMeter()

        self.status_label: QLabel = QLabel("Recording")
        self.status_label.setFont(_ui_font(11, QFont.Weight.DemiBold))
        self.status_label.setStyleSheet(f"background: transparent; color: {_TEXT};")
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

        self.detail_label: QLabel = QLabel()
        self.detail_label.setFont(_ui_font(10))
        self.detail_label.setStyleSheet(f"background: transparent; color: {_MUTED};")

        row.addWidget(self.meter)
        row.addWidget(self.status_label)
        row.addStretch()
        row.addWidget(self.detail_label)
        self.main_layout.addLayout(row)

    @override
    def paintEvent(self, a0: QPaintEvent | None) -> None:
        # Opaque pill, no DWM backdrop: Acrylic/Mica fills the whole HWND rect, which is what
        # produced the grey rectangle behind the old pill.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), _RADIUS, _RADIUS
        )
        painter.setPen(QPen(_HAIRLINE, 1))
        painter.setBrush(_PILL)
        painter.drawPath(path)

    def _position_window(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        # Width from font metrics, not sizeHint(): the layout hint still reflects the previous
        # text when this runs right after setText, so the pill was sometimes cut off.
        text_w = self.status_label.fontMetrics().horizontalAdvance(self.status_label.text())
        detail = self.detail_label.text()
        # Reserve "00:00" so the pill does not widen when the timer ticks past 9:59
        detail_w = self.detail_label.fontMetrics().horizontalAdvance("00:00" if detail[:1].isdigit() else detail)
        margins = self.main_layout.contentsMargins()
        w = margins.left() + self.meter.width() + 12 + text_w + 24 + detail_w + margins.right()
        w = max(160, min(w, 620))
        self.resize(w, _HEIGHT)
        self.move(
            geo.x() + (geo.width() - w) // 2, geo.y() + geo.height() - _HEIGHT - 48
        )

    def fade_in(self) -> None:
        self._position_window()
        if self._fade_out_anim.state() != QPropertyAnimation.State.Stopped:
            self._fade_out_anim.stop()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            super(BaseWindow, self).show()
        self._fade_in_anim.setStartValue(self.windowOpacity())
        self._fade_in_anim.setEndValue(1.0)
        self._fade_in_anim.start()

    def fade_out(self) -> None:
        self.meter.stop()
        if not self.isVisible():
            return
        if self._fade_in_anim.state() != QPropertyAnimation.State.Stopped:
            self._fade_in_anim.stop()
        self._fade_out_anim.setStartValue(self.windowOpacity())
        self._fade_out_anim.setEndValue(0.0)
        self._fade_out_anim.start()

    @pyqtSlot(float)
    def push_level(self, rms: float) -> None:
        self.meter.push(rms)
        if self._elapsed.isValid():
            seconds = int(self._elapsed.elapsed() / 1000)
            if seconds != self._shown_seconds:
                self._shown_seconds = seconds
                self.detail_label.setText(f"{seconds // 60}:{seconds % 60:02d}")

    def _show_busy(self, text: str, detail: str = "") -> None:
        self._elapsed.invalidate()
        self.status_label.setText(text)
        self.detail_label.setText(detail)
        self.meter.set_busy(_LLM if detail else QColor(_MUTED))
        self.fade_in()

    @override
    def closeEvent(self, a0: QCloseEvent | None) -> None:
        self.closeSignal.emit()
        super().closeEvent(a0)

    @pyqtSlot(str, bool)
    def updateStatus(self, status: str, use_llm: bool = False) -> None:
        if status == "recording":
            continuous_mode = (
                ConfigManager.get_config_value("recording_options", "recording_mode")
                == "continuous"
            )
            using_remote_api = bool(
                ConfigManager.get_config_value("model_options", "use_api")
            )
            if use_llm:
                llm_type = ConfigManager.get_config_value(
                    "llm_post_processing", "api_type"
                )
                using_remote_api = using_remote_api or (llm_type != "ollama")
            allow_continuous_api = ConfigManager.get_config_value(
                "recording_options", "allow_continuous_api"
            )

            if continuous_mode and using_remote_api and not allow_continuous_api:
                self.closeSignal.emit()
                return

            remote = continuous_mode and using_remote_api
            self.status_label.setText(
                "Recording to remote API" if remote else "Recording"
            )
            self.meter.set_live(_LLM if remote else _REC)
            self._elapsed.start()
            self._shown_seconds = 0
            self.detail_label.setText("0:00")
            self.fade_in()

        elif status == "warming_up":
            self._elapsed.invalidate()
            self.status_label.setText("Opening microphone")
            self.detail_label.setText("")
            self.meter.set_live(_REC)
            self.fade_in()

        elif status == "transcribing":
            self._show_busy("Transcribing")

        elif status in ("processing_llm_cleanup", "processing_llm_instruction"):
            api_type = (
                ConfigManager.get_config_value("llm_post_processing", "api_type")
                or "LLM"
            )
            verb = (
                "Cleaning up"
                if status == "processing_llm_cleanup"
                else "Running instruction"
            )
            self._show_busy(verb, str(api_type).capitalize())

        elif status in ("idle", "error", "cancel"):
            self._elapsed.invalidate()
            self.fade_out()


if __name__ == "__main__":
    import random

    app = QApplication(sys.argv)
    ConfigManager.initialize()
    w = StatusWindow()
    w.statusSignal.emit("recording", False)
    feed = QTimer()
    _ = feed.timeout.connect(lambda: w.push_level(random.uniform(0.001, 0.2)))
    feed.start(30)
    QTimer.singleShot(
        3000, lambda: (feed.stop(), w.statusSignal.emit("transcribing", False))
    )
    QTimer.singleShot(5000, lambda: w.statusSignal.emit("processing_llm_cleanup", True))
    QTimer.singleShot(7000, lambda: w.statusSignal.emit("idle", False))
    QTimer.singleShot(7500, app.quit)
    sys.exit(app.exec())
