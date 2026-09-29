# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```
uv run python run.py
```

Or double-click `start.bat`. CWD **must** be `D:\Tools\ww-llm` (not `src/`) — paths like `src/config.yaml` and `assets/` are relative to project root.

`run.py` discovers CUDA 12.x (newest `v*/bin` under NVIDIA toolkit, venv-bundled fallback), calls `load_dotenv()`, then `subprocess.run([sys.executable, 'src/main.py'])`. CUDA env setup happens in the parent process only — **`restart_app()` in `main.py` uses `QProcess.startDetached` which re-runs `main.py` directly, bypassing `run.py`.** The child inherits the parent's env (incl. `PATH` set by `run.py`), so CUDA should still resolve — not measured.

User-facing docs live in `README.md` and `docs/` — keep them in sync when changing behaviour or config keys.

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

Visual rules and colour tokens: `DESIGN.md` — read before touching any UI.

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

**1. `key_listener.start()` is called from several places** (`main.py` init, `on_transcription_complete` `finally`, restart). Safe only because `PynputBackend.start()` calls `self.stop()` first (`key_listener.py` ~961). Don't remove that stop — it is what prevents leaked listener threads.

**2. Two independent clipboard save/restore implementations.**
- `InputSimulator._paste_with_clipboard_preservation()` — for long transcription output
- `main.handle_text_cleanup()` — for the text-cleanup hotkey (also does delete+paste + manually clears `text_cleanup_chord.pressed_keys`)

Fix one, don't assume it covers the other.

**3. `LLMProcessor.process_text()` instruction-model selection is broken when a file path is set.** Line 72 compares the fully-assembled `system_message` (which `main.py` may have appended file contents to) against the raw config value. Once `instruction_system_message_file_path` is non-empty, equality fails → routes to `cleanup_model` silently. Additionally, `process_text` references `self.is_instruction_mode` (line 63) which is never set in `__init__` → latent `AttributeError` masked only by `main.py`'s early-return guard on empty `system_message`.

## Fine-tuning (`training/`)

Separate subproject with **its own venv** — do not mix with the main one. The main venv **has no torch**
(the app transcribes via `ctranslate2`, and any installed torch gets imported by
`ctranslate2` at startup — measured ~10 s); `training/` carries `torch` cu128
because the RTX 5080 is Blackwell sm_120.

```
cd training && uv sync && uv run python train_lora.py
```

Full run (baseline → training → export → measurement) documented in `training/README.md`.
That file also has the results table — **read it before starting another training run** to avoid
repeating paths already proven dead ends.

| file | role |
|------|------|
| `data.py` | train/validation/test split, deterministic, no time-based cutoff |
| `run_eval.ps1` | export + baseline + model + bootstrap + term hits in one pass |
| `term_hits.py` | proper-noun hit count — the only metric that answers "does it know the terms" |
| `eval_wer.py` | WER via faster-whisper; `--prompt auto`, `--dump` |
| `train_lora.py` | `Seq2SeqTrainer` + PEFT LoRA on `openai/whisper-large-v3-turbo` |
| `export_ct2.py` | merge adapter → CTranslate2; without `--adapter` exports the base model (control) |
| `bootstrap.py` | confidence interval for WER difference between two models |

### Pitfalls (all verified by measurement)

1. **`training_data/` grows during the experiment.** The app appends a recording on every use,
   so dictating while working on training changes `N` and with it the `train_test_split`. The
   same sample can move from the test set to the train set between two measurements. The
   time-based cutoff was removed on request, so **baseline and model must be measured in a
   single pass** (`run_eval.ps1`), without dictating in between. The sample count is printed
   at each measurement — if it differs between the two, the comparison is invalid.
2. **`initial_prompt` with a term list is harmful.** Whisper treats the prompt as stylistic
   context to imitate, not as a vocabulary hint. A comma-separated list teaches it to generate
   clipped phrases without punctuation — measured: WER raw 0.0753 → 0.1354.
3. **WER difference at ~70 test samples is indistinguishable from noise.**
   Always run `bootstrap.py` before claiming an improvement.
4. **WER aggregates too coarsely to answer "does it know proper nouns".** A proper noun weighs
   the same as a conjunction and drowns in the average. For that question, count term hits separately.
5. **`ct2-transformers-converter` requires `preprocessor_config.json`**, but transformers v5
   writes `processor_config.json`. Hence the explicit `feature_extractor.save_pretrained()`
   in `export_ct2.py`.
6. **cuBLAS/cuDNN for faster-whisper in this venv live in `torch/lib`** and must be registered
   via `os.add_dll_directory` before importing `faster_whisper` — the same thing `run.py` does
   for the main app.
7. **`datasets` pinned `<4.0`** — 4.x decodes audio through `torchcodec`, which on Windows
   requires a separate FFmpeg.
8. **Learning rate is decisive.** `lr 1e-3` teaches proper nouns but destroys general competence
   (WER soft ×3.2). `lr 2e-4` yields the same term gain without degradation. Four other
   hypotheses (batch size, collator, gradient checkpointing, data quality) were tested and
   **disproved** — list in `training/README.md`.
9. **VRAM saturation does not give OOM, only silent ×90 slowdown.** The Windows driver spills
   to host RAM. Symptom: `nvidia-smi` shows ~300 MB free at 100% utilization while the step
   grows from 2 s to 180 s. Hence `--grad-checkpointing` is on by default.
10. **The Trainer's `eval_wer` metric (~0.18) and WER from `eval_wer.py` (~0.06) are different
    pipelines.** The former serves only for checkpoint selection. Comparing them leads to a
    false conclusion of catastrophic degradation.
11. **Run training via `Start-Process`** (detached process). Claude Code background tasks are
    killed under low system memory and die with the session.

### Using a trained model

`src/config.yaml` → `model_options.local.model_path` pointing to the export directory.
No code changes needed.

## Dependencies

`uv` + `uv.lock`. `start.bat` runs `.venv\Scripts\python.exe` directly (not `uv run`), so after changing deps run `uv sync --extra local` by hand. The `ctranslate2` wheel bundles cuBLAS/cuDNN (`run.py:check_bundled_cuda`). **Do not install torch in the main venv** — `ctranslate2` imports it when present, adding ~10 s to startup.