# WhisperWriter Providers Reference

WhisperWriter supports multiple backends for both **transcription** and **LLM post-processing**. Select providers in **Settings → Model** (transcription) and **Settings → LLM** (post-processing).

---

## Transcription Providers

### Local — faster-whisper

Default backend when `model_options.use_api: false` and the selected `model` is not a Vosk model. Uses [CTranslate2](https://github.com/OpenNMT/CTranslate2) — no internet required after the first download.

#### Available models

| Model | Notes |
|-------|-------|
| `tiny` / `tiny.en` | Fastest, lowest accuracy. `.en` = English-only. |
| `base` / `base.en` | **Default.** Good balance for most use cases. |
| `small` / `small.en` | Better accuracy, moderate speed. |
| `distil-small.en` | Distilled; faster than `small.en` at similar accuracy. |
| `medium` / `medium.en` | High accuracy, slower. |
| `distil-medium.en` | Distilled medium, English-only. |
| `large` | Best accuracy, requires ~10 GB VRAM. |
| `large-v1` / `large-v2` / `large-v3` | Successive large-model generations. |
| `large-v3-turbo` / `turbo` | Faster large-v3 variant. Recommended for GPU users. |
| `distil-large-v2` / `distil-large-v3` | Distilled large models, English-only, faster. |

#### Key settings

| Setting | Purpose |
|---------|---------|
| `device` (`auto`/`cuda`/`cpu`) | `auto` picks CUDA when available. Blackwell (RTX 50xx) requires the `training/` venv for torch; main venv uses ctranslate2 directly. |
| `compute_type` | `float16` suits most NVIDIA GPUs; `default` lets CTranslate2 decide. **`int8` forces `device=cpu`** even if `device: cuda` is set. |
| `condition_on_previous_text` | Feeds prior output as context — improves continuity but can propagate hallucinations. |
| `vad_filter` | Built-in VAD strips leading/trailing silence before decode — useful with `press_to_toggle`. |
| `model_path` | Absolute path to a **CTranslate2 model directory**. Overrides `model`. Use this to load a fine-tuned export from `training/`. See [training/README.md](../training/README.md). |

#### Custom / fine-tuned models

Export a fine-tuned LoRA adapter to CTranslate2 format with `training/export_ct2.py`, then point `model_path` at the output directory. No other code changes required.

---

### Local — Vosk

Select a Vosk model by choosing one of the `vosk-*` entries in the `model` dropdown.

| Model | Notes |
|-------|-------|
| `vosk-model-small-en-us-0.15` | Compact English model (~50 MB). |
| `vosk-model-en-us-0.22` | Larger English model, better accuracy (~1.8 GB). |

Vosk runs fully offline and has lower RAM requirements than Whisper, but accuracy is lower. No GPU required.

---

### API — OpenAI

| Setting | Value |
|---------|-------|
| `provider` | `openai` |
| `model` | `whisper-1` (only option) |
| `base_url` | `https://api.openai.com/v1` (override for proxies) |
| Keyring key | `openai_transcription` |

`base_url` can be pointed at any OpenAI-compatible endpoint (e.g. a local proxy or Azure deployment).

---

### API — Deepgram

| Setting | Value |
|---------|-------|
| `provider` | `deepgram` |
| `model` | `nova-3` (recommended), `nova-2` |
| Keyring key | `deepgram_transcription` |

---

### API — Groq

| Setting | Value |
|---------|-------|
| `provider` | `groq` |
| `model` | `whisper-large-v3-turbo` (recommended), `distil-whisper-large-v3-en`, `whisper-large-v3` |
| Keyring key | `groq_transcription` |

Groq offers very fast transcription via their LPU hardware.

---

## LLM Post-processing Providers

Enable in **Settings → LLM** (`enabled: true`). Two separate models can be configured: `cleanup_model` (used with `llm_cleanup_key`) and `instruction_model` (used with `llm_instruction_key`).

The Settings window includes a **Refresh Models** button that fetches the live model list from the selected provider's API.
### Anthropic Claude

| Setting | Value |
|---------|-------|
| `api_type` | `claude` |
| `cleanup_model` / `instruction_model` | e.g. `claude-3-5-sonnet-latest`, `claude-3-haiku-20240307` |
| Keyring key | `claude` |

Default fallback model (when none configured): `claude-3-5-sonnet-latest`.
---

### OpenAI ChatGPT

| Setting | Value |
|---------|-------|
| `api_type` | `chatgpt` |
| `cleanup_model` / `instruction_model` | e.g. `gpt-4o-mini` (default), `gpt-4o`, `gpt-4-turbo` |
| Keyring key | `openai_llm` |

> Note: the transcription and LLM OpenAI keys are stored separately (`openai_transcription` vs `openai_llm`).

---

### Google Gemini

| Setting | Value |
|---------|-------|
| `api_type` | `gemini` |
| `cleanup_model` / `instruction_model` | e.g. `gemini-1.5-flash` (default), `gemini-1.5-pro` |
| Keyring key | `gemini` |

---

### Groq LLM

| Setting | Value |
|---------|-------|
| `api_type` | `groq` |
| `cleanup_model` / `instruction_model` | e.g. `llama-3.1-8b-instant` (default), `llama-3.3-70b-versatile` |
| Keyring key | `groq` |

> Note: the transcription and LLM Groq keys are stored separately (`groq_transcription` vs `groq`).

---

### Ollama (local LLM)

| Setting | Value |
|---------|-------|
| `api_type` | `ollama` |
| `cleanup_model` | Default: `airat/karen-the-editor-v2-strict` |
| `instruction_model` | Default: `llama3.2` |
| Keyring key | None — no API key required. |

Ollama must be installed separately and running before WhisperWriter starts. The app lists local models via `ollama.list()`. If the configured model is not installed it only prints a warning; the call then fails and the raw text is returned unchanged — `ollama pull <model>` first.

---

## Choosing a Provider

| Scenario | Recommendation |
|----------|---------------|
| Privacy / offline | Local faster-whisper (`turbo` or `large-v3`) |
| Low-end hardware | `base` or `small`; or Vosk for minimal RAM |
| Best cloud accuracy | Groq (`whisper-large-v3`) or Deepgram (`nova-3`) |
| Custom vocabulary / domain | Fine-tune + `model_path` (see [training/README.md](../training/README.md)) |
| LLM cleanup, low latency | Groq LLM (`llama-3.1-8b-instant`) |
| LLM cleanup, high quality | Claude (`claude-3-5-sonnet-latest`) or OpenAI (`gpt-4o`) |
| LLM fully offline | Ollama |
