<div align="center">

<img src="./assets/ww-logo.png" alt="WhisperWriter logo" width="96">

# WhisperWriter

**Press a hotkey, speak, and the text is typed wherever your cursor is.**
Local Whisper or cloud APIs, optional LLM cleanup, and a built-in loop for fine-tuning on your own voice.

![platform](https://img.shields.io/badge/platform-Windows-0078D6)
![python](https://img.shields.io/badge/python-3.12-3776AB)
![license](https://img.shields.io/badge/license-GPL--3.0-green)

<img src="./assets/ww-demo-image-02.gif" alt="WhisperWriter demo" width="720">

</div>

---

## Features

**New in this fork**

- **Redesigned UI.** A compact status pill with a live mic level meter and timer, plus a reworked, tabbed settings window.
- **Ready in about 6 s.** Startup used to take about 29 s. The speedup comes from lazy imports, a lazily built settings window, and no torch in the app venv.
- **Review before paste.** An editable dialog shows the transcript before it is typed. You can listen to the recording with play, seek and a slider. `Enter` accepts, `Esc` cancels.
- **Training data capture.** Each dictation can be saved as FLAC plus `metadata.jsonl` (HF `audiofolder` format), along with any correction you made.
- **Fine-tuning subproject.** Trains a LoRA for `whisper-large-v3-turbo` on your recordings and exports it to CTranslate2. See [`training/`](training/README.md).

**Core**

- Four hotkeys: plain dictation, LLM cleanup, LLM instruction, and in-place cleanup of copied text.
- Four recording modes: press-to-toggle, hold-to-record, voice activity detection, continuous.
- Transcription runs locally with `faster-whisper` (CUDA or CPU) or `vosk`, or through the OpenAI, Deepgram or Groq APIs.
- LLM post-processing supports Claude, ChatGPT, Gemini, Groq and Ollama.
- Find-and-replace rules from plain `.txt` lists or regex `.json` files.
- API keys are stored in Windows Credential Manager, never in config files.

## Quick start

```powershell
git clone https://github.com/albertlis/open-writer-2.0.git
cd open-writer-2.0
uv sync --extra local
.\start.bat            # or: uv run python run.py
```

The first launch opens **Settings**. Pick a model, set a hotkey (default `Ctrl+Shift+Space`) and save. After that the app lives in the system tray. Details: [installation](docs/installation.md).

## Documentation

| Guide | What's inside |
|-------|---------------|
| [Installation](docs/installation.md) | Prerequisites, `uv`, CUDA discovery, `start.bat` |
| [Usage](docs/usage.md) | Hotkeys, recording modes, status pill, review dialog, tray |
| [Configuration](docs/configuration.md) | Every option in `config_schema.yaml`, keyring entries |
| [Providers](docs/providers.md) | Local and API transcription, LLM providers and models |
| [Post-processing](docs/post-processing.md) | Find & replace, LLM modes, text output methods |
| [Training data](docs/training-data.md) | Dataset format, review workflow, using a fine-tuned model |
| [Troubleshooting](docs/troubleshooting.md) | Known issues and fixes |
| [Changelog](CHANGELOG.md) | What changed and when |

## Credits

This is a fork of a fork:

- **[savbell/whisper-writer](https://github.com/savbell/whisper-writer)** is the original WhisperWriter by [savbell](https://github.com/savbell) and [contributors](https://github.com/savbell/whisper-writer/graphs/contributors).
- **[Thomas Frank](https://github.com/TomFrankly)** made the Windows-focused fork this one builds on, adding LLM post-processing and more.
- [OpenAI](https://openai.com/) created Whisper, and [SYSTRAN / Guillaume Klein](https://github.com/SYSTRAN/faster-whisper) created `faster-whisper`.

## License

GNU General Public License. See [LICENSE](LICENSE).
