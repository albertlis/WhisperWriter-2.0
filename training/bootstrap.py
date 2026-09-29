"""Przedział ufności dla różnicy WER między dwoma modelami (bootstrap po próbkach).

    uv run python bootstrap.py base.json ft.json

Pytanie, na które odpowiada: czy różnica WER jest odróżnialna od zera przy 72 próbkach,
czy mieści się w szumie doboru zbioru testowego.
"""

from __future__ import annotations

import argparse
import json
import random

import jiwer

from eval_wer import _SOFT

N_RESAMPLES = 5000


def counts(refs: list[str], hyps: list[str]) -> list[tuple[int, int]]:
    """Na próbkę: (liczba błędów, liczba słów referencji). WER musi się sumować
    po próbkach jako iloraz sum, nie jako średnia z ilorazów."""
    out: list[tuple[int, int]] = []
    for ref, hyp in zip(refs, hyps):
        m = jiwer.process_words(ref, hyp, reference_transform=_SOFT, hypothesis_transform=_SOFT)
        out.append((m.substitutions + m.deletions + m.insertions, m.hits + m.substitutions + m.deletions))
    return out


def wer_of(sample: list[tuple[int, int]]) -> float:
    err = sum(e for e, _ in sample)
    n = sum(n for _, n in sample)
    return err / n if n else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("other")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    a = json.loads(open(args.base, encoding="utf-8").read())
    b = json.loads(open(args.other, encoding="utf-8").read())
    assert a["refs"] == b["refs"], "różne zbiory testowe — porównanie bez sensu"

    ca, cb = counts(a["refs"], a["hyps"]), counts(b["refs"], b["hyps"])
    obs = wer_of(cb) - wer_of(ca)

    rng = random.Random(args.seed)
    idx = range(len(ca))
    diffs = []
    for _ in range(N_RESAMPLES):
        pick = [rng.choice(idx) for _ in idx]
        diffs.append(wer_of([cb[i] for i in pick]) - wer_of([ca[i] for i in pick]))
    diffs.sort()
    lo, hi = diffs[int(0.025 * N_RESAMPLES)], diffs[int(0.975 * N_RESAMPLES)]
    p_worse = sum(1 for d in diffs if d >= 0) / N_RESAMPLES

    print(f"WER {args.base}  : {wer_of(ca):.4f}")
    print(f"WER {args.other} : {wer_of(cb):.4f}")
    print(f"różnica (other - base) : {obs:+.4f}")
    print(f"95% CI                 : [{lo:+.4f}, {hi:+.4f}]")
    print(f"P(other nie lepszy)    : {p_worse:.3f}")
    print(
        "\nWNIOSEK: "
        + (
            "przedział nie obejmuje zera — różnica jest realna."
            if hi < 0 or lo > 0
            else "przedział obejmuje zero — różnica nieodróżnialna od szumu."
        )
    )


if __name__ == "__main__":
    main()
