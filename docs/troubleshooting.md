# Troubleshooting

## Startup and Launch

**App must be started from repo root.**
CWD must be the repo root — paths like `src/config.yaml` and `assets/` are resolved relative to it. Always use `start.bat` or `uv run python run.py` from the repo root. Do not `cd src && python main.py`.

**Do not install `torch` in the main venv.**
`ctranslate2` imports `torch` when it is present, adding ~10 s to startup even though the app never uses it directly. If startup is slow, run:

```powershell
uv pip uninstall torch torchvision torchaudio
```

The training sub-project (`training/`) has its own venv with `torch+cu128` — keep them separate.

**After changing dependencies, sync the venv manually.**
`start.bat` runs the venv Python directly and does not call `uv sync`. After editing `pyproject.toml` or `uv.lock`, run:

```powershell
uv sync --extra local
```

## GPU and CUDA

**cuBLAS / cuDNN not found.**
The `ctranslate2` wheel ships and loads its own cuBLAS/cuDNN. If those are missing, `run.py` prepends the newest CUDA 12.x toolkit `bin` (or `site-packages/nvidia/{cuda_runtime,cublas,cudnn}/bin`) to `PATH` and `CUDA_PATH`. Launching `src/main.py` directly skips this — use `start.bat` or `uv run python run.py`.

## Microphone / Recording

**Finding your device index.**
Run:

```powershell
python -m sounddevice
```

This lists all audio devices with their numeric indices. Set `recording_options.sound_device` to the index of your microphone. Leave it `null` to use the system default.

**Recording stops after Bluetooth headset reconnects or RDP session drops.**
The app opens the microphone stream for each recording and closes it afterwards. If recording silently fails, check the terminal for sounddevice errors. Re-selecting the device in Settings and saving may help.

**Hotkeys stop working / two instances conflict.**
WhisperWriter uses a named mutex for single-instance enforcement. If a previous instance did not exit cleanly, the mutex may be stale. Check Task Manager for `python.exe` processes and terminate any stray instances.

## Known Issues (upstream)

**Two separate clipboard save/restore paths.**
`InputSimulator._paste_with_clipboard_preservation()` handles clipboard save/restore for long transcription output. `main.handle_text_cleanup()` has its own independent implementation for the text-cleanup hotkey. If you find clipboard corruption, check both paths — a fix in one does not cover the other.

**LLM instruction-model selection breaks when a file path is set.**
When `instruction_system_message_file_path` is non-empty, `LLMProcessor.process_text()` compares the assembled system message (with file contents appended) against the raw config value. They never match, so the processor silently falls back to `cleanup_model` instead of `instruction_model`.

## Settings Window

**Values showing schema defaults instead of saved values.**
A bug in the Settings window used `or` to fall back to the schema default, which treated `false`, `0`, and `""` as missing. This was fixed in the `fix(mic)` commit. If you see this, make sure you are on the latest version.

**Settings window is slow to open on first use.**
By design — the Settings window is built on first open, not at startup, to reduce startup time. Subsequent opens are faster.

## Training Sub-project

See `training/README.md` for fine-tuning specific issues. Common ones:

- VRAM saturation does not give OOM — it silently switches to host RAM and slows training ×90. Monitor `nvidia-smi`.
- `eval_wer` from the Trainer (~0.18) and `eval_wer.py` (~0.06) measure different pipelines and are not comparable.
- `datasets` is pinned `<4.0` — version 4.x requires a separate FFmpeg install on Windows.
