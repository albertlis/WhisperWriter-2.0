# Training Data

WhisperWriter can record every transcription session to disk so you can later fine-tune a Whisper model on your own voice, vocabulary, and speech patterns.

## Enabling Recording

In Settings → Training Data (or `src/config.yaml`):

```yaml
training_data:
  save_recordings: true      # off by default
  output_dir: training_data  # relative to repo root
```

When `save_recordings` is `true`, each transcription that is **not processed through an LLM** is saved automatically after typing. LLM-processed output is skipped because it is no longer ground truth for the recorded audio (`src/main.py`, around line 393–403).

## Review Before Paste

Set `training_data.review_before_paste: true` to show an editable dialog after each transcription, before text is typed into the active app.

- **Enter** — accept and type
- **Shift+Enter** — insert a newline in the editor
- **Esc** — cancel (nothing is typed, nothing is saved)

The dialog includes audio playback controls so you can listen to the recording while editing. `review_seek_seconds` (default `5`) controls the seek-button jump size.

When you edit the text in the dialog, the saved record has `edited: true` and the corrected text in `text`, while the raw ASR output remains in `text_asr`. This is the best way to build high-quality training data.

## Dataset Layout

```
training_data/               ← output_dir
    metadata.jsonl
    audio/
        20260806-141233-a1b2c3.flac
        20260806-141401-d4e5f6.flac
        ...
```

Audio is saved as 16-bit FLAC at the sample rate used during recording (default 16 000 Hz).

### metadata.jsonl

One JSON object per line (HuggingFace `audiofolder` format — load directly with `load_dataset("audiofolder", data_dir="training_data")`).

| Field | Type | Description |
|---|---|---|
| `file_name` | str | Relative audio path, e.g. `audio/20260806-141233-a1b2c3.flac` |
| `text` | str | Final text (post-review if edited, otherwise raw ASR) |
| `text_asr` | str | Raw ASR output, before any user edits |
| `duration` | float | Recording duration in seconds (3 decimal places) |
| `model` | str | Model used, e.g. `local:large-v3-turbo` or `api:whisper-1` |
| `edited` | bool | `true` when `text` differs from `text_asr` |
| `ts` | str | ISO 8601 timestamp, second precision |

All fields verified in `src/dataset_recorder.py`.

## Fine-Tuning

The `training/` directory is a separate sub-project with its own virtual environment. **Do not mix it with the main app venv.** The main venv does not have `torch`; `training/` has `torch+cu128` for RTX 5080 (Blackwell sm_120).

Quick-start:

```powershell
cd training
uv sync
uv run python train_lora.py
```

This trains a LoRA adapter on `openai/whisper-large-v3-turbo` using `Seq2SeqTrainer` + PEFT.

Full workflow (baseline → training → export → evaluation) is documented in `training/README.md`. Read it before starting — it contains measured results and a list of already-tested hypotheses to avoid repeating dead ends.

After training, export to CTranslate2:

```powershell
uv run python export_ct2.py --adapter out/best --output D:/path/to/model-ft
```

Then set in `src/config.yaml`:

```yaml
model_options:
  local:
    model_path: D:/path/to/model-ft
```

No code changes needed. The fine-tuned model is a drop-in replacement for any faster-whisper model.
