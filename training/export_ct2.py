"""Merge a LoRA adapter into the base model and convert to CTranslate2 (faster-whisper).

    uv run python export_ct2.py --adapter out/best --output <output-dir>

CTranslate2 does not understand PEFT adapters — merging before conversion is mandatory.
"""

from __future__ import annotations

import argparse
import gc
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from peft import PeftModel
from transformers import WhisperForConditionalGeneration, WhisperProcessor

BASE_MODEL = "openai/whisper-large-v3-turbo"


def main() -> None:
    ap = argparse.ArgumentParser()
    # Without --adapter, exports the bare base model. Use this as a control to separate
    # the effect of training from the effect of the HF → CTranslate2 conversion itself.
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--output", required=True)
    ap.add_argument("--quantization", default="float16")
    args = ap.parse_args()

    out = Path(args.output)
    if out.exists() and any(out.iterdir()):
        sys.exit(f"Directory {out} exists and is not empty — remove it manually or choose a different path.")

    merged = WhisperForConditionalGeneration.from_pretrained(BASE_MODEL)
    if args.adapter:
        print("Merging adapter into base model...")
        merged = PeftModel.from_pretrained(merged, args.adapter).merge_and_unload()
    else:
        print("No adapter — exporting bare base model (control run).")

    with tempfile.TemporaryDirectory() as tmp:
        merged.save_pretrained(tmp)
        processor = WhisperProcessor.from_pretrained(BASE_MODEL)
        processor.save_pretrained(tmp)
        # transformers v5 writes processor_config.json, but ct2-transformers-converter
        # expects the old preprocessor_config.json. Save the feature extractor separately
        # because only it creates the file under that name.
        processor.feature_extractor.save_pretrained(tmp)
        processor.tokenizer.save_pretrained(tmp)

        # The fp32 model (~3.2 GB) is already on disk and no longer needed, but the
        # converter starts its own process and loads it again. Without this, two copies
        # live in memory simultaneously.
        del merged
        gc.collect()

        print("Converting to CTranslate2...")
        subprocess.run(
            [
                "ct2-transformers-converter",
                "--model", tmp,
                "--output_dir", str(out),
                "--quantization", args.quantization,
                "--copy_files", "tokenizer.json", "preprocessor_config.json",
            ],
            check=True,
        )

        # The converter is selective; copy remaining tokenizer files manually.
        for name in ("vocab.json", "merges.txt", "normalizer.json", "special_tokens_map.json",
                     "tokenizer_config.json", "added_tokens.json"):
            src = Path(tmp) / name
            if src.exists() and not (out / name).exists():
                shutil.copy2(src, out / name)

    print(f"\nDone: {out}")
    print("Hook up in src/config.yaml → model_options.local.model_path")


if __name__ == "__main__":
    main()
