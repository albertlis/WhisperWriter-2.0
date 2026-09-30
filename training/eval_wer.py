"""Measure WER of a faster-whisper model on the test split of training_data/.

    uv run python eval_wer.py --model-dir <path/to/base-ct2>
    uv run python eval_wer.py --model-dir <path/to/base-ct2> --prompt auto

`--prompt auto` builds an initial_prompt from terms extracted ONLY from the training
split — the test split never feeds the prompt, otherwise it would be a data leak.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

import jiwer

# torch cu128 ships cublas64_12.dll and cudnn64_9.dll in its lib directory,
# but Windows does not search there automatically. CTranslate2 (faster-whisper)
# needs them. Must be imported BEFORE faster_whisper.
# Equivalent to what run.py does for the main application.
import torch  # noqa: E402

_TORCH_LIB = Path(torch.__file__).parent / "lib"
if _TORCH_LIB.is_dir():
    os.add_dll_directory(str(_TORCH_LIB))

from faster_whisper import WhisperModel  # noqa: E402

from data import load_splits

# "Soft" normalisation: WER without penalties for punctuation and case.
# Both numbers are reported because human corrections also cover punctuation.
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
    """Words present in the human correction but absent from raw ASR output — terms to hint."""
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
    ap.add_argument("--prompt", default=None, help="'auto' or a literal initial_prompt string")
    ap.add_argument("--dump", default=None, help="write ref/hyp pairs to JSON (for bootstrap)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute-type", default="float16")
    args = ap.parse_args()

    splits = load_splits()
    prompt = build_prompt(splits["train"]) if args.prompt == "auto" else args.prompt
    if prompt:
        print(f"initial_prompt: {prompt}\n")

    # Same parameters as src/transcription.py:187-190 — otherwise the comparison is meaningless.
    model = WhisperModel(args.model_dir, device=args.device, compute_type=args.compute_type)

    refs: list[str] = []
    hyps: list[str] = []
    edited: list[bool] = []
    for i, row in enumerate(splits["test"], 1):
        segments, _ = model.transcribe(
            # datasets returns float64; VAD (ONNX) accepts float32 only
            row["audio"]["array"].astype("float32"),
            language="pl",
            vad_filter=True,
            condition_on_previous_text=True,
            initial_prompt=prompt,
            # 0.0, not the default [0.0..1.0]: production (src/config.yaml) does not use
            # temperature fallback. With fallback, faster-whisper switches to sampling when
            # confidence is low — output becomes non-deterministic and differs from what
            # the user actually sees.
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
    print(f"samples    : {len(refs)}")
    print(f"WER (soft) : {soft:.4f}   # no punctuation or case")
    print(f"WER (raw)  : {raw:.4f}   # verbatim, with punctuation")
    print(f"CER        : {cer:.4f}")

    # Break down by `edited`: for edited=False records the reference IS the base-model
    # output (the recorder copies text_asr to text when the user made no correction).
    # Baseline has zero error there by definition, so the aggregate WER is biased in its
    # favour. The number that actually measures fine-tuning value is the edited=True column.
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
        print(f"saved      : {args.dump}")


if __name__ == "__main__":
    main()
