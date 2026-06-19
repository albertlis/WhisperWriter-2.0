# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```
uv run python run.py
```

Or double-click `start.bat`. CWD **must** be `D:\Tools\ww-llm` (not `src/`) — paths like `src/config.yaml` and `assets/` are relative to project root.

`run.py` discovers CUDA 12.x (newest `v*/bin` under NVIDIA toolkit, venv-bundled fallback), calls `load_dotenv()`, then `subprocess.run([sys.executable, 'src/main.py'])`. CUDA env setup happens in the parent process only — **`restart_app()` in `main.py` uses `QProcess.startDetached` which re-runs `main.py` directly, bypassing `run.py`, so GPU may be unavailable after an in-app settings restart.**

## Architecture

### Corrected data flow

```
hotkey chord fires
  → on_activation*(sets app.use_llm / app.is_instruction_mode)
  → start_result_thread()
      → ResultThread(use_llm)   # use_llm here is display-only (statusSignal color)
          records mic → VAD → transcribe() → resultSignal(text)
  → on_transcription_complete(text)   # in main.py, not llm_processor
      assembles system_message from config value + optional file append
      if use_llm and llm_processor: LLMProcessor.process_text(text, system_message)
      InputSimulator.typewrite(result)
```

`ResultThread` only records and transcribes. All LLM gating, system-message assembly, and file-append logic live in `on_transcription_complete()` (`main.py`).

### Core modules (`src/`)

| File | Role |
|------|------|
| `main.py` | `WhisperWriterApp(QObject)` — orchestrator, system tray, `on_transcription_complete`, `handle_text_cleanup` |
| `key_listener.py` | `KeyListener` + `KeyChord` — `PynputBackend` (Windows default) / `EvdevBackend` (Linux). `KeyChord.update()` handles debouncing and hold-vs-press semantics. |
| `result_thread.py` | `ResultThread(QThread)` — mic via `sounddevice`, VAD via `webrtcvad` (aggressiveness=2, 30ms frames, 0.15s initial skip hardcoded), emits `resultSignal` |
| `transcription.py` | `transcribe()` — local (`faster-whisper`/`vosk`) or API (`openai`/`deepgram`/`groq`), then `post_process_transcription()` |
| `llm_processor.py` | `LLMProcessor` — `claude`/`chatgpt`/`gemini`/`groq`/`ollama`. See Gotchas §3. |
| `utils.py` | `ConfigManager` singleton — schema defaults from `src/config_schema.yaml`, deep-merged with user `src/config.yaml`. `initialize()` must be called once; `get_config_value('section', 'key')`. |
| `input_simulation.py` | `InputSimulator` — `pynput` typewrite for short text, Win32 clipboard paste above `clipboard_threshold` (default 1000 chars) with clipboard save/restore |
| `keyring_manager.py` | `KeyringManager` — Windows Credential Manager, app namespace `whisperwriter` |
| `text_processor.py` | `TextProcessor` — `.txt` simple `find,replace` or `.json` regex + capture group transforms |
| `media_controller.py` | `MediaController` — pause/resume audio via `pycaw` |

### UI (`src/ui/`)

`SettingsWindow`, `StatusWindow`, `ModelRefreshWorker` (QThread for async model list fetching).

**`MainWindow` is vestigial — never instantiated at runtime.** The app goes directly from config-load to `key_listener.start()` (with tray icon); the old Start-button window was bypassed intentionally.

Auto-API-mode fallback: `SettingsWindow.__init__` probes for `faster_whisper`/`vosk` at import; if neither available, forces API mode regardless of config.

### Configuration

- `src/config_schema.yaml` — schema + defaults (`value`/`type`/`description`/`options` per key)
- `src/config.yaml` — user overrides, deep-merged at startup. Missing → `SettingsWindow` shown on first run (`ConfigManager.config_file_exists()` gate).
- API keys — Windows Credential Manager only, never in YAML.

#### Keyring service names (`KeyringManager.APP_NAME = "whisperwriter"`)

| Provider | Keyring service key |
|----------|-------------------|
| OpenAI transcription | `openai_transcription` |
| OpenAI LLM | `openai_llm` |
| Anthropic Claude | `claude` |
| Google Gemini | `gemini` |
| Groq transcription | `groq_transcription` |
| Groq LLM | `groq` |
| Deepgram | `deepgram_transcription` |

Note: `openai_llm` ≠ `openai_transcription` and `groq` ≠ `groq_transcription` — separate keyring entries.

### Hotkey modes

Four independent hotkeys (`recording_options`):
- `activation_key` — plain transcription
- `llm_cleanup_key` — transcription + LLM cleanup prompt
- `llm_instruction_key` — transcription + LLM instruction prompt
- `text_cleanup_key` — clipboard text → LLM → replace selection in place

`on_deactivation()` only stops recording in `hold_to_record` mode; for `press_to_toggle`/`continuous` the key-release is a no-op — toggling happens on the next `on_activation`.

Recording modes: `press_to_toggle` (default), `hold_to_record`, `voice_activity_detection`, `continuous`.

`continuous` self-terminates inside `_record_audio` (`result_thread.py`) by setting `self.is_running = False` on silence timeout — not via the `on_transcription_complete` re-arm loop. Stop logic spans both files.

## Gotchas

**1. Double `key_listener.start()` — listener leak.** `on_transcription_complete` calls `key_listener.start()` at line 277, then the `finally` block calls it again at line 282 unconditionally. `PynputBackend.start()` creates fresh listener threads each call without stopping prior ones → one leaked listener thread per transcription. Known bug.

**2. Two independent clipboard save/restore implementations.**
- `InputSimulator._paste_with_clipboard_preservation()` — for long transcription output
- `main.handle_text_cleanup()` — for the text-cleanup hotkey (also does delete+paste + manually clears `text_cleanup_chord.pressed_keys`)

Fix one, don't assume it covers the other.

**3. `LLMProcessor.process_text()` instruction-model selection is broken when a file path is set.** Line 75 compares the fully-assembled `system_message` (which `main.py` may have appended file contents to) against the raw config value. Once `instruction_system_message_file_path` is non-empty, equality fails → routes to `cleanup_model` silently. Additionally, `process_text` references `self.is_instruction_mode` (line 66) which is never set in `__init__` → latent `AttributeError` masked only by `main.py`'s early-return guard on empty `system_message`.

## Dependencies

`uv` + `uv.lock`. GPU transcription requires CUDA 12.x + cuDNN 9 separately. CUDA-compatible torch (after `pip install .`):
```
pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
```
