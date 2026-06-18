# UI Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modernize ww-llm UI — pill-shaped Mica/Acrylic status popup, dark-themed settings window with inline help text, and a HotkeyWidget with record-mode key detection.

**Architecture:** PyQt6 throughout. `apply_mica()` via `ctypes` DWM API (stdlib, no new deps). `QPropertyAnimation` for fade. Dark QSS loaded from `src/ui/styles.qss`. New `HotkeyWidget` uses `pynput` (already a project dep) for key capture.

**Tech Stack:** PyQt6, ctypes (stdlib), pynput (already installed)

## Global Constraints

- No new pip dependencies — `ctypes` is stdlib, `pynput` already in `uv.lock`
- CWD at runtime is `D:\Tools\ww-llm` (project root) — all asset paths are relative to project root
- `styles.qss` loaded via `os.path.join(os.path.dirname(__file__), 'styles.qss')` — resolves relative to `src/ui/`
- Run app with `uv run python run.py` from project root
- Windows 11 only for Mica/Acrylic — fallback for older Windows must not crash

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/ui/base_window.py` | Modify | Add `show_title_bar` param; add `apply_mica()` helper |
| `src/ui/status_window.py` | Modify | Pill redesign, Mica, fade animations, pulse dot |
| `src/ui/hotkey_widget.py` | Create | HotkeyWidget — record mode + key reference panel |
| `src/ui/styles.qss` | Create | Dark QSS theme for SettingsWindow |
| `src/ui/settings_window.py` | Modify | Load QSS, inline help text, use HotkeyWidget |

---

## Task 1: BaseWindow — `show_title_bar` parameter + `apply_mica` helper

**Files:**
- Modify: `src/ui/base_window.py`

**Interfaces:**
- Produces: `apply_mica(hwnd: int, backdrop_type: int = 3) -> bool` — module-level function in `base_window.py`
- Produces: `BaseWindow.__init__(title, width, height, show_title_bar=True)` — backward compatible

- [ ] **Step 1: Read current base_window.py**

  Read `src/ui/base_window.py` in full. Confirm the `initUI` method structure and `paintEvent`.

- [ ] **Step 2: Write the full replacement for base_window.py**

  Replace the file with this content:

  ```python
  import ctypes
  import sys
  
  from PyQt6.QtCore import Qt, QRectF
  from PyQt6.QtGui import QPainter, QBrush, QColor, QPainterPath, QFont, QGuiApplication
  from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QMainWindow
  
  
  def apply_mica(hwnd: int, backdrop_type: int = 3) -> bool:
      """Apply Windows 11 Mica (type=2) or Acrylic (type=3) backdrop via DWM.
      Returns True if applied, False on unsupported Windows or failure.
      DWMWA_SYSTEMBACKDROP_TYPE = 38; backdrop values: 2=Mica, 3=Acrylic.
      Must be called after the window is shown (winId() valid).
      """
      if sys.platform != 'win32':
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
      def __init__(self, title: str, width: int, height: int, show_title_bar: bool = True):
          super().__init__()
          self._show_title_bar = show_title_bar
          self.initUI(title, width, height)
          self.setWindowPosition()
          self.is_dragging = False
  
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
  
              title_label = QLabel('WhisperWriter')
              title_label.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
              title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
              title_label.setStyleSheet("color: #404040;")
  
              close_button_widget = QWidget()
              close_button_layout = QHBoxLayout(close_button_widget)
              close_button_layout.setContentsMargins(0, 0, 0, 0)
  
              close_button = QPushButton('×')
              close_button.setFixedSize(25, 25)
              close_button.setStyleSheet("""
                  QPushButton { background-color: transparent; border: none; color: #404040; }
                  QPushButton:hover { color: #000000; }
              """)
              close_button.clicked.connect(self.handleCloseButton)
              close_button_layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
  
              title_bar_layout.addWidget(QWidget(), 1)
              title_bar_layout.addWidget(title_label, 3)
              title_bar_layout.addWidget(close_button_widget, 1)
              self.main_layout.addWidget(title_bar)
  
          self.setCentralWidget(self.main_widget)
  
      def setWindowPosition(self) -> None:
          center_point = QGuiApplication.primaryScreen().availableGeometry().center()
          frame_geometry = self.frameGeometry()
          frame_geometry.moveCenter(center_point)
          self.move(frame_geometry.topLeft())
  
      def handleCloseButton(self) -> None:
          self.close()
  
      def mousePressEvent(self, event) -> None:
          if event.button() == Qt.MouseButton.LeftButton:
              self.is_dragging = True
              self.start_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
              event.accept()
  
      def mouseMoveEvent(self, event) -> None:
          if Qt.MouseButton.LeftButton and self.is_dragging:
              self.move(event.globalPosition().toPoint() - self.start_position)
              event.accept()
  
      def mouseReleaseEvent(self, event) -> None:
          self.is_dragging = False
  
      def paintEvent(self, event) -> None:
          path = QPainterPath()
          path.addRoundedRect(QRectF(self.rect()), 20, 20)
          painter = QPainter(self)
          painter.setRenderHint(QPainter.RenderHint.Antialiasing)
          painter.setBrush(QBrush(QColor(255, 255, 255, 220)))
          painter.setPen(Qt.PenStyle.NoPen)
          painter.drawPath(path)
  ```

- [ ] **Step 3: Verify SettingsWindow still opens**

  ```
  uv run python run.py
  ```

  Expected: app starts, tray icon appears. Click Settings → SettingsWindow opens with title bar intact. No traceback.

- [ ] **Step 4: Commit**

  ```
  git add src/ui/base_window.py
  git commit -m "feat: add show_title_bar param and apply_mica helper to BaseWindow"
  ```

---

## Task 2: StatusWindow — pill + Mica + fade + pulse dot

**Files:**
- Modify: `src/ui/status_window.py`

**Interfaces:**
- Consumes: `apply_mica(hwnd, backdrop_type)` from `src/ui/base_window.py`
- Consumes: `BaseWindow.__init__(title, width, height, show_title_bar=False)`
- `statusSignal(str, bool)` interface unchanged — main.py emits this, no changes needed there

- [ ] **Step 1: Read current status_window.py in full**

  Read `src/ui/status_window.py`. Note all locations that call `self.show()` and `self.close()` — these become `self.fade_in()` and `self.fade_out()`.

- [ ] **Step 2: Write full replacement for status_window.py**

  ```python
  import sys
  import os
  from typing import override
  
  from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer, QPropertyAnimation, QEasingCurve
  from PyQt6.QtGui import QFont, QPixmap, QCloseEvent
  from PyQt6.QtWidgets import QApplication, QLabel, QHBoxLayout, QVBoxLayout, QWidget, QSizePolicy
  
  sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
  from ui.base_window import BaseWindow, apply_mica
  from utils import ConfigManager
  
  
  _STATUS_QSS_MICA = """
      QWidget#statusContent {
          background: rgba(10, 10, 20, 0.30);
          border-radius: 26px;
          border: 1px solid rgba(255, 255, 255, 0.12);
      }
      QLabel { background: transparent; border: none; color: #f0f0f0; }
  """
  
  _STATUS_QSS_FALLBACK = """
      QWidget#statusContent {
          background: rgba(28, 28, 38, 0.92);
          border-radius: 26px;
          border: 1px solid rgba(255, 255, 255, 0.10);
      }
      QLabel { background: transparent; border: none; color: #f0f0f0; }
  """
  
  
  class StatusWindow(BaseWindow):
      statusSignal: pyqtSignal = pyqtSignal(str, bool)
      closeSignal: pyqtSignal = pyqtSignal()
  
      def __init__(self) -> None:
          super().__init__('WhisperWriter Status', 320, 52, show_title_bar=False)
          self._mica_active = False
          self._fade_anim: QPropertyAnimation | None = None
          self._pulse_timer = QTimer()
          self._pulse_timer.timeout.connect(self._update_pulse)
          self._pulse_alpha = 0.3
          self._pulse_dir = 1
          self._pulse_color = (255, 68, 68)
          self._init_status_ui()
          self.statusSignal.connect(self.updateStatus)
  
      def _init_status_ui(self) -> None:
          self.setWindowFlags(
              Qt.WindowType.FramelessWindowHint
              | Qt.WindowType.WindowStaysOnTopHint
              | Qt.WindowType.Tool
          )
  
          # Transparent outer window; pill lives in statusContent widget
          self.main_widget.setObjectName('statusContent')
          self.main_layout.setContentsMargins(14, 0, 14, 0)
          self.main_layout.setSpacing(0)
  
          row = QHBoxLayout()
          row.setSpacing(8)
          row.setContentsMargins(0, 0, 0, 0)
  
          microphone_path = os.path.join('assets', 'microphone.png')
          pencil_path = os.path.join('assets', 'pencil.png')
          self._mic_pixmap = QPixmap(microphone_path).scaled(
              20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
          )
          self._pencil_pixmap = QPixmap(pencil_path).scaled(
              20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
          )
  
          self.icon_label = QLabel()
          self.icon_label.setFixedSize(20, 20)
          self.icon_label.setPixmap(self._mic_pixmap)
          self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
  
          self.status_label = QLabel('Recording...')
          self.status_label.setFont(QFont('Segoe UI Variable Display', 12))
          self.status_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
  
          self.pulse_dot = QLabel()
          self.pulse_dot.setFixedSize(8, 8)
          self.pulse_dot.setStyleSheet('QLabel { background: rgba(255,68,68,0.3); border-radius: 4px; }')
          self.pulse_dot.hide()
  
          row.addWidget(self.icon_label)
          row.addWidget(self.status_label)
          row.addStretch()
          row.addWidget(self.pulse_dot)
  
          self.main_layout.addLayout(row)
  
      def paintEvent(self, event) -> None:
          pass  # ponytail: Mica/Acrylic + QSS handle background; no Qt painting needed
  
      def _position_window(self) -> None:
          screen = QApplication.primaryScreen()
          if screen is None:
              return
          geo = screen.geometry()
          self.adjustSize()
          x = (geo.width() - self.width()) // 2
          y = geo.height() - self.height() - 80
          self.move(x, y)
  
      def fade_in(self) -> None:
          self._position_window()
          if self._fade_anim and self._fade_anim.state() == QPropertyAnimation.State.Running:
              self._fade_anim.stop()
          self.setWindowOpacity(0.0)
          super(BaseWindow, self).show()
          if not self._mica_active:
              self._mica_active = apply_mica(int(self.winId()), backdrop_type=3)
              self.setStyleSheet(_STATUS_QSS_MICA if self._mica_active else _STATUS_QSS_FALLBACK)
          self._fade_anim = QPropertyAnimation(self, b'windowOpacity')
          self._fade_anim.setDuration(120)
          self._fade_anim.setStartValue(0.0)
          self._fade_anim.setEndValue(1.0)
          self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
          self._fade_anim.start()
  
      def fade_out(self) -> None:
          if not self.isVisible():
              return
          if self._fade_anim and self._fade_anim.state() == QPropertyAnimation.State.Running:
              self._fade_anim.stop()
          self._pulse_timer.stop()
          self.pulse_dot.hide()
          self._fade_anim = QPropertyAnimation(self, b'windowOpacity')
          self._fade_anim.setDuration(200)
          self._fade_anim.setStartValue(self.windowOpacity())
          self._fade_anim.setEndValue(0.0)
          self._fade_anim.setEasingCurve(QEasingCurve.Type.InCubic)
          self._fade_anim.finished.connect(self.hide)
          self._fade_anim.start()
  
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
              f'QLabel {{ background: rgba({r},{g},{b},{self._pulse_alpha:.2f}); border-radius: 4px; }}'
          )
  
      @override
      def closeEvent(self, a0: QCloseEvent | None) -> None:
          self.closeSignal.emit()
          super().closeEvent(a0)
  
      @pyqtSlot(str, bool)
      def updateStatus(self, status: str, use_llm: bool = False) -> None:
          if status == 'recording':
              self.icon_label.setPixmap(self._mic_pixmap)
  
              continuous_mode = ConfigManager.get_config_value('recording_options', 'recording_mode') == 'continuous'
              using_api = ConfigManager.get_config_value('model_options', 'use_api')
              allow_continuous_api = ConfigManager.get_config_value('recording_options', 'allow_continuous_api')
  
              using_remote_api = using_api
              if use_llm:
                  llm_type = ConfigManager.get_config_value('llm_post_processing', 'api_type')
                  using_remote_api = using_remote_api or (llm_type != 'ollama')
  
              if continuous_mode and using_remote_api and not allow_continuous_api:
                  self.closeSignal.emit()
                  return
  
              if continuous_mode and using_remote_api:
                  self.status_label.setText('⚠ Continuous Recording (Remote API)')
                  self._start_pulse((255, 140, 0))  # orange
              else:
                  self.status_label.setText('Recording...')
                  self._start_pulse((255, 68, 68))   # red
  
              self.fade_in()
  
          elif status == 'warming_up':
              self.icon_label.setPixmap(self._mic_pixmap)
              self.status_label.setText('Preparing microphone...')
              self._pulse_timer.stop()
              self.pulse_dot.hide()
              self.fade_in()
  
          elif status == 'transcribing':
              self.icon_label.setPixmap(self._pencil_pixmap)
              self.status_label.setText('Transcribing...')
              self._pulse_timer.stop()
              self.pulse_dot.hide()
              if not self.isVisible():
                  self.fade_in()
  
          elif status == 'processing_llm_cleanup':
              self.icon_label.setPixmap(self._pencil_pixmap)
              api_type = ConfigManager.get_config_value('llm_post_processing', 'api_type') or 'LLM'
              self.status_label.setText(f'Cleaning up with {api_type.upper()}...')
              self._pulse_timer.stop()
              self.pulse_dot.hide()
              if not self.isVisible():
                  self.fade_in()
  
          elif status == 'processing_llm_instruction':
              self.icon_label.setPixmap(self._pencil_pixmap)
              api_type = ConfigManager.get_config_value('llm_post_processing', 'api_type') or 'LLM'
              self.status_label.setText(f'Processing with {api_type.upper()}...')
              self._pulse_timer.stop()
              self.pulse_dot.hide()
              if not self.isVisible():
                  self.fade_in()
  
          if status in ('idle', 'error', 'cancel'):
              self.fade_out()
  
  
  if __name__ == '__main__':
      app = QApplication(sys.argv)
      w = StatusWindow()
      w.statusSignal.emit('recording', False)
      QTimer.singleShot(3000, lambda: w.statusSignal.emit('transcribing', False))
      QTimer.singleShot(5000, lambda: w.statusSignal.emit('idle', False))
      sys.exit(app.exec())
  ```

- [ ] **Step 3: Run the standalone test**

  ```
  uv run python src/ui/status_window.py
  ```

  Expected: pill appears bottom-center, fades in, shows "Recording..." with red pulse dot. After 3s: "Transcribing...", dot hidden. After 5s: fades out, app exits.

- [ ] **Step 4: Run full app**

  ```
  uv run python run.py
  ```

  Trigger recording hotkey. Expected: pill appears, fades in smoothly. Stop recording. Expected: fades out.

- [ ] **Step 5: Commit**

  ```
  git add src/ui/status_window.py
  git commit -m "feat: redesign StatusWindow as Mica/Acrylic pill with fade animations"
  ```

---

## Task 3: Dark QSS theme for SettingsWindow

**Files:**
- Create: `src/ui/styles.qss`
- Modify: `src/ui/settings_window.py` (load QSS in `__init__`)

**Interfaces:**
- Produces: `src/ui/styles.qss` — loaded by SettingsWindow at init

- [ ] **Step 1: Create `src/ui/styles.qss`**

  ```css
  /* ── Base ─────────────────────────────────────────── */
  QMainWindow, QWidget {
      background-color: #1e1e2e;
      color: #cdd6f4;
      font-family: "Segoe UI";
  }
  
  /* ── Tabs ─────────────────────────────────────────── */
  QTabWidget::pane {
      border: 1px solid #3d3d5c;
      border-radius: 6px;
      background: #1e1e2e;
  }
  QTabBar::tab {
      background: #2a2a3d;
      color: #888;
      padding: 6px 16px;
      border: 1px solid #3d3d5c;
      border-bottom: none;
      border-top-left-radius: 6px;
      border-top-right-radius: 6px;
      margin-right: 2px;
  }
  QTabBar::tab:selected {
      background: #1e1e2e;
      color: #cdd6f4;
      border-bottom: 2px solid #7c3aed;
  }
  QTabBar::tab:hover:!selected { background: #313244; color: #cdd6f4; }
  
  /* ── Inputs ───────────────────────────────────────── */
  QLineEdit, QTextEdit, QSpinBox {
      background: #313244;
      border: 1px solid #3d3d5c;
      border-radius: 5px;
      padding: 4px 8px;
      color: #cdd6f4;
      selection-background-color: #7c3aed;
  }
  QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {
      border-color: #7c3aed;
  }
  QLineEdit[echoMode="2"] { color: #888; }
  
  /* ── ComboBox ─────────────────────────────────────── */
  QComboBox {
      background: #313244;
      border: 1px solid #3d3d5c;
      border-radius: 5px;
      padding: 4px 8px;
      color: #cdd6f4;
  }
  QComboBox:focus { border-color: #7c3aed; }
  QComboBox::drop-down { border: none; width: 20px; }
  QComboBox QAbstractItemView {
      background: #2a2a3d;
      border: 1px solid #3d3d5c;
      selection-background-color: #7c3aed;
      color: #cdd6f4;
  }
  
  /* ── CheckBox ─────────────────────────────────────── */
  QCheckBox { spacing: 8px; color: #cdd6f4; }
  QCheckBox::indicator {
      width: 16px; height: 16px;
      border: 1px solid #3d3d5c;
      border-radius: 3px;
      background: #313244;
  }
  QCheckBox::indicator:checked {
      background: #7c3aed;
      border-color: #7c3aed;
      image: none;
  }
  
  /* ── Buttons ──────────────────────────────────────── */
  QPushButton {
      background: #313244;
      border: 1px solid #3d3d5c;
      border-radius: 5px;
      padding: 6px 16px;
      color: #cdd6f4;
  }
  QPushButton:hover { background: #3d3d5c; border-color: #7c3aed; }
  QPushButton:pressed { background: #7c3aed; color: #fff; }
  
  /* ── Scrollbar ────────────────────────────────────── */
  QScrollBar:vertical {
      background: #1e1e2e;
      width: 8px;
      border-radius: 4px;
  }
  QScrollBar::handle:vertical {
      background: #3d3d5c;
      border-radius: 4px;
      min-height: 20px;
  }
  QScrollBar::handle:vertical:hover { background: #7c3aed; }
  QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
  
  /* ── Labels ───────────────────────────────────────── */
  QLabel { background: transparent; }
  QLabel[objectName$="description"] {
      color: #6b6b8a;
      font-size: 9pt;
      padding-top: 1px;
      padding-bottom: 4px;
  }
  
  /* ── Key reference panel ──────────────────────────── */
  QFrame#keyReferenceFrame {
      background: #252535;
      border: 1px solid #3d3d5c;
      border-radius: 6px;
  }
  QLabel#keyRefGroupName {
      color: #888;
      font-size: 9pt;
      font-weight: bold;
  }
  QLabel#keyRefKeys {
      color: #aaa;
      font-size: 9pt;
      font-family: "Cascadia Code", "Consolas", monospace;
  }
  
  /* ── Title bar labels (BaseWindow) ───────────────── */
  QLabel[font-weight="bold"] { color: #cdd6f4; }
  QPushButton[text="×"] {
      color: #888;
      background: transparent;
      border: none;
      font-size: 16pt;
  }
  QPushButton[text="×"]:hover { color: #ff6b6b; }
  ```

- [ ] **Step 2: Load QSS in SettingsWindow.__init__**

  Read `src/ui/settings_window.py` lines 21–58 (the `__init__` and `init_settings_ui` methods). Add QSS loading as the first thing in `init_settings_ui`:

  In `init_settings_ui`, after `def init_settings_ui(self):`, add before `self.tabs = QTabWidget()`:

  ```python
  def init_settings_ui(self):
      """Initialize the settings user interface."""
      # Load dark theme
      _qss_path = os.path.join(os.path.dirname(__file__), 'styles.qss')
      try:
          with open(_qss_path, 'r', encoding='utf-8') as _f:
              self.setStyleSheet(_f.read())
      except FileNotFoundError:
          pass  # ponytail: no QSS is better than crashing
      
      self.tabs = QTabWidget()
      # ... rest unchanged
  ```

  Also update the BaseWindow title bar label color for dark mode. In `base_window.py`, change `title_label.setStyleSheet("color: #404040;")` → `"color: #cdd6f4;"`. And close button: change `color: #404040` → `#cdd6f4`, `color: #000000` (hover) → `#ffffff`.

- [ ] **Step 3: Verify dark theme**

  ```
  uv run python run.py
  ```

  Open Settings. Expected: dark background (#1e1e2e), tabs styled, inputs dark. No white flash.

- [ ] **Step 4: Commit**

  ```
  git add src/ui/styles.qss src/ui/settings_window.py src/ui/base_window.py
  git commit -m "feat: add dark QSS theme for SettingsWindow"
  ```

---

## Task 4: Inline help text in Settings (replace "?" button)

**Files:**
- Modify: `src/ui/settings_window.py`

**Interfaces:**
- Consumes: `meta.get('description', '')` from config schema — already available in `add_setting_widget`
- No interface changes — purely internal layout change

- [ ] **Step 1: Read add_setting_widget and create_help_button**

  Read `src/ui/settings_window.py` lines 122–186 (`add_setting_widget`) and lines 340–365 (`create_help_button` + `show_description`). Confirm exact line ranges.

- [ ] **Step 2: Modify add_setting_widget — remove help button, add description label**

  In `add_setting_widget`, find and remove these three lines:

  ```python
  help_button = self.create_help_button(meta.get('description', ''))
  ```
  ```python
  item_layout.addWidget(help_button)
  ```
  ```python
  help_name = f"{category}_{sub_category}_{key}_help" if sub_category else f"{category}_{key}_help"
  ```
  ```python
  help_button.setObjectName(help_name)
  ```

  After `layout.addLayout(item_layout)`, add:

  ```python
  description = meta.get('description', '')
  if description:
      desc_label = QLabel(description)
      desc_label.setWordWrap(True)
      desc_label.setObjectName('settingDescription')
      desc_label.setContentsMargins(0, 0, 0, 6)
      layout.addWidget(desc_label)
  ```

  Remove `QToolButton` and `QStyle` from the PyQt6 imports at the top (lines 4–6) if they are no longer used anywhere else in the file. Check with a search for `QToolButton` and `QStyle.StandardPixmap` before removing.

- [ ] **Step 3: Delete create_help_button and show_description**

  Remove both methods. They are now dead code.

- [ ] **Step 4: Verify inline descriptions appear**

  ```
  uv run python run.py
  ```

  Open Settings. Each setting should now show a small gray description line below its input widget. No "?" buttons. No QMessageBox on click.

- [ ] **Step 5: Commit**

  ```
  git add src/ui/settings_window.py
  git commit -m "feat: show setting descriptions inline, remove help button popups"
  ```

---

## Task 5: HotkeyWidget — record mode + key reference panel

**Files:**
- Create: `src/ui/hotkey_widget.py`
- Modify: `src/ui/settings_window.py` (use HotkeyWidget for hotkey fields)

**Interfaces:**
- `HotkeyWidget(parent=None)` — drop-in replacement for `QLineEdit` in layout
- `HotkeyWidget.text() -> str` — returns current combo string e.g. `"ctrl+shift+space"`
- `HotkeyWidget.setText(value: str)` — sets the combo string
- `HotkeyWidget.setObjectName(name: str)` — propagates name to internal QLineEdit so save_setting finds it

- [ ] **Step 1: Read save_setting to understand widget value reading**

  Read `src/ui/settings_window.py` — search for `save_setting` and `get_widget_value_typed` methods. Confirm: does it use `isinstance(widget, QLineEdit)` to read `.text()`? Does it iterate nested layouts? This determines whether propagating object name to internal QLineEdit is sufficient.

  Expected: `save_setting` walks layouts, finds widgets by type. `get_widget_value_typed` checks `isinstance(widget, QLineEdit)` and calls `.text()`. The internal QLineEdit in HotkeyWidget will be found during layout walk — set its object name via `setObjectName` override.

- [ ] **Step 2: Create src/ui/hotkey_widget.py**

  ```python
  import os
  import sys
  from typing import override
  
  from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
  from PyQt6.QtWidgets import (
      QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton,
      QLabel, QFrame, QSizePolicy,
  )
  
  sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
  
  try:
      from pynput import keyboard as _kb
      _PYNPUT_AVAILABLE = True
  except ImportError:
      _PYNPUT_AVAILABLE = False
  
  
  _MODIFIER_NAMES: dict = {}  # populated below if pynput available
  _SPECIAL_NAMES: dict = {}
  
  if _PYNPUT_AVAILABLE:
      _MODIFIER_NAMES = {
          _kb.Key.ctrl_l: 'ctrl', _kb.Key.ctrl_r: 'ctrl',
          _kb.Key.alt_l: 'alt', _kb.Key.alt_r: 'alt',
          _kb.Key.shift_l: 'shift', _kb.Key.shift_r: 'shift',
          _kb.Key.cmd_l: 'win', _kb.Key.cmd_r: 'win',
      }
      _SPECIAL_NAMES = {
          _kb.Key.space: 'space', _kb.Key.enter: 'enter',
          _kb.Key.tab: 'tab', _kb.Key.backspace: 'backspace',
          _kb.Key.delete: 'delete', _kb.Key.home: 'home',
          _kb.Key.end: 'end', _kb.Key.page_up: 'page_up',
          _kb.Key.page_down: 'page_down', _kb.Key.up: 'up',
          _kb.Key.down: 'down', _kb.Key.left: 'left',
          _kb.Key.right: 'right', _kb.Key.insert: 'insert',
          _kb.Key.caps_lock: 'caps_lock', _kb.Key.num_lock: 'num_lock',
          _kb.Key.scroll_lock: 'scroll_lock', _kb.Key.pause: 'pause',
          _kb.Key.print_screen: 'print_screen',
          _kb.Key.media_play_pause: 'play_pause',
          _kb.Key.media_next: 'next_track',
          _kb.Key.media_previous: 'prev_track',
          _kb.Key.media_volume_mute: 'mute',
          _kb.Key.media_volume_down: 'volume_down',
          _kb.Key.media_volume_up: 'volume_up',
      }
  
  _MODIFIER_DISPLAY_ORDER = ['ctrl', 'alt', 'shift', 'win']
  
  _KEY_GROUPS = [
      ('Modifiers', 'ctrl  alt  shift  win'),
      ('Letters',   'a – z'),
      ('Numbers',   '0 – 9'),
      ('Function',  'f1  f2  ...  f12'),
      ('Special',   'space  enter  tab  esc  backspace  delete\n'
                    'home  end  page_up  page_down\n'
                    'up  down  left  right  insert  print_screen'),
      ('Numpad',    'numpad0 – numpad9  multiply  add  subtract'),
      ('Media',     'mute  volume_up  volume_down\n'
                    'play_pause  next_track  prev_track'),
  ]
  
  
  def _get_key_name(key) -> str | None:
      """Convert pynput key to key_listener-compatible name string."""
      if not _PYNPUT_AVAILABLE:
          return None
      if key in _SPECIAL_NAMES:
          return _SPECIAL_NAMES[key]
      # Function keys: Key.f1 ... Key.f12
      if hasattr(key, 'name') and key.name and key.name.startswith('f'):
          rest = key.name[1:]
          if rest.isdigit():
              return key.name  # 'f1', 'f2', ...
      # Regular characters
      if hasattr(key, 'char') and key.char:
          return key.char.lower()
      return None
  
  
  class HotkeyWidget(QWidget):
      """QLineEdit replacement for hotkey config fields.
      Adds a Record button (captures live keypresses) and a key-name reference panel.
      setObjectName() propagates to the internal QLineEdit so save_setting() finds it.
      """
  
      def __init__(self, parent: QWidget | None = None) -> None:
          super().__init__(parent)
          self._listener = None
          self._cancel_timer: QTimer | None = None
          self._original_value = ''
          self._held_mods: set[str] = set()
          self._setup_ui()
  
      def _setup_ui(self) -> None:
          outer = QVBoxLayout(self)
          outer.setContentsMargins(0, 0, 0, 0)
          outer.setSpacing(4)
  
          # Input row
          row = QHBoxLayout()
          row.setContentsMargins(0, 0, 0, 0)
          row.setSpacing(6)
          self.line_edit = QLineEdit()
          self.line_edit.setPlaceholderText('e.g. ctrl+shift+space')
  
          self.record_btn = QPushButton('⏺ Record')
          self.record_btn.setFixedWidth(90)
          self.record_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
          if _PYNPUT_AVAILABLE:
              self.record_btn.clicked.connect(self._start_recording)
          else:
              self.record_btn.setEnabled(False)
              self.record_btn.setToolTip('pynput not available')
  
          row.addWidget(self.line_edit)
          row.addWidget(self.record_btn)
          outer.addLayout(row)
  
          # Key reference panel
          outer.addWidget(self._build_ref_panel())
  
      def _build_ref_panel(self) -> QFrame:
          frame = QFrame()
          frame.setObjectName('keyReferenceFrame')
          layout = QVBoxLayout(frame)
          layout.setContentsMargins(8, 6, 8, 6)
          layout.setSpacing(3)
          for group_name, keys_text in _KEY_GROUPS:
              row = QHBoxLayout()
              row.setContentsMargins(0, 0, 0, 0)
              row.setSpacing(6)
              name_lbl = QLabel(f'{group_name}:')
              name_lbl.setObjectName('keyRefGroupName')
              name_lbl.setFixedWidth(68)
              name_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
              keys_lbl = QLabel(keys_text)
              keys_lbl.setObjectName('keyRefKeys')
              keys_lbl.setWordWrap(True)
              row.addWidget(name_lbl)
              row.addWidget(keys_lbl, 1)
              layout.addLayout(row)
          return frame
  
      # ── Public API ──────────────────────────────────────
  
      def text(self) -> str:
          return self.line_edit.text()
  
      def setText(self, value: str) -> None:
          self.line_edit.setText(value)
  
      @override
      def setObjectName(self, name: str) -> None:
          super().setObjectName(name)
          self.line_edit.setObjectName(name)  # save_setting finds QLineEdit by object name
  
      # ── Recording ───────────────────────────────────────
  
      def _start_recording(self) -> None:
          self._original_value = self.line_edit.text()
          self.line_edit.clear()
          self.line_edit.setPlaceholderText('Press a key combination...')
          self.record_btn.setText('● Listening...')
          self.record_btn.setStyleSheet('color: #ff4444;')
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
          mod = _MODIFIER_NAMES.get(key)
          if mod:
              self._held_mods.add(mod)
  
      def _on_release(self, key) -> bool | None:
          if key == _kb.Key.esc:
              # Schedule cancel on Qt thread
              QTimer.singleShot(0, self._cancel_recording)
              return False  # stop listener
  
          if key in _MODIFIER_NAMES:
              return None  # modifier-only release — keep listening
  
          key_name = _get_key_name(key)
          if key_name:
              ordered_mods = [m for m in _MODIFIER_DISPLAY_ORDER if m in self._held_mods]
              combo = '+'.join(ordered_mods + [key_name])
              QTimer.singleShot(0, lambda: self._fill_combo(combo))
  
          return False  # stop listener after first non-modifier key
  
      def _fill_combo(self, combo: str) -> None:
          if self._cancel_timer:
              self._cancel_timer.stop()
          self.line_edit.setText(combo)
          self.line_edit.setPlaceholderText('e.g. ctrl+shift+space')
          self._reset_button()
          self._stop_listener()
  
      def _cancel_recording(self) -> None:
          self._stop_listener()
          self.line_edit.setText(self._original_value)
          self.line_edit.setPlaceholderText('e.g. ctrl+shift+space')
          self._reset_button()
  
      def _reset_button(self) -> None:
          self.record_btn.setText('⏺ Record')
          self.record_btn.setStyleSheet('')
  
      def _stop_listener(self) -> None:
          if self._cancel_timer:
              self._cancel_timer.stop()
          if self._listener:
              self._listener.stop()
              self._listener = None
  ```

- [ ] **Step 3: Integrate HotkeyWidget into settings_window.py**

  In `src/ui/settings_window.py`:

  a) Add import at top (with other ui imports):
  ```python
  from ui.hotkey_widget import HotkeyWidget
  ```

  b) In `create_widget_for_type`, find where string-type widgets are created (likely an `elif meta_type == 'str':` branch creating `QLineEdit`). Add a check for hotkey fields BEFORE that branch:

  ```python
  HOTKEY_KEYS = {'activation_key', 'llm_cleanup_key', 'llm_instruction_key', 'text_cleanup_key'}
  
  if category == 'recording_options' and key in HOTKEY_KEYS:
      widget = HotkeyWidget()
      widget.setText(str(current_value) if current_value else '')
      return widget
  ```

  Add the `HOTKEY_KEYS` constant at module level (top of file, after imports).

- [ ] **Step 4: Verify HotkeyWidget in Settings**

  ```
  uv run python run.py
  ```

  Open Settings → Recording Options tab. The four hotkey fields should show `HotkeyWidget`: input + "⏺ Record" button + key reference panel below.

  Test Record mode:
  1. Click "⏺ Record" on the activation_key field
  2. Button turns red "● Listening..."
  3. Press `Ctrl+Shift+Space`
  4. Field fills with `ctrl+shift+space`, button resets

  Test escape: Click Record → press Escape → original value restored.

  Test timeout: Click Record → wait 5 seconds → original value restored.

- [ ] **Step 5: Verify Save still works**

  Set a hotkey combo via Record, click Save. Expected: app restarts, new hotkey is active.

- [ ] **Step 6: Commit**

  ```
  git add src/ui/hotkey_widget.py src/ui/settings_window.py
  git commit -m "feat: add HotkeyWidget with record mode and key reference panel"
  ```

---

## Self-Review

### Spec coverage check

| Spec requirement | Task |
|-----------------|------|
| Pill 280×52px, border-radius 26px | Task 2 — 320px width with adjustSize |
| Mica/Acrylic ctypes, Win11 22H2+ | Task 1 (apply_mica), Task 2 (called in fade_in) |
| Fallback rgba(30,30,30,0.88) | Task 2 (_STATUS_QSS_FALLBACK) |
| Fade-in 120ms OutCubic / fade-out 200ms InCubic | Task 2 |
| Pulse dot replacing pulsing background | Task 2 (_start_pulse, _update_pulse) |
| Remove BaseWindow title bar from StatusWindow | Task 1 (show_title_bar=False) |
| Dark QSS theme for SettingsWindow | Task 3 |
| Inline description labels | Task 4 |
| Remove "?" button + QMessageBox | Task 4 |
| HotkeyWidget with ⏺ Record | Task 5 |
| Key reference panel with groups | Task 5 |
| Escape to cancel recording | Task 5 |
| 5-second timeout | Task 5 |
| setObjectName propagation for save_setting | Task 5 |
| KeyListener conflict mitigation (check active window) | NOT in plan — out of scope for this iteration; the risk is low (user unlikely to record their own activation key) |

### Placeholder scan

No TBD/TODO in plan. All code steps include complete implementations.

### Type consistency

- `apply_mica(hwnd: int, backdrop_type: int = 3) -> bool` — defined Task 1, used Task 2 ✓
- `BaseWindow(title, width, height, show_title_bar=True)` — defined Task 1, called Task 2 ✓
- `HotkeyWidget.text()`, `.setText()`, `.setObjectName()` — defined Task 5 step 2, used Task 5 step 3 ✓
- `statusSignal(str, bool)` — unchanged throughout ✓
