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
    QSlider,
    QTextEdit,
    QVBoxLayout,
)

from utils import ConfigManager

_RADIUS = 18
_SHADOW_MARGIN = 16  # empty ring around the card where the drop shadow is painted
_STYLE = """
QTextEdit {
    background-color: #202226;
    color: #E8E6E1;
    border: 1px solid #33363C;
    border-radius: 8px;
    padding: 12px 14px;
    font-family: "Segoe UI Variable Text", "Segoe UI";
    font-size: 12pt;
    selection-background-color: #4A4D55;
    selection-color: #E8E6E1;
}
QTextEdit:focus {
    border: 1px solid #8C8F96;
}
QPushButton {
    background-color: transparent;
    color: #E8E6E1;
    border: 1px solid #33363C;
    border-radius: 6px;
    padding: 5px 16px;
    font-family: "Segoe UI Variable Text", "Segoe UI";
    font-size: 10pt;
}
QPushButton:hover { background-color: #26282D; border-color: #4A4D55; }
QPushButton:pressed { background-color: #33363C; }
QPushButton:focus { border-color: #8C8F96; }
QSlider::groove:horizontal { height: 4px; background: #33363C; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #C9C7C2; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #E8E6E1; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: #FFFFFF; }
QLabel#timeLabel { color: #8C8F96; font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 9pt; }
"""

# ponytail: plain text, no ⏪/⏩/⏸ — Windows renders those as colour emoji that clash with the palette
_PLAY_LABEL = "Odtwórz"
_PAUSE_LABEL = "Pauza"
_EDITOR_MIN_H = 64
_EDITOR_MAX_H = 380
_DIALOG_WIDTH = 760
_SEEK_FALLBACK = 5.0


def _read_seek_step() -> float:
    """Skok przewijania z ustawień, w sekundach.

    Wartość <= 0 wyłączyłaby przewijanie po cichu (przycisk klikalny, nic nie robi),
    a tekst z pola tekstowego w YAML-u wywaliłby konstruktor okna razem z transkrypcją
    w środku — stąd fallback zamiast zaufania schematowi.
    """
    raw: object = ConfigManager.get_config_value(
        "training_data", "review_seek_seconds"
    )
    if not isinstance(raw, (int, float)) or isinstance(raw, bool) or raw <= 0:
        return _SEEK_FALLBACK
    return float(raw)

_HINT = (
    '<span style="color:#C9C7C2;">Enter</span>'
    '<span style="color:#5E6168;"> zatwierdź &nbsp;&nbsp;&nbsp; </span>'
    '<span style="color:#C9C7C2;">Shift+Enter</span>'
    '<span style="color:#5E6168;"> nowa linia &nbsp;&nbsp;&nbsp; </span>'
    '<span style="color:#C9C7C2;">Esc</span>'
    '<span style="color:#5E6168;"> anuluj &nbsp;&nbsp;&nbsp; </span>'
    '<span style="color:#C9C7C2;">Ctrl+Space</span>'
    '<span style="color:#5E6168;"> odtwórz / pauza</span>'
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
    slider: QSlider | None
    time_label: QLabel | None
    _pos_timer: QTimer
    _sample_rate: int
    _play_gen: int
    _seek_step: float
    _offset: float  # seconds of the recording already played back
    _started: float | None  # monotonic clock at the last play(), None while not playing

    def __init__(
        self, text: str, audio: np.ndarray | None = None, sample_rate: int = 16000
    ):
        super().__init__()
        self._audio = audio
        self._sample_rate = sample_rate
        self._play_gen = 0
        # Odczyt w __init__, nie przy każdym kliknięciu: etykieta przycisku i skok
        # muszą pokazywać tę samą liczbę przez całe życie okna.
        self._seek_step = _read_seek_step()
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
        self.setFixedWidth(_DIALOG_WIDTH)

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
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        doc = self.editor.document()
        if doc is not None:
            _ = doc.contentsChanged.connect(self._fit_editor)
        layout.addWidget(self.editor)

        self.play_btn = None
        self.stop_btn = None
        self.slider = None
        self.time_label = None
        if audio is not None and len(audio) > 0:
            self.play_btn = QPushButton(_PLAY_LABEL)
            self.play_btn.setFixedWidth(96)
            step = self._seek_step
            label = f"{step:g}" if step % 1 else f"{int(step)}"
            back_btn = QPushButton(f"−{label} s")
            fwd_btn = QPushButton(f"+{label} s")

            self.slider = QSlider(Qt.Orientation.Horizontal)
            self.slider.setRange(0, int(self._duration() * 1000))
            # Clicking the groove jumps one seek step, same as the buttons
            self.slider.setPageStep(int(step * 1000))
            self.slider.setSingleStep(1000)  # arrows / wheel: 1 s
            _ = self.slider.sliderReleased.connect(self._seek_to_slider)
            _ = self.slider.actionTriggered.connect(self._on_slider_action)
            self.time_label = QLabel()
            self.time_label.setObjectName("timeLabel")
            self._update_position()

            controls = QHBoxLayout()
            controls.setSpacing(8)
            for w, slot in (
                (self.play_btn, self.toggle_play),
                (back_btn, lambda: self._seek(-self._seek_step)),
                (self.slider, None),
                (fwd_btn, lambda: self._seek(self._seek_step)),
                (self.time_label, None),
            ):
                # NoFocus: a control must never steal focus from the editor, or Enter would
                # click it instead of accepting the dialog.
                w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                if slot is not None and isinstance(w, QPushButton):
                    _ = w.clicked.connect(slot)
                controls.addWidget(w, 1 if w is self.slider else 0)
            layout.addLayout(controls)

            self._pos_timer = QTimer(self)
            _ = self._pos_timer.timeout.connect(self._update_position)
            self._pos_timer.start(100)

        hint = QLabel(_HINT)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet('font-family: "Segoe UI"; font-size: 9pt;')
        layout.addWidget(hint)

        self._fit_editor()
        self._center()
        self.editor.setFocus()
        # Document height depends on the viewport width, known only after the first layout
        QTimer.singleShot(0, self._fit_editor)

    def _duration(self) -> float:
        return 0.0 if self._audio is None else len(self._audio) / self._sample_rate

    def _position(self) -> float:
        """Current playhead in seconds (wall clock since the last play, see toggle_play)."""
        pos = self._offset
        if self._started is not None:
            pos += time.monotonic() - self._started
        return min(pos, self._duration())

    def _update_position(self) -> None:
        if self.slider is None or self.time_label is None:
            return
        pos = self._position()
        if not self.slider.isSliderDown():
            self.slider.setValue(int(pos * 1000))
        else:
            pos = self.slider.value() / 1000
        dur = self._duration()
        self.time_label.setText(f"{int(pos) // 60}:{int(pos) % 60:02d} / {int(dur) // 60}:{int(dur) % 60:02d}")

    def _seek_to_slider(self) -> None:
        if self.slider is not None:
            self._seek(self.slider.value() / 1000 - self._position())

    def _on_slider_action(self, action: int) -> None:
        """Groove click, wheel, arrows, Home/End: seek now — nothing else would, and the
        position timer would snap the thumb back. Drags seek on release instead."""
        if self.slider is None or action == QSlider.SliderAction.SliderNoAction.value:
            return
        if action == QSlider.SliderAction.SliderMove.value and self.slider.isSliderDown():
            return
        # sliderPosition() already holds the target; value() is applied only after this signal
        self._seek(self.slider.sliderPosition() / 1000 - self._position())

    def _fit_editor(self) -> None:
        """Grow/shrink the editor with its text; past the cap the editor scrolls instead."""
        doc = self.editor.document()
        if doc is None:
            return
        margins = self.editor.contentsMargins()
        h = int(doc.size().height()) + margins.top() + margins.bottom() + 2 * int(doc.documentMargin()) + 26
        self.editor.setFixedHeight(max(_EDITOR_MIN_H, min(h, _EDITOR_MAX_H)))
        # Keep the top edge where it is while typing — re-centring would make the card jump
        top = self.y()
        self.adjustSize()
        self.move(self.x(), top)

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
        painter.setBrush(QBrush(QColor("#18191C")))
        painter.setPen(QPen(QColor("#33363C"), 1))
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

            self._play_from_offset()
        except Exception as e:
            # No output device must not take down the dialog holding the transcription.
            ConfigManager.console_print(f"Playback failed: {e}")
            self.stop_play()

    def _play_from_offset(self) -> None:
        """Play the slice starting at `self._offset`. Caller guarantees audio exists."""
        assert self._audio is not None and self.play_btn is not None
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

    def _seek(self, delta: float) -> None:
        """Move the playhead by `delta` seconds, clamped to the recording.

        Clamping matters on both ends: a negative offset would index the array from the
        back, playing the tail instead of the head. Past the end there is nothing left
        to play at all — parking the playhead just short of it would emit a ~10 ms
        click and then rewind anyway, so seeking past the end simply ends playback.
        """
        if self._audio is None:
            return
        duration = len(self._audio) / self._sample_rate
        started = self._started
        was_playing = started is not None
        if started is not None:
            sd.stop()
            self._offset += time.monotonic() - started
            self._started = None
        target = max(self._offset + delta, 0.0)
        self._play_gen += 1  # any pending end-of-playback timer is now stale
        if target >= duration:
            # Krótkie nagranie i jeden klik ⏩ wystarczą, żeby tu wejść.
            self.stop_play()
            return
        self._offset = target
        if was_playing:
            try:
                self._play_from_offset()
            except Exception as e:
                ConfigManager.console_print(f"Playback failed: {e}")
                self.stop_play()

    def stop_play(self) -> None:
        """Stop playback and rewind, so the next play starts from the beginning."""
        sd.stop()
        self._started = None
        self._offset = 0.0
        self._play_gen += 1
        if self.play_btn is not None:
            try:
                self.play_btn.setText(_PLAY_LABEL)
            except RuntimeError:
                # Dialog already torn down on the C++ side (accepted mid-playback) —
                # stopping the sound is all that is left to do.
                pass

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
        # stop_play() rather than sd.stop(): it also bumps the generation counter, so the
        # pending end-of-playback timer becomes a no-op instead of firing at a dialog
        # whose buttons Qt has already destroyed.
        dialog.stop_play()
        result = dialog.editor.toPlainText().strip() if accepted else None
        # hide() before returning: the caller types into the app underneath, and it only
        # regains focus once this topmost window is actually gone. deleteLater() alone
        # would not remove it until control returns to the main event loop.
        hwnd = int(dialog.winId())
        dialog.hide()
        _wait_until_not_foreground(hwnd)
        dialog.deleteLater()
        return result or None
