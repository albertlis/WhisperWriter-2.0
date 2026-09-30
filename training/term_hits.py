"""Diagnostic: did fine-tuning improve proper nouns and technical terms."""

import json
import re
import sys
from collections import Counter

TERMS = [
    "claude", "code", "opus", "sonnet", "haiku", "adversary", "simpletask",
    "generalpurpose", "explore", "lintfixer", "testrunner", "apisearch",
    "serena", "cocoindex", "lora", "whisper", "python", "git", "commit",
    "repo", "prompt", "token", "agent", "skill", "hook", "venv", "cuda",
]

base = json.loads(open(sys.argv[1], encoding="utf-8").read())
ft = json.loads(open(sys.argv[2], encoding="utf-8").read())

word = re.compile(r"[\w'-]+", re.UNICODE)


def hits(refs, hyps):
    """How many times a term present in the reference also appeared in the hypothesis."""
    ok, total = Counter(), Counter()
    for r, h in zip(refs, hyps):
        rw = word.findall(r.lower())
        hw = set(word.findall(h.lower()))
        for t in TERMS:
            n = rw.count(t)
            if n:
                total[t] += n
                if t in hw:
                    ok[t] += n
    return ok, total


ob, tb = hits(base["refs"], base["hyps"])
of, tf = hits(ft["refs"], ft["hyps"])

print(f"{'term':<16}{'in ref':>6}{'baseline':>10}{'after FT':>8}")
print("-" * 40)
tb_sum = ob_sum = of_sum = 0
for t in TERMS:
    if tb[t]:
        print(f"{t:<16}{tb[t]:>6}{ob[t]:>10}{of[t]:>8}")
        tb_sum += tb[t]
        ob_sum += ob[t]
        of_sum += of[t]
print("-" * 40)
print(f"{'TOTAL':<16}{tb_sum:>6}{ob_sum:>10}{of_sum:>8}")
if tb_sum:
    print(f"\naccuracy baseline: {ob_sum / tb_sum:.1%}   after FT: {of_sum / tb_sum:.1%}")
