"""Scala adapter LoRA z bazą i konwertuje do formatu CTranslate2 (faster-whisper).

    uv run python export_ct2.py --adapter out/best --output D:/Tools/whisper-writer/models/turbo-ft

CTranslate2 nie zna adapterów PEFT — scalenie przed konwersją jest obowiązkowe.
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
    # Bez --adapter eksportuje samą bazę. To kontrola: pozwala oddzielić wpływ treningu
    # od wpływu samej konwersji HF → CTranslate2.
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--output", required=True)
    ap.add_argument("--quantization", default="float16")
    args = ap.parse_args()

    out = Path(args.output)
    if out.exists() and any(out.iterdir()):
        sys.exit(f"Katalog {out} istnieje i nie jest pusty — usuń go ręcznie albo wskaż inny.")

    merged = WhisperForConditionalGeneration.from_pretrained(BASE_MODEL)
    if args.adapter:
        print("Scalam adapter z bazą...")
        merged = PeftModel.from_pretrained(merged, args.adapter).merge_and_unload()
    else:
        print("Bez adaptera — eksportuję samą bazę (kontrola).")

    with tempfile.TemporaryDirectory() as tmp:
        merged.save_pretrained(tmp)
        processor = WhisperProcessor.from_pretrained(BASE_MODEL)
        processor.save_pretrained(tmp)
        # transformers v5 zapisuje processor_config.json, a ct2-transformers-converter
        # wymaga starego preprocessor_config.json. Ekstraktor cech zapisujemy osobno,
        # bo tylko on tworzy plik pod tą nazwą.
        processor.feature_extractor.save_pretrained(tmp)
        processor.tokenizer.save_pretrained(tmp)

        # Model fp32 (~3,2 GB) jest już na dysku i niepotrzebny, a konwerter startuje
        # własny proces i wczytuje go drugi raz. Bez tego dwie kopie żyją równolegle.
        del merged
        gc.collect()

        print("Konwertuję do CTranslate2...")
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

        # Konwerter bywa wybiórczy; dobieramy resztę plików tokenizera ręcznie.
        for name in ("vocab.json", "merges.txt", "normalizer.json", "special_tokens_map.json",
                     "tokenizer_config.json", "added_tokens.json"):
            src = Path(tmp) / name
            if src.exists() and not (out / name).exists():
                shutil.copy2(src, out / name)

    print(f"\nGotowe: {out}")
    print("Podepnij w src/config.yaml → model_options.local.model_path")


if __name__ == "__main__":
    main()
