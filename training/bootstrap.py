"""Confidence interval for WER difference between two models (sample-level bootstrap).

    uv run python bootstrap.py base.json ft.json

Answers the question: is the WER difference distinguishable from zero given the test-set
size, or does it fall within sampling noise?
"""

from __future__ import annotations

import argparse
import json
import random

import jiwer

from eval_wer import _SOFT

N_RESAMPLES = 5000


def counts(refs: list[str], hyps: list[str]) -> list[tuple[int, int]]:
    """Per sample: (error count, reference word count). WER must be summed across samples
    as a ratio of sums, not as an average of ratios."""
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
    assert a["refs"] == b["refs"], "different test sets — comparison is meaningless"

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
    print(f"difference (other - base) : {obs:+.4f}")
    print(f"95% CI                    : [{lo:+.4f}, {hi:+.4f}]")
    print(f"P(other not better)       : {p_worse:.3f}")
    print(
        "\nCONCLUSION: "
        + (
            "interval does not include zero — difference is real."
            if hi < 0 or lo > 0
            else "interval includes zero — difference indistinguishable from noise."
        )
    )


if __name__ == "__main__":
    main()
