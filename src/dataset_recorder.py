"""Append recorded audio + corrected transcription to an on-disk training dataset.

Layout (HF `load_dataset("audiofolder", data_dir=...)` compatible):

    <output_dir>/
        metadata.jsonl
        audio/20260806-141233-a1b2c3.flac
"""

import json
import os
import uuid
from datetime import datetime

import numpy as np
import soundfile as sf

from utils import ConfigManager


def _model_name() -> str:
    if ConfigManager.get_config_value("model_options", "use_api"):
        return f"api:{ConfigManager.get_config_value('model_options', 'api', 'model') or 'unknown'}"
    return f"local:{ConfigManager.get_config_value('model_options', 'local', 'model') or 'unknown'}"


def save_sample(
    audio: np.ndarray | None,
    sample_rate: int | None,
    text: str,
    text_asr: str,
) -> str | None:
    """Write one (audio, text) pair to the dataset. Returns the flac path, or None if skipped.

    Never raises — a failing dataset write must not block typing the transcription.
    """
    try:
        if audio is None or len(audio) == 0 or not text.strip():
            return None

        output_dir = (
            ConfigManager.get_config_value("training_data", "output_dir")
            or "training_data"
        )
        audio_dir = os.path.join(output_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)

        sample_rate = sample_rate or 16000
        name = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.flac"
        path = os.path.join(audio_dir, name)
        sf.write(path, audio, sample_rate, format="FLAC")

        record = {
            "file_name": f"audio/{name}",
            "text": text.strip(),
            "text_asr": text_asr.strip(),
            "duration": round(len(audio) / sample_rate, 3),
            "model": _model_name(),
            "edited": text.strip() != text_asr.strip(),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        with open(
            os.path.join(output_dir, "metadata.jsonl"), "a", encoding="utf-8"
        ) as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        ConfigManager.console_print(
            f"Saved training sample: {path} ({record['duration']}s)"
        )
        return path
    except Exception as e:
        ConfigManager.console_print(f"Failed to save training sample: {e}")
        return None
