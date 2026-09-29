"""LoRA fine-tuning openai/whisper-large-v3-turbo na training_data/.

    uv run python train_lora.py

Adapter ląduje w out/best. Do podłączenia pod aplikację potrzebny jeszcze export_ct2.py.
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
# Twardy limit okna dekodera Whispera (`max_target_positions`), nie parametr do strojenia.
# Dłuższy transkrypt wywala forward z ValueError. Ucinanie odpada — uczyłoby model
# kończyć wypowiedź w połowie zdania — więc takie próbki wypadają z treningu.
MAX_LABEL_TOKENS = 448


@dataclass
class DataCollatorSpeechSeq2SeqWithPadding:
    """Standardowy collator z przepisu HF: feature'y i etykiety mają różne długości."""

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
        # <|startoftranscript|> dokleja shift_tokens_right; jeśli tokenizer już go dodał,
        # ucinamy. UWAGA: porównanie musi iść po decoder_start_token_id (50258), NIE po
        # bos_token_id — w Whisperze bos to <|endoftext|> (50257) i stoi na KOŃCU, więc
        # warunek nigdy by nie zadziałał, a model uczyłby się generować token, który
        # przy inferencji jest wymuszany. Cichy train/inference mismatch.
        if (labels[:, 0] == self.decoder_start_token_id).all().cpu().item():
            labels = labels[:, 1:]
        batch["labels"] = labels
        return batch


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--rank", type=int, default=32)
    # lr 2e-4, nie 1e-3: przy 1e-3 model uczy się nazw własnych, ale rozjeżdża ogólną
    # kompetencję (WER soft 0.0455 -> 0.1457). Przy 2e-4 nazwy własne wychodzą tak samo
    # dobrze (100% trafień), a WER rośnie o wielkość nieodróżnialną od szumu.
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument(
        "--workers",
        type=int,
        default=1,
        help="0 = bez osobnego procesu ładującego. Oszczędza ~2 GB RAM (świeży import "
        "torcha na Windows) kosztem utylizacji GPU. Ustaw 0, gdy RAM jest wąskim gardłem.",
    )
    ap.add_argument(
        "--grad-checkpointing",
        action="store_true",
        help="Oszczędza VRAM kosztem ~25%% czasu. Praktycznie konieczne: bez tego "
        "batch 12 wysyca 16 GB karty i sterownik po cichu przechodzi na RAM hosta "
        "(krok rośnie z 2 s do 180 s, bez żadnego błędu).",
    )
    args = ap.parse_args()

    processor = WhisperProcessor.from_pretrained(
        BASE_MODEL, language="polish", task="transcribe"
    )
    splits = load_splits()

    def prepare(batch: dict[str, Any]) -> dict[str, Any]:
        audio = batch["audio"]
        # float32 jawnie: Arrow zapisałby listę float64 i podwoił rozmiar cache'u.
        batch["input_features"] = processor.feature_extractor(
            audio["array"], sampling_rate=audio["sampling_rate"]
        ).input_features[0].astype("float32")
        batch["labels"] = processor.tokenizer(batch["text"]).input_ids
        return batch

    # writer_batch_size: domyślne 1000 trzyma w RAM ~3 GB melu, zanim zrzuci go do Arrow
    # (128 kanałów × 3000 ramek na próbkę). Przy 50 bufor schodzi do ~150 MB.
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
        print(f"[data] odrzucono za długie transkrypty (>{MAX_LABEL_TOKENS} tok.): {dropped}")

    # dtype JAWNIE fp32: transformers domyślnie bierze torch_dtype z configu checkpointu,
    # a large-v3-turbo ma tam float16 — wtedy autocast Trainera podaje fp32 do wag fp16
    # i conv w encoderze wywala się na niezgodności typów. Mieszaną precyzję robi bf16=True.
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
    # gradient_checkpointing + PEFT: wejście encodera musi wymagać gradientu,
    # inaczej backward nie ma się o co zaczepić i loss nie schodzi.
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
            # Bez workerów GPU czeka na collator w tym samym wątku — util skacze 0→50%.
            # Whisper ma stały kształt melu (3000 ramek), więc prefetch jest przewidywalny.
            # 1 worker, nie 2: na Windows każdy to osobny proces ze świeżym importem
            # torcha i własną kopią bufora. Jeden wystarcza, by GPU nie czekało.
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
            remove_unused_columns=False,  # PEFT owija forward; Trainer źle zgaduje kolumny
            label_names=["labels"],
            report_to=[],
        ),
        train_dataset=splits["train"],
        # validation, nie test: na tym zbiorze Trainer wybiera najlepszy checkpoint,
        # więc raportowanie na nim WER byłoby wyciekiem. eval_wer.py mierzy na `test`.
        eval_dataset=splits["validation"],
        data_collator=DataCollatorSpeechSeq2SeqWithPadding(
            processor, model.config.decoder_start_token_id
        ),
        compute_metrics=compute_metrics,
    )

    trainer.train()
    model.save_pretrained(OUT / "best")
    processor.save_pretrained(OUT / "best")
    print(f"\nAdapter zapisany: {OUT / 'best'}")


if __name__ == "__main__":
    main()
