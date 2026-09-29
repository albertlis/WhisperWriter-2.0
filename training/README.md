# Fine-tuning Whispera na własnym głosie

Osobne środowisko — **nie** miesza się z venv aplikacji (ten ma `torch+cpu`).
Wszystkie komendy z katalogu `training/`.

## 0. Środowisko i GPU (blokujące)

```
uv sync
uv run python -c "import torch;print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_capability(0))"
```

Oczekiwane: `True (12, 0)` na RTX 5080. Jeśli `False` — dalej nie ma sensu.

## 1. Baseline — zmierz, zanim wytrenujesz

```
uv run python eval_wer.py --model-dir D:/Tools/whisper-writer/models/turbo
uv run python eval_wer.py --model-dir D:/Tools/whisper-writer/models/turbo --prompt auto
```

Drugi przebieg to kontrola: jeśli sam `initial_prompt` z Twoimi terminami zbija WER
prawie tak samo jak trening, trening jest zbędny. Zapisz obie liczby.

## 2. Trening

```
uv run python train_lora.py
```

~56 kroków na epokę (450 próbek, batch efektywny 8). Eval co 50 kroków,
`load_best_model_at_end`. Jeśli eval WER rośnie od pierwszej ewaluacji — przeuczenie,
zejdź niżej: `--epochs 1` albo `--rank 8`. OOM → `--batch-size 2`.

## 3. Eksport do faster-whisper

```
uv run python export_ct2.py --adapter out/best --output D:/Tools/whisper-writer/models/turbo-ft
```

## 4. Porównanie i podpięcie

```
uv run python eval_wer.py --model-dir D:/Tools/whisper-writer/models/turbo-ft
```

Niższy WER niż baseline **i** niższy niż wariant z promptem → w `src/config.yaml`
ustaw `model_options.local.model_path` na `D:/Tools/whisper-writer/models/turbo-ft`.
Zmian w kodzie aplikacji nie ma.

## Wyniki z 2026-09-25 (628 próbek / 143 min, split 95 testowych)

Bez `CUTOFF_TS` — cały zbiór. Trzy splity: train / validation / test.
Baseline i model mierzone w jednym przebiegu (`run_eval.ps1`), bo bez odcięcia
każde nowe nagranie zmienia podział.

| wariant | WER soft | WER raw | CER | trafność terminów |
|---|---|---|---|---|
| baseline `models/turbo` | **0.0455** | **0.0670** | **0.0252** | 54.5% |
| **LoRA r=32, lr 2e-4, 3 ep., batch 4** | 0.0590 | 0.0965 | 0.0373 | **100.0%** |
| LoRA r=32, lr 1e-3, 3 ep., batch 4 | 0.1457 | 0.1999 | 0.0935 | 95.5% |

Bootstrap (baseline vs lr 2e-4): różnica **+0.0135**, 95% CI `[-0.0111, +0.0427]`,
P(FT nie lepszy) = 0.814 → **przedział obejmuje zero, różnica nieistotna**.

Trafność terminów, wariant lr 2e-4: `claude` **0/10 → 10/10**, `haiku` 1/4 → 4/4,
`opus` 5/6 → 6/6, `sonnet` 5/6 → 6/6. **RAZEM 18/33 → 33/33.**

**Wniosek: wariant lr 2e-4 nadaje się do użycia**, jeśli przyjąć kryterium
użytkownika (słowa i nazwy własne ponad interpunkcję). Rozwiązuje problem nazw
własnych całkowicie, pogarszając WER o wielkość nieodróżnialną od szumu.
Interpunkcja (`raw` +44%) jest realnym kosztem.

### Obalone hipotezy (nie powtarzaj tych eksperymentów)

| hipoteza | test | wynik |
|---|---|---|
| za dużo kroków przez mały batch | batch 12 vs 4, lr 1e-3 | obalona — batch 12 GORSZY (val WER 0.2066 vs 0.1599) |
| przycinanie `<\|startoftranscript\|>` szkodzi | trim vs no-trim, identyczna reszta | obalona — bez trim 0.2227, z trim 0.2066 |
| gradient checkpointing gubi gradienty przy PEFT | — | odrzucona: loss jest zdrowy (najniższy ze wszystkich przebiegów) |
| złe dane po zdjęciu `CUTOFF_TS` | audyt 628 próbek | obalona — 0 duplikatów, 0 braków, 0 halucynacji |
| **learning rate za wysoki** | lr 2e-4 vs 1e-3 | **potwierdzona** |

### Pułapka pomiarowa, która kosztowała cztery przebiegi

`eval_wer` z `Seq2SeqTrainer` (~0.18) i WER z `eval_wer.py` (~0.06) to **różne
potoki**: pierwszy to `generate()` z transformers bez VAD i bez normalizacji, drugi
to faster-whisper z VAD i `temperature=0.0`. Nie są porównywalne. Metryka walidacyjna
służy WYŁĄCZNIE do wyboru checkpointu; o wartości modelu rozstrzyga `eval_wer.py`.

## Wyniki z 2026-09-23 (478 próbek do odcięcia, split 72 testowe) — nieaktualne

| wariant | WER soft | WER raw | CER |
|---|---|---|---|
| baseline `models/turbo` | 0.0556 | **0.0753** | **0.0235** |
| kontrola: baza przez nasz eksport | 0.0556 | 0.0753 | 0.0235 |
| LoRA r=32, lr 1e-3, 3 ep. | **0.0454** | 0.0878 | 0.0257 |
| LoRA r=8, lr 1e-4, 2 ep. | 0.0578 | 0.1119 | 0.0316 |
| LoRA r=32, lr 2e-4, 8 ep. (best@100) | 0.0630 | 0.1178 | 0.0319 |
| + `initial_prompt auto` (inny split) | 0.0614 | 0.1354 | 0.0358 |

**Wnioski:**

1. **Nie podpięto żadnego modelu.** `src/config.yaml` bez zmian.
2. Kontrola jest identyczna z baseline co do czwartego miejsca — ścieżka
   merge → CTranslate2 nie wprowadza żadnej degradacji. Eksport jest sprawny.
3. `initial_prompt` z listą terminów **szkodzi** — Whisper traktuje prompt jako
   kontekst do naśladowania stylistycznie, nie jako słownik. Ścieżka zamknięta.
4. Najlepszy wariant (r=32, lr 1e-3) daje −18% na `soft`, ale bootstrap na tych
   samych próbkach daje 95% CI `[-0.0281, +0.0057]` — **przedział obejmuje zero**.
   Poprawa jest prawdopodobna (P ≈ 0.89), ale niepotwierdzona przy 72 próbkach.
5. Wszystkie warianty pogarszają `raw` (interpunkcja, wielkość liter) o 17–56%.

**Kiedy wrócić:** przy ~2× większym zbiorze. Podnieś `CUTOFF_TS` w `data.py`,
przemierz baseline od nowa i powtórz. Konfiguracja startowa: r=32, lr 1e-3, 3 epoki.

## Sprawdzenie istotności

```
uv run python eval_wer.py --model-dir <A> --dump dump_a.json
uv run python eval_wer.py --model-dir <B> --dump dump_b.json
uv run python bootstrap.py dump_a.json dump_b.json
```

Bez tego kroku różnica WER rzędu 1 punktu przy ~70 próbkach jest nie do odróżnienia
od doboru zbioru testowego.

## Uwagi

- Split train/test jest deterministyczny (`data.py`, seed 0) — wszystkie pomiary porównywalne.
- Do treningu idą **wszystkie** próbki, także `edited: false` — uczą model nie psuć tego,
  co już robi dobrze.
- `--prompt auto` wyciąga terminy tylko ze splitu treningowego, nigdy z testowego.
