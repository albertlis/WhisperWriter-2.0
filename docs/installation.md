# Installation

WhisperWriter runs on **Windows** (tested on Windows 11). Python 3.12+ is required. The project uses [uv](https://docs.astral.sh/uv/) for dependency management.

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.12+ | `requires-python = ">=3.12"`; `uv` installs it if missing |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Package and venv manager |
| Git | For cloning |
| NVIDIA GPU (optional) | CUDA 12.x + cuDNN 9 for local GPU transcription |

### CUDA setup (GPU users only)

Install both:
1. [CUDA Toolkit 12.x](https://developer.nvidia.com/cuda-downloads?target_os=Windows) — provides cuBLAS
2. [cuDNN 9 for CUDA 12](https://developer.nvidia.com/cudnn) — full library, Windows x86_64

`run.py` auto-detects the newest CUDA 12.x installation under `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA`. If none is found, it falls back to the cuBLAS/cuDNN bundled inside the `ctranslate2` wheel.

> **Do not install torch in the main venv.** `ctranslate2` imports it when present, adding ~10 s to startup. The `faster-whisper` backend runs on CTranslate2, not PyTorch.

## Install steps

```
git clone <repo-url>
cd ww-llm
uv sync --extra local
```

`--extra local` pulls in `faster-whisper`, `ctranslate2`, and `vosk`. Omit it to use API-only transcription.

After changing dependencies, re-run `uv sync --extra local` manually — `start.bat` does not run `uv sync` automatically once the venv exists.

## Running

**Option A — double-click** `start.bat` (recommended for daily use)

`start.bat` runs `.venv\Scripts\python.exe run.py` directly when the venv exists, skipping the `uv` lock-check overhead (~1 s). On a fresh checkout without a `.venv`, it falls back to `uv run --extra local python run.py` to create and sync the venv first.

**Option B — command line**

```
uv run python run.py
```

The working directory **must** be the repo root. Paths like `src/config.yaml` and `assets/` are resolved relative to the current directory.

`run.py` sets CUDA environment variables, calls `load_dotenv()`, then launches `src/main.py` as a subprocess.

## First run

If `src/config.yaml` does not exist, the Settings window opens automatically. Configure at minimum:

- **Model options** — choose local vs API, set model and device
- **Recording options** — confirm hotkeys
- **LLM post processing** — enable and set API key if desired

Click **Save**. The app moves to the system tray and starts listening for hotkeys.

## API keys

Keys are stored in the Windows Credential Manager (never in YAML files). Enter them in the Settings window; they are saved with `keyring` under the `whisperwriter` namespace.

| Provider | Purpose |
|----------|---------|
| OpenAI | Transcription (`whisper-1`) and/or LLM (`chatgpt`) |
| Deepgram | Transcription (`nova-3`, `nova-2`) |
| Groq | Transcription and/or LLM |
| Anthropic | LLM (`claude`) |
| Google | LLM (`gemini`) |

See [docs/providers.md](providers.md) for per-provider model names and limits.

## Restarting after settings changes

The in-app **Save** button restarts `src/main.py` via `QProcess.startDetached`, which bypasses `run.py`. CUDA paths are therefore not re-applied and GPU transcription may be unavailable after an in-app restart. To avoid this, close the app from the tray and relaunch via `start.bat`.
