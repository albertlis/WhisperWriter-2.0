# Fine-tuning Whisper on your own voice

Separate environment — **do not** mix with the application venv.
All commands run from the `training/` directory.

## 0. Environment and GPU (required)

```
uv sync
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_capability(0))"
```

Expected output: `True` and a capability tuple matching your GPU (e.g. `(12, 0)` for
Blackwell sm_120). If `False`, training will not run usefully.

## 1. Quick start — one command

```powershell
cd training
.\train.ps1
```

That is all. The script:

1. trains a LoRA adapter on everything in `../training_data/` (`out/best`),
2. exports it to `../models/turbo-ft-<date>-<time>` (CTranslate2, for faster-whisper),
3. measures the base model (`../models/turbo`) and the new one on the same test split,
4. prints bootstrap CI for the WER difference and proper-noun hit counts,
5. points `model_options.local.model_path` in `src/config.yaml` at the new model.

Restart the app afterwards. Takes ~1 h on an RTX 5080. **Do not dictate while it runs** —
new recordings change the train/test split.

Options (all optional):

| option | default | meaning |
|---|---|---|
| `-Epochs` | `3` | training epochs |
| `-Lr` | `2e-4` | learning rate — see Lessons learned before raising it |
| `-BaseModelDir` | `..\models\turbo` | base CTranslate2 model used as baseline |
| `-OutputDir` | `..\models\turbo-ft-<date>` | export destination |
| `-SkipTrain` | off | reuse existing `out/best`, only export + measure |
| `-NoSwitch` | off | leave `src/config.yaml` untouched |

Long runs: start detached so the job survives a closed terminal and log to a file:

```powershell
Start-Process powershell -ArgumentList '-File','train.ps1' -RedirectStandardOutput train.log -RedirectStandardError train.err -WindowStyle Hidden
```

Want to roll back? Set `model_path` in `src/config.yaml` back to the previous model.

Sections below describe the individual steps for manual use.

### Merging data from another computer

`training_data/` is `audio/*.flac` + `metadata.jsonl` (one JSON line per recording).
To add recordings from another machine: copy its `audio/*.flac` into `training_data/audio/`
(names are timestamped + random, no collisions) and append its `metadata.jsonl` lines to the
local one. Back up `metadata.jsonl` first.

## 2. Baseline — measure before you train

```
uv run python eval_wer.py --model-dir <path/to/base-ct2>
uv run python eval_wer.py --model-dir <path/to/base-ct2> --prompt auto
```

The second run is a control: if `initial_prompt` alone drops WER as much as training
would, training adds no value.

## 3. Training only

```
uv run python train_lora.py
```

Roughly 80 steps per epoch at the default settings (batch 8, gradient accumulation 1).
Evaluation runs every 50 steps; `load_best_model_at_end` selects the checkpoint.
If eval WER rises from the very first evaluation — overfitting: try `--epochs 1` or
`--rank 8`.

The script caps PyTorch at the VRAM free at startup, so a too-large batch fails with a
real OOM instead of silently spilling into shared memory. Mel spectrograms are computed on
6 CPU processes and cached; bf16 + TF32 + SDPA attention on the GPU.

**Picking batch size / gradient checkpointing on a different GPU — measure, don't guess:**

```
uv run python train_lora.py --probe 20 --batch-size 8 --grad-checkpointing
uv run python train_lora.py --probe 20 --batch-size 4 --no-grad-checkpointing
```

Each prints peak VRAM and seconds per sample. Take the fastest per-sample config whose peak
leaves ~2–3 GB headroom below the cap (the app may load Whisper while you train).
Measured on RTX 5080 16 GB:

| batch | grad ckpt | peak VRAM | s/sample |
|---|---|---|---|
| 4 | off | 13.7 GiB (at cap) | 0.236 |
| 4 | on | 6.2 GiB | 0.267 |
| **8** | **on** | **10.1 GiB** | **0.205** ← default |
| 16 | on | 13.8 GiB (at cap) | 0.171 |

## 4. Export to faster-whisper

```
uv run python export_ct2.py --adapter out/best --output <output-dir>
```

To export the bare base model as a control (verifies the conversion adds no degradation):

```
uv run python export_ct2.py --output <output-dir-control>
```

## 4. Compare and hook up

```
uv run python eval_wer.py --model-dir <output-dir>
```

Lower WER than baseline **and** lower than the prompt-only variant → set
`model_options.local.model_path` in `src/config.yaml` to `<output-dir>`.
No code changes required.

Always run bootstrap before claiming a gain:

```
uv run python eval_wer.py --model-dir <path/to/base-ct2> --dump dump_base.json
uv run python eval_wer.py --model-dir <output-dir>        --dump dump_ft.json
uv run python bootstrap.py dump_base.json dump_ft.json
```


## Lessons learned

These observations are based on real experiments; treat them as strong priors, not rules.

**Learning rate is the most important hyperparameter.**
`lr 1e-3` learns proper nouns quickly but degrades general WER significantly (measured
soft WER roughly tripled in one experiment). `lr 2e-4` achieves the same improvement on
proper nouns while keeping WER change indistinguishable from noise. Start at `2e-4`.

**`initial_prompt` with a term list hurts.**
Whisper treats the prompt as style context to imitate, not as a vocabulary hint. A
comma-separated list of terms teaches it to generate clipped phrases without punctuation.
Measured: raw WER nearly doubled with `--prompt auto` vs no prompt.

**Bootstrap before claiming a gain on small test sets.**
With ~70 test samples a 1-point WER difference is within sampling noise. Always run
`bootstrap.py` and check that the 95% CI excludes zero before announcing an improvement.

**Trainer `eval_wer` and `eval_wer.py` are different pipelines.**
The in-trainer metric uses `generate()` from transformers without VAD and without
normalisation. `eval_wer.py` uses faster-whisper with VAD and `temperature=0.0`.
The two numbers are not comparable. Use the Trainer metric only for checkpoint selection;
use `eval_wer.py` for all model quality claims.

**VRAM saturation on Windows causes silent slowdown, not OOM.**
When VRAM fills up the Windows driver spills to host RAM silently. Symptom: step time
grows from ~2 s to ~180 s with no error or warning. Use `--grad-checkpointing` by
default; it costs ~25% extra time but keeps VRAM well within budget.

**`datasets < 4.0` is required on Windows.**
`datasets` 4.x decodes audio through `torchcodec`, which needs a separately installed
FFmpeg on Windows. Pin `<4.0` in `pyproject.toml` to avoid this dependency.

**Measure baseline and fine-tuned model in a single pass.**
Without a timestamp cutoff the dataset grows with every recording, changing
`train_test_split`. The same sample can move from test to train between two runs.
`train.ps1` does this — use it to guarantee both measurements use the same split.

**WER aggregates too slowly to answer "does it know the terms?"**
A proper noun counts the same as a function word and disappears in the mean. Use
`term_hits.py` separately to measure vocabulary coverage.

**Term accuracy is the right criterion when vocabulary is the goal.**
If the user's priority is proper nouns and technical terms over punctuation, term hit
rate measures that directly. Overall WER (especially "raw" WER including punctuation)
is a poor proxy for this goal.
