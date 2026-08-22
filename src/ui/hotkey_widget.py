import os
import sys

from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QFrame,
)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Windows VK codes for left/right modifier distinction
_VK_MODIFIER_MAP: dict[int, str] = {
    0xA2: "lctrl",  0xA3: "rctrl",
    0xA0: "lshift", 0xA1: "rshift",
    0xA4: "lalt",   0xA5: "ralt",
    0x5B: "lwin",   0x5C: "rwin",
}

_QT_MODIFIER_FALLBACK: dict[int, str] = {
    Qt.Key.Key_Control.value: "ctrl",
    Qt.Key.Key_Shift.value:   "shift",
    Qt.Key.Key_Alt.value:     "alt",
    Qt.Key.Key_Meta.value:    "win",
    Qt.Key.Key_AltGr.value:   "ralt",
}

_QT_SPECIAL_KEYS: dict[int, str] = {
    Qt.Key.Key_Space.value:      "space",
    Qt.Key.Key_Return.value:     "enter",
    Qt.Key.Key_Enter.value:      "enter",
    Qt.Key.Key_Tab.value:        "tab",
    Qt.Key.Key_Backtab.value:    "tab",
    Qt.Key.Key_Backspace.value:  "backspace",
    Qt.Key.Key_Delete.value:     "delete",
    Qt.Key.Key_Insert.value:     "insert",
    Qt.Key.Key_Home.value:       "home",
    Qt.Key.Key_End.value:        "end",
    Qt.Key.Key_PageUp.value:     "page_up",
    Qt.Key.Key_PageDown.value:   "page_down",
    Qt.Key.Key_Up.value:         "up",
    Qt.Key.Key_Down.value:       "down",
    Qt.Key.Key_Left.value:       "left",
    Qt.Key.Key_Right.value:      "right",
    Qt.Key.Key_Print.value:      "print_screen",
    Qt.Key.Key_Pause.value:      "pause",
    Qt.Key.Key_CapsLock.value:   "caps_lock",
    Qt.Key.Key_ScrollLock.value: "scroll_lock",
    Qt.Key.Key_NumLock.value:    "num_lock",
    Qt.Key.Key_Escape.value:     None,  # ESC = cancel
}

_MODIFIER_DISPLAY_ORDER = [
    "lctrl", "rctrl", "ctrl",
    "lalt",  "ralt",  "alt",
    "lshift","rshift","shift",
    "lwin",  "rwin",  "win",
]

_KEY_GROUPS = [
    ("Modifiers", "ctrl  alt  shift  win\nlctrl  rctrl  lshift  rshift  lalt  ralt"),
    ("Letters",   "a – z"),
    ("Numbers",   "0 – 9"),
    ("Function",  "f1  f2  ...  f12"),
    ("Special",   "space  enter  tab  esc  backspace  delete\n"
                  "home  end  page_up  page_down\n"
                  "up  down  left  right  insert  print_screen"),
    ("Numpad",    "numpad0 – numpad9  multiply  add  subtract"),
    ("Media",     "mute  volume_up  volume_down\nplay_pause  next_track  prev_track"),
]


def _resolve_modifier(key_int: int, vk: int) -> str | None:
    if vk in _VK_MODIFIER_MAP:
        return _VK_MODIFIER_MAP[vk]
    return _QT_MODIFIER_FALLBACK.get(key_int)


def _get_key_name(key_int: int, event: QKeyEvent) -> str | None:
    if key_int in _QT_SPECIAL_KEYS:
        return _QT_SPECIAL_KEYS[key_int]  # None for ESC
    f1 = Qt.Key.Key_F1.value
    f24 = Qt.Key.Key_F24.value
    if f1 <= key_int <= f24:
        return f"f{key_int - f1 + 1}"
    text = event.text()
    if text and text.isprintable() and not text.isspace():
        return text.lower()
    return None


class HotkeyWidget(QWidget):
    """Drop-in replacement for QLineEdit for hotkey config fields.

    Adds a Record button that captures live keypresses via Qt key events
    (no pynput — avoids conflicts with the global key listener).
    setObjectName() propagates to the internal QLineEdit so save_setting()
    can find it via layout walk.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._capturing = False
        self._cancel_timer: QTimer | None = None
        self._original_value: str = ""
        self._held_mods: set[str] = set()
        self._peak_mods: set[str] = set()
        self._has_non_modifier = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText("e.g. ctrl+shift+space")

        self.record_btn = QPushButton("⏺ Record")
        self.record_btn.setFixedWidth(90)
        self.record_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.record_btn.clicked.connect(self._start_recording)

        row.addWidget(self.line_edit)
        row.addWidget(self.record_btn)
        outer.addLayout(row)
        outer.addWidget(self._build_ref_panel())

    def _build_ref_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("keyReferenceFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)
        for group_name, keys_text in _KEY_GROUPS:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            name_lbl = QLabel(f"{group_name}:")
            name_lbl.setObjectName("keyRefGroupName")
            name_lbl.setFixedWidth(68)
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
            keys_lbl = QLabel(keys_text)
            keys_lbl.setObjectName("keyRefKeys")
            keys_lbl.setWordWrap(True)
            row.addWidget(name_lbl)
            row.addWidget(keys_lbl, 1)
            layout.addLayout(row)
        return frame

    # ── Public API ──────────────────────────────────────────────────────────

    def text(self) -> str:
        return self.line_edit.text()

    def setText(self, value: str) -> None:
        self.line_edit.setText(value)

    def setObjectName(self, name: str) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        super().setObjectName(name)  # type: ignore[arg-type]
        self.line_edit.setObjectName(name)

    # ── Recording ───────────────────────────────────────────────────────────

    def _start_recording(self) -> None:
        if self._capturing:
            return
        self._original_value = self.line_edit.text()
        self.line_edit.clear()
        self.line_edit.setPlaceholderText("Press a key combination...")
        self.record_btn.setText("● Listening...")
        self.record_btn.setStyleSheet("color: #ff4444;")
        self._held_mods = set()
        self._peak_mods = set()
        self._has_non_modifier = False
        self._capturing = True

        self.line_edit.installEventFilter(self)
        self.line_edit.setFocus()

        self._cancel_timer = QTimer(self)
        self._cancel_timer.setSingleShot(True)
        self._cancel_timer.timeout.connect(self._cancel_recording)
        self._cancel_timer.start(5000)

    def eventFilter(self, obj, event) -> bool:
        if not self._capturing or obj is not self.line_edit:
            return super().eventFilter(obj, event)

        if event.type() == QEvent.Type.KeyPress:
            self._handle_key_press(event)
            return True
        if event.type() == QEvent.Type.KeyRelease:
            self._handle_key_release(event)
            return True

        return super().eventFilter(obj, event)

    def _handle_key_press(self, event: QKeyEvent) -> None:
        key = event.key()
        vk = event.nativeVirtualKey()

        if key == Qt.Key.Key_Escape.value or key == Qt.Key.Key_Escape:
            self._cancel_recording()
            return

        mod = _resolve_modifier(key if isinstance(key, int) else key.value, vk)
        if mod:
            self._held_mods.add(mod)
            self._peak_mods = set(self._held_mods)
        else:
            self._has_non_modifier = True

    def _handle_key_release(self, event: QKeyEvent) -> None:
        key = event.key()
        vk = event.nativeVirtualKey()
        key_int = key if isinstance(key, int) else key.value

        mod = _resolve_modifier(key_int, vk)
        if mod:
            self._held_mods.discard(mod)
            if not self._held_mods and not self._has_non_modifier and self._peak_mods:
                combo = self._build_combo(self._peak_mods, None)
                self._finish_recording(combo)
        else:
            name = _get_key_name(key_int, event)
            if name:
                combo = self._build_combo(self._held_mods, name)
                self._finish_recording(combo)

    def _build_combo(self, mods: set[str], key_name: str | None) -> str:
        parts = [m for m in _MODIFIER_DISPLAY_ORDER if m in mods]
        if key_name:
            parts.append(key_name)
        return "+".join(parts)

    def _finish_recording(self, combo: str) -> None:
        if self._cancel_timer:
            self._cancel_timer.stop()
        self._capturing = False
        self.line_edit.removeEventFilter(self)
        self.line_edit.setText(combo)
        self.line_edit.setPlaceholderText("e.g. ctrl+shift+space")
        self._reset_button()

    def _cancel_recording(self) -> None:
        self._capturing = False
        self.line_edit.removeEventFilter(self)
        if self._cancel_timer:
            self._cancel_timer.stop()
        self.line_edit.setText(self._original_value)
        self.line_edit.setPlaceholderText("e.g. ctrl+shift+space")
        self._reset_button()

    def _reset_button(self) -> None:
        self.record_btn.setText("⏺ Record")
        self.record_btn.setStyleSheet("")
