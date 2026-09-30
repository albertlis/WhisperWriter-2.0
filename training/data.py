"""Shared train/validation/test split. Used by eval_wer.py and train_lora.py."""

from pathlib import Path

from datasets import Audio, DatasetDict, load_dataset

DATA_DIR = Path(__file__).resolve().parent.parent / "training_data"
SAMPLE_RATE = 16000

# No timestamp cutoff — we take everything on disk.
# Consequence: the app appends a recording on every use, so N grows and
# train_test_split shuffles differently. The same sample can move between
# train and test between two runs. Always measure baseline and fine-tuned model
# in a single pass (run_eval.ps1) without recording in between.
# The sample count is printed below — if it differs between two runs the
# comparison is invalid.


def load_splits(
    test_size: float = 0.15, val_size: float = 0.12, seed: int = 0
) -> DatasetDict:
    """Load training_data/ as an HF audiofolder and split deterministically.

    metadata.jsonl already uses the audiofolder layout (file_name + text), so no
    conversion is needed. The `text` column is the human correction; `text_asr`
    (raw model output) travels alongside and is only used for term extraction.

    Three splits, not two. `validation` exists solely so that
    `load_best_model_at_end` has a held-out set for checkpoint selection. Using
    `test` for that would leak: the reported WER would be calculated on data that
    participated in model selection — underestimated, increasingly so with more
    checkpoints. Classic selection leak, not training leak.
    """
    ds = load_dataset("audiofolder", data_dir=str(DATA_DIR), split="train")
    ds = ds.cast_column("audio", Audio(sampling_rate=SAMPLE_RATE))
    # audiofolder also picks up files with no metadata.jsonl entry (text = None) —
    # recordings abandoned before the user confirmed them. Drop these.
    before = len(ds)
    ds = ds.filter(
        lambda r: r["text"] is not None
        and r["text"].strip() != ""
        and r.get("ts") is not None
    )
    print(f"[data] {len(ds)} samples (dropped {before - len(ds)})")
    # Sort before splitting: audiofolder ordering depends on the filesystem.
    # `file_name` disappears — audiofolder turns it into the `audio` column; `ts` is unique.
    ds = ds.sort("ts")
    outer = ds.train_test_split(test_size=test_size, seed=seed)
    inner = outer["train"].train_test_split(test_size=val_size, seed=seed)
    splits = DatasetDict(
        train=inner["train"], validation=inner["test"], test=outer["test"]
    )
    print(
        f"[data] train {len(splits['train'])} / val {len(splits['validation'])} "
        f"/ test {len(splits['test'])}"
    )
    return splits
