# WhisperWriter Configuration Reference

WhisperWriter ships with built-in defaults for every setting. Customise via **tray icon → Settings** (recommended) or by editing `src/config.yaml` directly. The settings window has one tab per schema section: **Model**, **Recording**, **Post-processing**, **LLM**, **Misc**, and **Training data** (where `save_recordings` and `review_before_paste` live). Any key absent from `src/config.yaml` falls back to the schema default.

> **API keys** are stored in **Windows Credential Manager** (app name `whisperwriter`), never in YAML. Add them through the Settings window.

---

## model_options

Top-level toggle:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `use_api` | bool | `false` | When `true`, use a remote transcription API instead of a local model. |

### model_options.common

Applies to both local and API transcription.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `language` | str | `null` | ISO-639-1 language code (e.g. `en`, `pl`). `null` = auto-detect. |
| `temperature` | float | `0.0` | Sampling temperature. Lower = more deterministic. |
| `initial_prompt` | str | `null` | Text prepended as context before transcription. See [OpenAI prompting guide](https://platform.openai.com/docs/guides/speech-to-text/prompting). **Warning:** comma-separated term lists hurt accuracy — see training notes. |

### model_options.api

Active when `use_api: true`. See [Providers](providers.md) for per-provider model lists.

| Key | Type | Default | Options | Description |
|-----|------|---------|---------|-------------|
| `provider` | str | `openai` | `openai`, `deepgram`, `groq` | Transcription API provider. |
| `model` | str | `whisper-1` | See [Providers](providers.md) | Model identifier for the chosen provider. |
| `openai_transcription_api_key` | str | `null` | — | OpenAI key (stored in keyring, not used from YAML). |
| `deepgram_transcription_api_key` | str | `null` | — | Deepgram key (stored in keyring, not used from YAML). |
| `groq_transcription_api_key` | str | `null` | — | Groq key (stored in keyring, not used from YAML). |
| `base_url` | str | `https://api.openai.com/v1` | — | OpenAI-only. Override for self-hosted or proxy endpoints. |

### model_options.local

Active when `use_api: false`. Uses `faster-whisper` (default) or `vosk`.

| Key | Type | Default | Options | Description |
|-----|------|---------|---------|-------------|
| `model` | str | `base` | See [Providers](providers.md) | Model size/variant to load. Larger = slower but more accurate. |
| `device` | str | `auto` | `auto`, `cuda`, `cpu` | `auto` picks CUDA if available. |
| `compute_type` | str | `default` | `default`, `float32`, `float16`, `int8` | Precision for inference. `float16` suits most GPUs. `int8` forces CPU regardless of `device`. |
| `condition_on_previous_text` | bool | `true` | — | Feed previous transcription as context into the next request. |
| `vad_filter` | bool | `false` | — | Strip silence with faster-whisper's built-in VAD before transcribing. |
| `model_path` | str | `null` | — | Absolute path to a CTranslate2 model directory. Overrides `model`. Use for fine-tuned exports — see [training/README.md](../training/README.md). |

---

## recording_options

### Hotkeys

Four independent hotkeys; all default to `null` except `activation_key`.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `activation_key` | str | `ctrl+shift+space` | Start/stop plain transcription. |
| `llm_cleanup_key` | str | `null` | Transcribe, then apply the LLM cleanup prompt. |
| `llm_instruction_key` | str | `null` | Transcribe, then apply the LLM instruction prompt. |
| `text_cleanup_key` | str | `null` | Send clipboard text through LLM cleanup, then delete the selection and paste the result. Copy the selection first. |

Separate modifier keys with `+` (e.g. `ctrl+alt+r`).

### Recording behaviour

| Key | Type | Default | Options | Description |
|-----|------|---------|---------|-------------|
| `input_backend` | str | `auto` | `auto`, `pynput`, `evdev` | Keyboard-capture backend. Windows should stay on `auto` (resolves to `pynput`). |
| `recording_mode` | str | `press_to_toggle` | `press_to_toggle`, `hold_to_record`, `voice_activity_detection`, `continuous` | See table below. |
| `sound_device` | str | `null` | — | Numeric index of microphone. Run `python -m sounddevice` to list devices. |
| `sample_rate` | int | `16000` | — | Recording sample rate in Hz. |
| `silence_duration` | int | `900` | — | Milliseconds of silence before stopping (`voice_activity_detection` mode). |
| `min_duration` | int | `100` | — | Recordings shorter than this (ms) are discarded. |
| `allow_continuous_api` | bool | `false` | — | Allow `continuous` mode with remote APIs. Opt-in required for safety. |
| `continuous_timeout` | int | `10` | — | Seconds of silence before `continuous` mode auto-stops. `0` = never. |

#### Recording modes

| Mode | Behaviour |
|------|-----------|
| `press_to_toggle` | First press starts, second press stops and transcribes. |
| `hold_to_record` | Records while key held; releases trigger transcription. |
| `voice_activity_detection` | Stops automatically after `silence_duration` ms of silence. |
| `continuous` | Restarts recording after each transcription until pressed again (or `continuous_timeout` expires). |

---

## post_processing

| Key | Type | Default | Options | Description |
|-----|------|---------|---------|-------------|
| `writing_key_press_delay` | float | `0.005` | — | Delay (seconds) between simulated keystrokes. Reduce for speed; increase if characters drop. |
| `remove_trailing_period` | bool | `false` | — | Strip the final `.` from transcribed text before typing. |
| `add_trailing_space` | bool | `true` | — | Append a space after typed text (convenient for inline dictation). |
| `remove_capitalization` | bool | `false` | — | Lowercase the entire transcription. |
| `input_method` | str | `pynput` | `pynput`, `ydotool`, `dotool` | Backend for simulating keyboard input. `pynput` is correct for Windows. |
| `clipboard_threshold` | int | `1000` | — | Texts longer than this many characters are pasted via clipboard instead of keystroke simulation. |
| `find_replace_file` | str | `""` | — | Path to a `.txt` find/replace rules file (`find_term,replace_term` per line) or a `.json` regex+capture-group transform file. |

---

## llm_post_processing

LLM post-processing requires `enabled: true` **and** an API key in keyring for the chosen `api_type`.

| Key | Type | Default | Options | Description |
|-----|------|---------|---------|-------------|
| `enabled` | bool | `false` | — | Master switch for LLM post-processing. |
| `api_type` | str | `chatgpt` | `chatgpt`, `claude`, `gemini`, `groq`, `ollama` | LLM provider. `ollama` uses a local Ollama installation. |
| `claude_api_key` | str | `null` | — | Anthropic key (keyring only). |
| `openai_api_key` | str | `null` | — | OpenAI key (keyring only). |
| `gemini_api_key` | str | `null` | — | Google Gemini key (keyring only). |
| `groq_api_key` | str | `null` | — | Groq key (keyring only). |
| `cleanup_model` | str | `gpt-4o-mini` | — | Model used for cleanup hotkey (`llm_cleanup_key`). |
| `instruction_model` | str | `gpt-4o-mini` | — | Model used for instruction hotkey (`llm_instruction_key`). |
| `system_prompt` | str | *(see schema)* | — | System message for cleanup mode. |
| `instruction_system_message` | str | *(see schema)* | — | System message for instruction mode. |
| `temperature` | float | `0.3` | — | LLM sampling temperature. |
| `text_cleanup_system_message` | str | *(see schema)* | — | System message for the text-cleanup hotkey (`text_cleanup_key`). |

---

## misc

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `print_to_terminal` | bool | `true` | Log status and transcriptions to the terminal. |
| `hide_status_window` | bool | `false` | Suppress the floating status pill during recording/transcription. |
| `noise_on_completion` | bool | `false` | Play a sound when typing finishes. |
| `pause_media_during_recording` | bool | `false` | Pause system audio (via pycaw) while recording; resume after. |

---

## training_data

Controls the built-in dataset recorder. Requires separate training setup — see [training/README.md](../training/README.md).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `save_recordings` | bool | `false` | Save each recording (FLAC) and its transcription to the training dataset. |
| `review_before_paste` | bool | `false` | Show an editable review window before typing. **Enter** accepts, **Shift+Enter** adds newline, **Esc** cancels. |
| `review_seek_seconds` | int | `5` | Jump size (seconds) for rewind/forward buttons in the review window. |
| `output_dir` | str | `training_data` | Dataset folder (relative to project root). Contains `audio/` and `metadata.jsonl`. |

---

## API Key Storage

Keys are saved in **Windows Credential Manager** under application `whisperwriter`. Enter them via **Settings** — they are never written to `src/config.yaml`.

| Provider / Purpose | Keyring service name |
|--------------------|----------------------|
| OpenAI transcription | `openai_transcription` |
| OpenAI LLM (ChatGPT) | `openai_llm` |
| Anthropic Claude | `claude` |
| Google Gemini | `gemini` |
| Groq transcription | `groq_transcription` |
| Groq LLM | `groq` |
| Deepgram | `deepgram_transcription` |
