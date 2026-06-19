import sys
import os
from typing import override

from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
    pyqtSlot,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
)
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QFont, QCloseEvent, QPaintEvent, QPainter, QBrush, QColor, QPainterPath
from PyQt6.QtWidgets import QApplication, QLabel, QHBoxLayout, QSizePolicy

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from ui.base_window import BaseWindow, apply_mica
from utils import ConfigManager


_LABEL_STYLE = "QLabel { background: transparent; border: none; color: #f0f0f0; }"
_RADIUS = 26


class StatusWindow(BaseWindow):
    statusSignal: pyqtSignal = pyqtSignal(str, bool)
    closeSignal: pyqtSignal = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("WhisperWriter Status", 320, 52, show_title_bar=False)
        self._mica_active: bool = False
        self._pulse_timer: QTimer = QTimer()
        self._pulse_timer.timeout.connect(self._update_pulse)
        self._pulse_alpha: float = 0.3
        self._pulse_dir: int = 1
        self._pulse_color: tuple[int, int, int] = (255, 68, 68)

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
        self.statusSignal.connect(self.updateStatus)

    def _init_status_ui(self) -> None:
        # setWindowFlags recreates the native HWND — must re-apply WA_TranslucentBackground after
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # Dynamic width: shrinks/grows with text; fixed height for pill shape
        self.setFixedHeight(52)
        self.setMinimumWidth(180)
        self.setMaximumWidth(620)

        self.main_widget.setObjectName("statusContent")
        self.main_layout.setContentsMargins(16, 0, 16, 0)
        self.main_layout.setSpacing(0)

        # Prevent Qt from auto-filling main_widget background (would cover our rounded paintEvent)
        self.main_widget.setAutoFillBackground(False)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.setContentsMargins(0, 0, 0, 0)

        self.icon_label: QLabel = QLabel("🎙")
        self.icon_label.setFont(QFont("Segoe UI Emoji", 15))
        self.icon_label.setFixedSize(26, 26)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet(_LABEL_STYLE)

        self.status_label: QLabel = QLabel("Recording...")
        self.status_label.setFont(QFont("Segoe UI", 12))
        self.status_label.setStyleSheet(_LABEL_STYLE)
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

        self.pulse_dot: QLabel = QLabel()
        self.pulse_dot.setFixedSize(10, 10)
        self.pulse_dot.setStyleSheet(
            "QLabel { background: rgba(255,68,68,0.3); border-radius: 5px; }"
        )
        self.pulse_dot.hide()

        row.addWidget(self.icon_label)
        row.addWidget(self.status_label)
        row.addStretch()
        row.addWidget(self.pulse_dot)

        self.main_layout.addLayout(row)

    @override
    def paintEvent(self, a0: QPaintEvent | None) -> None:
        # Draw rounded rect directly — area outside path is transparent (WA_TranslucentBackground)
        # With Mica: semi-transparent tint over DWM blur. Without: opaque dark pill.
        alpha = 55 if self._mica_active else 230
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), _RADIUS, _RADIUS)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor(28, 28, 38, alpha)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)

    def _position_window(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        # Fit width to text content (icon + padding + text + padding + dot)
        hint = self.status_label.sizeHint().width() + 24 + 10 + 32
        w = max(180, min(hint, 620))
        self.resize(w, 52)
        x = (geo.width() - w) // 2
        y = geo.height() - 52 - 80
        self.move(x, y)

    def fade_in(self) -> None:
        self._position_window()
        if self._fade_out_anim.state() != QPropertyAnimation.State.Stopped:
            self._fade_out_anim.stop()
        self.setWindowOpacity(0.0)
        super(BaseWindow, self).show()
        if not self._mica_active:
            self._mica_active = apply_mica(int(self.winId()), backdrop_type=3)
            self.update()  # repaint with correct alpha for Mica vs fallback
        self._fade_in_anim.setStartValue(0.0)
        self._fade_in_anim.setEndValue(1.0)
        self._fade_in_anim.start()

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        if self._fade_in_anim.state() != QPropertyAnimation.State.Stopped:
            self._fade_in_anim.stop()
        self._pulse_timer.stop()
        self.pulse_dot.hide()
        self._fade_out_anim.setStartValue(self.windowOpacity())
        self._fade_out_anim.setEndValue(0.0)
        self._fade_out_anim.start()

    def _start_pulse(self, color: tuple[int, int, int] = (255, 68, 68)) -> None:
        self._pulse_color = color
        self._pulse_alpha = 0.3
        self._pulse_dir = 1
        self.pulse_dot.show()
        self._pulse_timer.start(30)

    def _update_pulse(self) -> None:
        self._pulse_alpha += self._pulse_dir * 0.04
        if self._pulse_alpha >= 1.0:
            self._pulse_alpha = 1.0
            self._pulse_dir = -1
        elif self._pulse_alpha <= 0.3:
            self._pulse_alpha = 0.3
            self._pulse_dir = 1
        r, g, b = self._pulse_color
        self.pulse_dot.setStyleSheet(
            f"QLabel {{ background: rgba({r},{g},{b},{self._pulse_alpha:.2f}); border-radius: 5px; }}"
        )

    @override
    def closeEvent(self, a0: QCloseEvent | None) -> None:
        self.closeSignal.emit()
        super().closeEvent(a0)

    @pyqtSlot(str, bool)
    def updateStatus(self, status: str, use_llm: bool = False) -> None:
        if status == "recording":
            self.icon_label.setText("🎙")

            continuous_mode = (
                ConfigManager.get_config_value("recording_options", "recording_mode")
                == "continuous"
            )
            using_api = ConfigManager.get_config_value("model_options", "use_api")
            allow_continuous_api = ConfigManager.get_config_value(
                "recording_options", "allow_continuous_api"
            )

            using_remote_api = using_api
            if use_llm:
                llm_type = ConfigManager.get_config_value(
                    "llm_post_processing", "api_type"
                )
                using_remote_api = using_remote_api or (llm_type != "ollama")

            if continuous_mode and using_remote_api and not allow_continuous_api:
                self.closeSignal.emit()
                return

            if continuous_mode and using_remote_api:
                self.status_label.setText("⚠ Continuous Recording (Remote API)")
                self._start_pulse((255, 140, 0))
            else:
                self.status_label.setText("Recording...")
                self._start_pulse((255, 68, 68))

            self.fade_in()

        elif status == "warming_up":
            self.icon_label.setText("🎙")
            self.status_label.setText("Preparing microphone...")
            self._pulse_timer.stop()
            self.pulse_dot.hide()
            self.fade_in()

        elif status == "transcribing":
            self.icon_label.setText("✍")
            self.status_label.setText("Transcribing...")
            self._pulse_timer.stop()
            self.pulse_dot.hide()
            if not self.isVisible():
                self.fade_in()

        elif status == "processing_llm_cleanup":
            self.icon_label.setText("✍")
            api_type = (
                ConfigManager.get_config_value("llm_post_processing", "api_type")
                or "LLM"
            )
            self.status_label.setText(f"Cleaning up with {api_type.upper()}...")
            self._pulse_timer.stop()
            self.pulse_dot.hide()
            if not self.isVisible():
                self.fade_in()

        elif status == "processing_llm_instruction":
            self.icon_label.setText("✍")
            api_type = (
                ConfigManager.get_config_value("llm_post_processing", "api_type")
                or "LLM"
            )
            self.status_label.setText(f"Processing with {api_type.upper()}...")
            self._pulse_timer.stop()
            self.pulse_dot.hide()
            if not self.isVisible():
                self.fade_in()

        if status in ("idle", "error", "cancel"):
            self.fade_out()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = StatusWindow()
    w.statusSignal.emit("recording", False)
    QTimer.singleShot(3000, lambda: w.statusSignal.emit("transcribing", False))
    QTimer.singleShot(5000, lambda: w.statusSignal.emit("idle", False))
    sys.exit(app.exec())
