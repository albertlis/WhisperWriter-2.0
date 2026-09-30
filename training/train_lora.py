"""LoRA fine-tuning openai/whisper-large-v3-turbo on training_data/.

    uv run python train_lora.py

Adapter is saved to out/best. Run export_ct2.py afterwards to convert to faster-whisper.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import evaluate
import torch
from peft import LoraConfig, get_peft_model
from transformers import (
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
    WhisperForConditionalGeneration,
    WhisperProcessor,
)

from data import load_splits

BASE_MODEL = "openai/whisper-large-v3-turbo"
OUT = Path(__file__).resolve().parent / "out"
# Hard limit of the Whisper decoder window (`max_target_positions`), not a tunable.
# A longer transcript causes forward() to raise ValueError. Truncation is not an option —
# it would teach the model to end utterances mid-sentence — so such samples are dropped.
MAX_LABEL_TOKENS = 448


@dataclass
class DataCollatorSpeechSeq2SeqWithPadding:
    """Standard HF recipe collator: input features and labels have different lengths."""

    processor: Any
    decoder_start_token_id: int

    def __call__(self, features: list[dict[str, Any]]) -> dict[str, torch.Tensor]:
        batch = self.processor.feature_extractor.pad(
            [{"input_features": f["input_features"]} for f in features],
            return_tensors="pt",
        )
        labels_batch = self.processor.tokenizer.pad(
            [{"input_ids": f["labels"]} for f in features], return_tensors="pt"
        )
        labels = labels_batch["input_ids"].masked_fill(
            labels_batch.attention_mask.ne(1), -100
        )
        # shift_tokens_right prepends <|startoftranscript|>; strip it if the tokenizer
        # already added it. IMPORTANT: compare against decoder_start_token_id (50258),
        # NOT bos_token_id — in Whisper bos is <|endoftext|> (50257) and sits at the END,
        # so the condition would never fire and the model would learn to generate a token
        # that is forced at inference time. Silent train/inference mismatch.
        if (labels[:, 0] == self.decoder_start_token_id).all().cpu().item():
            labels = labels[:, 1:]
        batch["labels"] = labels
        return batch


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--rank", type=int, default=32)
    # lr 2e-4, not 1e-3: high lr learns proper nouns but degrades general competence.
    # At 2e-4 proper nouns improve equally well while WER change is indistinguishable
    # from noise. See Lessons learned in README.md.
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument(
        "--workers",
        type=int,
        default=1,
        help="0 = no separate data-loading process. Saves ~2 GB RAM (fresh torch import "
        "per worker on Windows) at the cost of GPU utilisation. Set 0 when RAM is the "
        "bottleneck.",
    )
    ap.add_argument(
        "--grad-checkpointing",
        action="store_true",
        help="Saves VRAM at the cost of ~25%% extra time. Strongly recommended: without it "
        "a batch of 12 saturates 16 GB of VRAM and the Windows driver silently spills to "
        "host RAM (step time grows from 2 s to 180 s with no error).",
    )
    args = ap.parse_args()

    processor = WhisperProcessor.from_pretrained(
        BASE_MODEL, language="polish", task="transcribe"
    )
    splits = load_splits()

    def prepare(batch: dict[str, Any]) -> dict[str, Any]:
        audio = batch["audio"]
        # Explicit float32: Arrow would store a list of float64 and double the cache size.
        batch["input_features"] = processor.feature_extractor(
            audio["array"], sampling_rate=audio["sampling_rate"]
        ).input_features[0].astype("float32")
        batch["labels"] = processor.tokenizer(batch["text"]).input_ids
        return batch

    # writer_batch_size: the default 1000 keeps ~3 GB of mel in RAM before flushing to
    # Arrow (128 channels × 3000 frames per sample). At 50 the buffer drops to ~150 MB.
    splits = splits.map(
        prepare,
        remove_columns=splits["train"].column_names,
        num_proc=1,
        writer_batch_size=50,
    )

    before = {k: len(v) for k, v in splits.items()}
    splits = splits.filter(lambda r: len(r["labels"]) <= MAX_LABEL_TOKENS)
    dropped = {k: before[k] - len(v) for k, v in splits.items() if before[k] != len(v)}
    if dropped:
        print(f"[data] dropped samples with transcripts longer than {MAX_LABEL_TOKENS} tokens: {dropped}")

    # Explicit fp32: transformers picks torch_dtype from the checkpoint config by default,
    # and large-v3-turbo has float16 there — autocast then passes fp32 to fp16 weights
    # and the encoder conv fails on a type mismatch. Mixed precision is handled by bf16=True.
    model = WhisperForConditionalGeneration.from_pretrained(
        BASE_MODEL, dtype=torch.float32, attn_implementation="sdpa"
    )
    model.config.forced_decoder_ids = None
    model.config.suppress_tokens = []
    model.generation_config.language = "polish"
    model.generation_config.task = "transcribe"
    model.generation_config.forced_decoder_ids = None

    model = get_peft_model(
        model,
        LoraConfig(
            r=args.rank,
            lora_alpha=args.rank * 2,
            target_modules=["q_proj", "v_proj"],
            lora_dropout=0.05,
            bias="none",
        ),
    )
    model.print_trainable_parameters()
    # gradient_checkpointing + PEFT: encoder input must require grad,
    # otherwise backward has nothing to hook into and loss does not decrease.
    model.enable_input_require_grads()

    metric = evaluate.load("wer")

    def compute_metrics(pred: Any) -> dict[str, float]:
        label_ids = pred.label_ids.copy()
        label_ids[label_ids == -100] = processor.tokenizer.pad_token_id
        refs = processor.batch_decode(label_ids, skip_special_tokens=True)
        hyps = processor.batch_decode(pred.predictions, skip_special_tokens=True)
        return {"wer": metric.compute(predictions=hyps, references=refs)}

    trainer = Seq2SeqTrainer(
        model=model,
        args=Seq2SeqTrainingArguments(
            output_dir=str(OUT),
            per_device_train_batch_size=args.batch_size,
            per_device_eval_batch_size=args.batch_size,
            gradient_accumulation_steps=1,
            # Without workers the GPU waits for the collator on the same thread — util
            # spikes 0→50%. Whisper has a fixed mel shape (3000 frames) so prefetch is
            # predictable. 1 worker, not 2: on Windows each worker is a fresh process
            # with its own torch import and buffer copy. One is enough to keep GPU busy.
            dataloader_num_workers=args.workers,
            dataloader_persistent_workers=args.workers > 0,
            dataloader_pin_memory=True,
            learning_rate=args.lr,
            warmup_steps=50,
            num_train_epochs=args.epochs,
            bf16=True,
            gradient_checkpointing=args.grad_checkpointing,
            eval_strategy="steps",
            eval_steps=50,
            save_strategy="steps",
            save_steps=50,
            save_total_limit=2,
            logging_steps=10,
            predict_with_generate=True,
            generation_max_length=225,
            load_best_model_at_end=True,
            metric_for_best_model="wer",
            greater_is_better=False,
            remove_unused_columns=False,  # PEFT wraps forward; Trainer mis-infers columns
            label_names=["labels"],
            report_to=[],
        ),
        train_dataset=splits["train"],
        # validation, not test: Trainer uses this split to pick the best checkpoint,
        # so reporting WER on it would be data leakage. eval_wer.py evaluates on `test`.
        eval_dataset=splits["validation"],
        data_collator=DataCollatorSpeechSeq2SeqWithPadding(
            processor, model.config.decoder_start_token_id
        ),
        compute_metrics=compute_metrics,
    )

    trainer.train()
    model.save_pretrained(OUT / "best")
    processor.save_pretrained(OUT / "best")
    print(f"\nAdapter saved: {OUT / 'best'}")


if __name__ == "__main__":
    main()
