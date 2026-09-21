"""Modal transcription-review dialog shown between transcription and typing.

Enter accepts, Shift+Enter inserts a newline, Esc cancels (nothing typed, nothing saved).
"""

import sys
import time
from typing import override

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import Qt, QRectF, QTimer
from PyQt6.QtGui import (
    QColor,
    QBrush,
    QPen,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QKeyEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from utils import ConfigManager

_RADIUS = 18
_SHADOW_MARGIN = 16  # empty ring around the card where the drop shadow is painted
_STYLE = """
QTextEdit {
    background-color: rgba(17, 17, 27, 170);
    color: #cdd6f4;
    border: 1px solid rgba(137, 180, 250, 45);
    border-radius: 10px;
    padding: 12px 14px;
    font-family: "Segoe UI";
    font-size: 12pt;
    selection-background-color: #89b4fa;
    selection-color: #11111b;
}
QTextEdit:focus {
    border: 1px solid rgba(137, 180, 250, 140);
}
QPushButton {
    background-color: rgba(137, 180, 250, 30);
    color: #cdd6f4;
    border: 1px solid rgba(137, 180, 250, 70);
    border-radius: 9px;
    padding: 5px 18px;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QPushButton:hover {
    background-color: rgba(137, 180, 250, 55);
}
"""

_PLAY_LABEL = "▶  Odtwórz"
_PAUSE_LABEL = "⏸  Pauza"
_STOP_LABEL = "■  Stop"

_HINT = (
    '<span style="color:#89b4fa;">Enter</span>'
    '<span style="color:rgba(205,214,244,120);"> — zatwierdź &nbsp;·&nbsp; </span>'
    '<span style="color:#89b4fa;">Shift+Enter</span>'
    '<span style="color:rgba(205,214,244,120);"> — nowa linia &nbsp;·&nbsp; </span>'
    '<span style="color:#89b4fa;">Esc</span>'
    '<span style="color:rgba(205,214,244,120);"> — anuluj &nbsp;·&nbsp; </span>'
    '<span style="color:#89b4fa;">Ctrl+Space</span>'
    '<span style="color:rgba(205,214,244,120);"> — odtwórz / pauza</span>'
)


def _wait_until_not_foreground(hwnd: int, timeout: float = 0.5) -> None:
    """Block until hwnd is no longer the foreground window (or timeout).

    hide() only posts the activation change; Windows hands focus back to the previous
    window a few messages later. The caller types immediately after us, so without this
    wait the keystrokes land in the dialog that is on its way out.

    Safe to block here — we only poll our OWN window and keep pumping our event loop.
    No AttachThreadInput, so a wedged foreign app cannot drag us down with it.
    """
    if sys.platform != "win32":
        return
    try:
        import win32gui

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if win32gui.GetForegroundWindow() != hwnd:
                return
            time.sleep(0.01)
    except Exception:
        pass


def _grab_foreground(hwnd: int) -> None:
    """Make hwnd the active, keyboard-focused window.

    Windows refuses SetForegroundWindow from a process that did not receive the last
    input event, so we briefly attach our input queue to the current foreground thread.

    Deliberately fire-and-forget: one attempt, no retry loop, no sleeps. Holding the
    attachment while blocking freezes input for BOTH processes — that is a desktop-wide
    hang, not a local one. The detach is unconditional.

    There is no counterpart for restoring focus on close: hiding a topmost window makes
    Windows re-activate the previous one by itself, so the risky call is not needed there.
    """
    if sys.platform != "win32":
        return
    try:
        import win32api
        import win32gui
        import win32process

        current = win32gui.GetForegroundWindow()
        if not current or current == hwnd:
            return

        our_tid = win32api.GetCurrentThreadId()
        fg_tid = win32process.GetWindowThreadProcessId(current)[0]
        attached = fg_tid and fg_tid != our_tid
        if attached:
            win32process.AttachThreadInput(fg_tid, our_tid, True)
        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached:
                win32process.AttachThreadInput(fg_tid, our_tid, False)
    except Exception:
        pass


class _Editor(QTextEdit):
    """QTextEdit that treats bare Enter as "submit" instead of "newline".

    The key handling must live here, not on the dialog: the editor has focus, so it
    receives the key event first and would swallow Enter before the dialog sees it.
    """

    @override
    def keyPressEvent(self, e: QKeyEvent | None) -> None:
        if (
            e is not None
            and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ):
            dialog = self.window()
            if isinstance(dialog, QDialog):
                dialog.accept()
            return
        if (
            e is not None
            and e.key() == Qt.Key.Key_Space
            and e.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            dialog = self.window()
            if isinstance(dialog, ReviewDialog):
                dialog.toggle_play()
            return
        super().keyPressEvent(e)


class ReviewDialog(QDialog):
    editor: _Editor
    play_btn: QPushButton | None
    _audio: np.ndarray | None
    stop_btn: QPushButton | None
    _sample_rate: int
    _play_gen: int
    _offset: float  # seconds of the recording already played back
    _started: float | None  # monotonic clock at the last play(), None while not playing

    def __init__(
        self, text: str, audio: np.ndarray | None = None, sample_rate: int = 16000
    ):
        super().__init__()
        self._audio = audio
        self._sample_rate = sample_rate
        self._play_gen = 0
        self._offset = 0.0
        self._started = None
        self.setWindowTitle("Review transcription")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(_STYLE)
        self.resize(760, 260)

        # ponytail: Qt's own shadow instead of DWM Mica — Mica is not supported on a
        # layered (translucent) window, and mixing them made the card flicker.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(38)
        shadow.setColor(QColor(0, 0, 0, 190))
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)

        m = _SHADOW_MARGIN
        layout = QVBoxLayout(self)
        layout.setContentsMargins(m + 16, m + 14, m + 16, m + 12)
        layout.setSpacing(10)

        self.editor = _Editor(self)
        self.editor.setPlainText(text)
        self.editor.setAcceptRichText(False)
        self.editor.moveCursor(self.editor.textCursor().MoveOperation.End)
        layout.addWidget(self.editor)

        self.play_btn = None
        self.stop_btn = None
        if audio is not None and len(audio) > 0:
            self.play_btn = QPushButton(_PLAY_LABEL)
            self.stop_btn = QPushButton(_STOP_LABEL)
            controls = QHBoxLayout()
            controls.addStretch()
            for btn, slot in (
                (self.play_btn, self.toggle_play),
                (self.stop_btn, self.stop_play),
            ):
                # NoFocus: a button must never steal focus from the editor, or Enter would
                # click it instead of accepting the dialog.
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                _ = btn.clicked.connect(slot)
                controls.addWidget(btn)
            controls.addStretch()
            layout.addLayout(controls)

        hint = QLabel(_HINT)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet('font-family: "Segoe UI"; font-size: 9pt;')
        layout.addWidget(hint)

        self._center()
        self.editor.setFocus()

    def _center(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.x() + (geo.width() - self.width()) // 2,
            geo.y() + (geo.height() - self.height()) // 2,
        )

    @override
    def paintEvent(self, a0: QPaintEvent | None) -> None:
        card = QRectF(self.rect()).adjusted(
            _SHADOW_MARGIN, _SHADOW_MARGIN, -_SHADOW_MARGIN, -_SHADOW_MARGIN
        )
        path = QPainterPath()
        path.addRoundedRect(card, _RADIUS, _RADIUS)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor(24, 24, 34, 242)))
        painter.setPen(QPen(QColor(137, 180, 250, 60), 1))
        painter.drawPath(path)

    def toggle_play(self) -> None:
        """Start playback, or pause it — resuming continues where the pause left off.

        sounddevice has no pause, so "resume" is a fresh play() of the remaining slice.
        The position is tracked as wall-clock time since the last start rather than by
        polling the stream: a few ms of drift per pause is invisible without a seek bar.
        """
        if self.play_btn is None or self._audio is None:
            return
        try:
            if self._started is not None:
                sd.stop()
                self._offset += time.monotonic() - self._started
                self._started = None
                self._play_gen += 1  # the pending end-of-playback timer is now stale
                self.play_btn.setText(_PLAY_LABEL)
                return

            start = int(self._offset * self._sample_rate)
            if start >= len(self._audio):  # finished earlier — replay from the top
                self._offset = 0.0
                start = 0
            remaining = self._audio[start:]
            sd.play(remaining, self._sample_rate)
            self._started = time.monotonic()
            self.play_btn.setText(_PAUSE_LABEL)
            # ponytail: a timer instead of sd.wait() — waiting would block the dialog's
            # event loop. singleShot cannot be cancelled, so a timer left over from an
            # aborted playback would reset the label mid-replay; the generation counter
            # makes it a no-op.
            self._play_gen += 1
            gen = self._play_gen
            ms = int(len(remaining) / self._sample_rate * 1000) + 100
            QTimer.singleShot(ms, lambda: self._on_playback_end(gen))
        except Exception as e:
            # No output device must not take down the dialog holding the transcription.
            ConfigManager.console_print(f"Playback failed: {e}")
            self.stop_play()

    def stop_play(self) -> None:
        """Stop playback and rewind, so the next play starts from the beginning."""
        sd.stop()
        self._started = None
        self._offset = 0.0
        self._play_gen += 1
        if self.play_btn is not None:
            self.play_btn.setText(_PLAY_LABEL)

    def _on_playback_end(self, gen: int) -> None:
        if gen == self._play_gen:
            self.stop_play()

    @staticmethod
    def get_text(
        text: str, audio: np.ndarray | None = None, sample_rate: int = 16000
    ) -> str | None:
        """Show the dialog modally. Returns the edited text, or None if cancelled."""
        dialog = ReviewDialog(text, audio, sample_rate)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        # Qt's activateWindow() alone loses to the Win32 foreground lock; force it, then
        # focus the editor (setFocus only takes effect once the window is active).
        _grab_foreground(int(dialog.winId()))
        dialog.editor.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        # One stop for every exit path (Enter, Esc, close) — exec() returns on all of them.
        sd.stop()
        result = dialog.editor.toPlainText().strip() if accepted else None
        # hide() before returning: the caller types into the app underneath, and it only
        # regains focus once this topmost window is actually gone. deleteLater() alone
        # would not remove it until control returns to the main event loop.
        hwnd = int(dialog.winId())
        dialog.hide()
        _wait_until_not_foreground(hwnd)
        dialog.deleteLater()
        return result or None
