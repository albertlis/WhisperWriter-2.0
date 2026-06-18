# UI Modernization Design — ww-llm

**Date:** 2026-06-18  
**Scope:** StatusWindow ("dymek") visual redesign + Settings Window UX overhaul  
**Approach:** PyQt6 + Windows 11 Mica/Acrylic (ctypes) + inline help + HotkeyWidget  
**New dependencies:** none (ctypes = stdlib, pynput already installed)

---

## 1. StatusWindow ("dymek") Redesign

### Shape & Size
- Pill shape: default 280×52px, dynamic width for longer text (e.g. warning messages)
- `border-radius`: 26px (= height / 2 → full pill)
- Position: bottom-center, 80px above bottom of primary screen

### Background — Mica/Acrylic
- Win11 22H2+ (build ≥ 22621): call `DwmSetWindowAttribute` via `ctypes` with `DWMWA_SYSTEMBACKDROP_TYPE = 2` (Mica) or `3` (Acrylic blur)
- Requires `WA_TranslucentBackground = True` + `FramelessWindowHint` (already set in BaseWindow)
- Fallback (older Windows): `background: rgba(30, 30, 30, 0.88)` in QSS
- Helper function `apply_mica(hwnd, backdrop_type)` in `base_window.py`

### Content Layout
```
[ icon 20×20 ]  [ status text ]  [ pulse dot ]
```
- Icon: microphone.png / pencil.png scaled to 20×20
- Text: Segoe UI Variable Display, 13pt, color `#ffffff` or `#f0f0f0`
- Pulse dot (recording state only): 8×8px `QLabel` with `border-radius: 4px`, animated via `QTimer` (50ms interval) cycling `background` color opacity in QSS: `rgba(255,68,68,α)` where α oscillates 0.3→1.0→0.3. Warning state (continuous+remote API) uses `rgba(255,165,0,α)` (orange). Replaces the full-window HSL pulsing background.

### Animations
- Show: `QPropertyAnimation(self, b"windowOpacity")`, 0.0→1.0, duration 120ms, easing `OutCubic`
- Hide: 1.0→0.0, duration 200ms, easing `InCubic`, connect `finished` → `QWidget.hide()`
- No more instant `.show()` / `.close()` calls — replaced by `fade_in()` / `fade_out()` methods

### Removed from StatusWindow
- Entire BaseWindow title bar (title label + close button) — StatusWindow overrides `initUI` to skip it
- `shortcuts_label` (already commented out in code)
- `warning_timer` + `updateWarningPulse()` — replaced by pulse dot on the recording icon

### State → Visual Mapping
| Status | Icon | Text | Pulse dot |
|--------|------|------|-----------|
| `warming_up` | mic | "Preparing microphone..." | — |
| `recording` (normal) | mic | "Recording..." | red pulse |
| `recording` (continuous+remote API) | mic | "⚠️ Continuous Recording" | orange pulse |
| `transcribing` | pencil | "Transcribing..." | — |
| `processing_llm_cleanup` | pencil | "Cleaning up with {api}..." where `{api}` = `ConfigManager.get_config_value('llm_post_processing','api_type').upper()` | — |
| `processing_llm_instruction` | pencil | "Processing instruction with {api}..." (same substitution) | — |
| `idle` / `error` / `cancel` | — | — | fade_out() |

---

## 2. Settings Window UX Overhaul

### Inline Help Text
- Every setting widget gets a `QLabel` directly below it with `meta['description']` text
- Style: Segoe UI 9pt, color `#888888`, word wrap enabled, left-aligned
- **Remove**: "?" `QToolButton` (`create_help_button()`) and `show_description()` QMessageBox
- Implementation: in `create_setting_widget()`, after creating the input widget, append a description label to the same `QVBoxLayout` row

### HotkeyWidget (`src/ui/hotkey_widget.py`)
Replaces `QLineEdit` for the four hotkey config fields:
- `recording_options.activation_key`
- `recording_options.llm_cleanup_key`
- `recording_options.llm_instruction_key`
- `recording_options.text_cleanup_key`

**Layout:**
```
[ QLineEdit: "ctrl+shift+space" ] [ ⏺ Record ]

▼ Valid key names
┌─────────────────────────────────────────────────────┐
│ Modifiers:  [ctrl] [alt] [shift] [win]              │
│ Letters:    [a] [b] ... [z]                         │
│ Numbers:    [0] ... [9]                             │
│ Function:   [f1] [f2] ... [f12]                     │
│ Special:    [space] [enter] [tab] [esc] [delete]    │
│             [up] [down] [left] [right] [backspace]  │
│             [home] [end] [page_up] [page_down]      │
│ Numpad:     [numpad0] ... [numpad9]                 │
│ Media:      [mute] [volume_up] [volume_down]        │
│             [play_pause] [next_track] [prev_track]  │
└─────────────────────────────────────────────────────┘
```

Chips are non-interactive styled `QLabel` badges:
```qss
QLabel.chip {
    background: #2d2d3f;
    border: 1px solid #444;
    border-radius: 4px;
    padding: 1px 6px;
    font-family: "Cascadia Code", monospace;
    font-size: 9pt;
    color: #cccccc;
}
```

**⏺ Record mode:**
1. Button click → button text changes to "● Listening..." (red), field clears
2. Widget creates a new `pynput.keyboard.Listener(on_press=..., on_release=...)` and starts it in its own thread
3. Tracks held keys in a set; on release of any non-modifier key → format combo as `ctrl+shift+space` using same key-name conventions as `parse_key_combination()` in `key_listener.py`
4. Fills `QLineEdit`, calls `listener.stop()`, resets button text
5. Timeout: 5 seconds via `QTimer.singleShot(5000, cancel_fn)` → auto-cancel, restore original value
6. Edge case: pressing Escape during recording → cancel without overwriting
7. All four hotkey fields are always shown regardless of recording mode

**Key detection implementation:**
- Use `pynput.keyboard.Listener(on_press=..., on_release=...)` — already a project dependency
- Track currently held keys, on release of any non-modifier → format + fill
- `Key.ctrl_l`/`Key.ctrl_r` both display as `ctrl` (match existing `parse_key_combination` behavior)

### QSS Dark Theme (`src/ui/styles.qss`)
Applied to `SettingsWindow` only (not StatusWindow — it uses Mica).

Color palette:
```
Background:     #1e1e2e   (deep dark)
Surface:        #2a2a3d   (cards/tabs)
Border:         #3d3d5c
Text primary:   #cdd6f4
Text secondary: #888888
Accent:         #7c3aed   (purple) or #0078d4 (Windows blue)
Hover:          #3d3d5c
Input bg:       #313244
```

Widgets styled: `QTabWidget`, `QLineEdit`, `QComboBox`, `QCheckBox`, `QPushButton`, `QScrollArea`, `QSpinBox`, `QTextEdit`.

BaseWindow title bar (for SettingsWindow) gets same dark treatment.

---

## 3. Architecture Changes

### Files Modified
| File | Changes |
|------|---------|
| `src/ui/base_window.py` | Add `apply_mica(hwnd, type)` helper; StatusWindow skips title bar via override |
| `src/ui/status_window.py` | Full pill redesign: new layout, pulse dot, fade animations, Mica call |
| `src/ui/settings_window.py` | Inline description labels, swap hotkey QLineEdits → HotkeyWidget, load styles.qss |

### Files Added
| File | Purpose |
|------|---------|
| `src/ui/hotkey_widget.py` | `HotkeyWidget(QWidget)` — record button + key reference panel |
| `src/ui/styles.qss` | Dark QSS theme for SettingsWindow |

### Files Unchanged
| File | Reason |
|------|--------|
| `src/main.py` | StatusWindow interface unchanged (statusSignal still works) |
| `src/key_listener.py` | No changes — HotkeyWidget uses same pynput already imported |
| `src/ui/model_refresh_worker.py` | No changes |

---

## 4. Constraints & Edge Cases

- **Mica availability**: Check `sys.getwindowsversion().build >= 22621` before calling DWM API. Wrap in `try/except OSError` for safety. StatusWindow always uses Acrylic (`DWMWA_SYSTEMBACKDROP_TYPE = 3`) — gives blur regardless of warning state. Warning state is indicated by pulse dot color (red → orange), not backdrop change.
- **HotkeyWidget listener conflict**: pynput supports multiple concurrent listeners — both HotkeyWidget's temporary listener and KeyListener can coexist. However, pressing the current `activation_key` while in Record mode would trigger recording. Mitigation: KeyListener checks `QApplication.activeWindow()` — if SettingsWindow is focused, skip activation. This check is already sensible behavior independent of this feature.
- **Settings window restart**: QSS loaded via `os.path.join(os.path.dirname(__file__), 'styles.qss')` — resolves relative to `src/ui/`, same pattern as existing `microphone_path = os.path.join('assets', 'microphone.png')` convention in the codebase.
- **BaseWindow title bar**: `BaseWindow.__init__` gains `show_title_bar: bool = True` parameter. StatusWindow passes `show_title_bar=False`. This is backward compatible — SettingsWindow unchanged.

---

## 5. Out of Scope

- Settings window search/filter (add later if needed)
- Light theme (dark only for now, system theme detection → future)
- Animated settings window open/close transition
- Tray icon redesign
