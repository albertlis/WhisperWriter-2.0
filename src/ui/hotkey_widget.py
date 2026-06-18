import os
import sys
from typing import override

from PyQt6.QtCore import Qt, QTimer
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

_kb = None
try:
    from pynput import keyboard as _kb  # type: ignore[assignment]

    _pynput_available = True
except ImportError:
    _pynput_available = False

if _kb is not None:
    _modifier_names: dict[object, str] = {
        _kb.Key.ctrl_l: "ctrl",
        _kb.Key.ctrl_r: "ctrl",
        _kb.Key.alt_l: "alt",
        _kb.Key.alt_r: "alt",
        _kb.Key.shift_l: "shift",
        _kb.Key.shift_r: "shift",
        _kb.Key.cmd_l: "win",
        _kb.Key.cmd_r: "win",
    }
    _special_names: dict[object, str] = {
        _kb.Key.space: "space",
        _kb.Key.enter: "enter",
        _kb.Key.tab: "tab",
        _kb.Key.backspace: "backspace",
        _kb.Key.delete: "delete",
        _kb.Key.home: "home",
        _kb.Key.end: "end",
        _kb.Key.page_up: "page_up",
        _kb.Key.page_down: "page_down",
        _kb.Key.up: "up",
        _kb.Key.down: "down",
        _kb.Key.left: "left",
        _kb.Key.right: "right",
        _kb.Key.insert: "insert",
        _kb.Key.caps_lock: "caps_lock",
        _kb.Key.num_lock: "num_lock",
        _kb.Key.scroll_lock: "scroll_lock",
        _kb.Key.pause: "pause",
        _kb.Key.print_screen: "print_screen",
        _kb.Key.media_play_pause: "play_pause",
        _kb.Key.media_next: "next_track",
        _kb.Key.media_previous: "prev_track",
        _kb.Key.media_volume_mute: "mute",
        _kb.Key.media_volume_down: "volume_down",
        _kb.Key.media_volume_up: "volume_up",
    }
else:
    _modifier_names = {}
    _special_names = {}

_MODIFIER_DISPLAY_ORDER = ["ctrl", "alt", "shift", "win"]

_KEY_GROUPS = [
    ("Modifiers", "ctrl  alt  shift  win"),
    ("Letters", "a – z"),
    ("Numbers", "0 – 9"),
    ("Function", "f1  f2  ...  f12"),
    (
        "Special",
        "space  enter  tab  esc  backspace  delete\n"
        "home  end  page_up  page_down\n"
        "up  down  left  right  insert  print_screen",
    ),
    ("Numpad", "numpad0 – numpad9  multiply  add  subtract"),
    ("Media", "mute  volume_up  volume_down\nplay_pause  next_track  prev_track"),
]


def _get_key_name(key) -> str | None:
    if not _pynput_available:
        return None
    if key in _special_names:
        return _special_names[key]
    if hasattr(key, "name") and key.name and key.name.startswith("f"):
        rest = key.name[1:]
        if rest.isdigit():
            return key.name
    if hasattr(key, "char") and key.char:
        return key.char.lower()
    return None


class HotkeyWidget(QWidget):
    """Drop-in replacement for QLineEdit for hotkey config fields.

    Adds a Record button that captures live keypresses and a key-name
    reference panel. setObjectName() propagates to the internal QLineEdit
    so save_setting() can find it via layout walk.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._listener = None
        self._cancel_timer: QTimer | None = None
        self._original_value: str = ""
        self._held_mods: set[str] = set()
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
        if _pynput_available:
            self.record_btn.clicked.connect(self._start_recording)
        else:
            self.record_btn.setEnabled(False)
            self.record_btn.setToolTip("pynput not available")

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

    @override
    def setObjectName(self, name: str) -> None:
        super().setObjectName(name)
        self.line_edit.setObjectName(name)

    # ── Recording ───────────────────────────────────────────────────────────

    def _start_recording(self) -> None:
        self._original_value = self.line_edit.text()
        self.line_edit.clear()
        self.line_edit.setPlaceholderText("Press a key combination...")
        self.record_btn.setText("● Listening...")
        self.record_btn.setStyleSheet("color: #ff4444;")
        self._held_mods = set()

        self._listener = _kb.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

        self._cancel_timer = QTimer(self)
        self._cancel_timer.setSingleShot(True)
        self._cancel_timer.timeout.connect(self._cancel_recording)
        self._cancel_timer.start(5000)

    def _on_press(self, key) -> None:
        mod = _modifier_names.get(key)
        if mod:
            self._held_mods.add(mod)

    def _on_release(self, key) -> bool | None:
        if key == _kb.Key.esc:
            QTimer.singleShot(0, self._cancel_recording)
            return False

        if key in _modifier_names:
            return None

        key_name = _get_key_name(key)
        if key_name:
            ordered_mods = [m for m in _MODIFIER_DISPLAY_ORDER if m in self._held_mods]
            combo = "+".join(ordered_mods + [key_name])
            QTimer.singleShot(0, lambda: self._fill_combo(combo))

        return False

    def _fill_combo(self, combo: str) -> None:
        if self._cancel_timer:
            self._cancel_timer.stop()
        self.line_edit.setText(combo)
        self.line_edit.setPlaceholderText("e.g. ctrl+shift+space")
        self._reset_button()
        self._stop_listener()

    def _cancel_recording(self) -> None:
        self._stop_listener()
        self.line_edit.setText(self._original_value)
        self.line_edit.setPlaceholderText("e.g. ctrl+shift+space")
        self._reset_button()

    def _reset_button(self) -> None:
        self.record_btn.setText("⏺ Record")
        self.record_btn.setStyleSheet("")

    def _stop_listener(self) -> None:
        if self._cancel_timer:
            self._cancel_timer.stop()
        if self._listener:
            self._listener.stop()
            self._listener = None
