"""Mierzy WER modelu faster-whisper na splicie testowym z training_data/.

    uv run python eval_wer.py --model-dir D:/Tools/whisper-writer/models/turbo
    uv run python eval_wer.py --model-dir D:/Tools/whisper-writer/models/turbo --prompt auto

`--prompt auto` buduje initial_prompt z terminów wyciągniętych WYŁĄCZNIE ze splitu
treningowego — split testowy nigdy nie zasila promptu, inaczej byłby to wyciek.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

import jiwer

# ponytail: torch cu128 przywozi cublas64_12.dll i cudnn64_9.dll w swoim katalogu lib,
# ale Windows ich tam nie szuka. CTranslate2 (faster-whisper) ich potrzebuje.
# Musi być PRZED importem faster_whisper. Odpowiednik tego, co run.py robi dla aplikacji.
import torch  # noqa: E402

_TORCH_LIB = Path(torch.__file__).parent / "lib"
if _TORCH_LIB.is_dir():
    os.add_dll_directory(str(_TORCH_LIB))

from faster_whisper import WhisperModel  # noqa: E402

from data import load_splits

# Normalizacja "miękka": WER bez kar za interpunkcję i wielkość liter.
# Raportujemy obie liczby, bo poprawki użytkownika dotyczą również interpunkcji.
_SOFT = jiwer.Compose(
    [
        jiwer.ToLowerCase(),
        jiwer.RemovePunctuation(),
        jiwer.RemoveMultipleSpaces(),
        jiwer.Strip(),
        jiwer.ReduceToListOfListOfWords(),
    ]
)
_RAW = jiwer.Compose([jiwer.Strip(), jiwer.ReduceToListOfListOfWords()])

_WORD = re.compile(r"[\w'-]+", re.UNICODE)


def build_prompt(train_split, limit: int = 60) -> str:
    """Słowa obecne w poprawce człowieka, a nieobecne w surowym ASR = terminy do podpowiedzi."""
    counter: Counter[str] = Counter()
    for row in train_split:
        if not row.get("edited"):
            continue
        ref = set(_WORD.findall(row["text"].lower()))
        hyp = set(_WORD.findall((row.get("text_asr") or "").lower()))
        counter.update(w for w in ref - hyp if len(w) > 2)
    terms = [w for w, _ in counter.most_common(limit)]
    return ", ".join(terms) + "."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--prompt", default=None, help="'auto' albo dosłowny initial_prompt")
    ap.add_argument("--dump", default=None, help="zapisz pary ref/hyp do JSON (do bootstrapu)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute-type", default="float16")
    args = ap.parse_args()

    splits = load_splits()
    prompt = build_prompt(splits["train"]) if args.prompt == "auto" else args.prompt
    if prompt:
        print(f"initial_prompt: {prompt}\n")

    # Te same parametry co src/transcription.py:187-190 — inaczej porównanie jest bez sensu.
    model = WhisperModel(args.model_dir, device=args.device, compute_type=args.compute_type)

    refs: list[str] = []
    hyps: list[str] = []
    edited: list[bool] = []
    for i, row in enumerate(splits["test"], 1):
        segments, _ = model.transcribe(
            # datasets zwraca float64; VAD (ONNX) przyjmuje wyłącznie float32
            row["audio"]["array"].astype("float32"),
            language="pl",
            vad_filter=True,
            condition_on_previous_text=True,
            initial_prompt=prompt,
            # 0.0, nie domyślne [0.0..1.0]: produkcja (src/config.yaml:40) nie ma
            # fallbacku temperaturowego. Z fallbackiem faster-whisper przy niskiej
            # pewności przechodzi na sampling — wynik przestaje być deterministyczny
            # i różni się od tego, co realnie zobaczy użytkownik.
            temperature=0.0,
        )
        refs.append(row["text"].strip())
        hyps.append("".join(s.text for s in segments).strip())
        edited.append(bool(row.get("edited")))
        print(f"\r{i}/{len(splits['test'])}", end="", flush=True)
    print()

    soft = jiwer.wer(refs, hyps, reference_transform=_SOFT, hypothesis_transform=_SOFT)
    raw = jiwer.wer(refs, hyps, reference_transform=_RAW, hypothesis_transform=_RAW)
    cer = jiwer.cer(refs, hyps)
    print(f"\nmodel      : {args.model_dir}")
    print(f"prompt     : {'auto' if args.prompt == 'auto' else bool(prompt)}")
    print(f"próbek     : {len(refs)}")
    print(f"WER (soft) : {soft:.4f}   # bez interpunkcji i wielkości liter")
    print(f"WER (raw)  : {raw:.4f}   # dosłownie, z interpunkcją")
    print(f"CER        : {cer:.4f}")

    # Rozbicie po `edited`: dla rekordów edited=False referencja JEST outputem modelu
    # bazowego (dataset_recorder kopiuje text_asr do text, gdy user nic nie poprawił).
    # Baseline ma tam zerowy błąd z definicji, więc łączny WER jest przechylony na jego
    # korzyść. Liczbą rozstrzygającą o wartości fine-tuningu jest kolumna edited=True.
    for label, keep in (("edited=True ", True), ("edited=False", False)):
        sub = [(r, h) for r, h, e in zip(refs, hyps, edited) if e is keep]
        if sub:
            sr = [r for r, _ in sub]
            sh = [h for _, h in sub]
            w = jiwer.wer(sr, sh, reference_transform=_SOFT, hypothesis_transform=_SOFT)
            print(f"  {label} : WER soft {w:.4f}  (n={len(sub)})")

    if args.dump:
        Path(args.dump).write_text(
            json.dumps({"refs": refs, "hyps": hyps, "edited": edited}, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"zapisano   : {args.dump}")


if __name__ == "__main__":
    main()
