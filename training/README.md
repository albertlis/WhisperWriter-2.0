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

## 1. Baseline — measure before you train

```
uv run python eval_wer.py --model-dir <path/to/base-ct2>
uv run python eval_wer.py --model-dir <path/to/base-ct2> --prompt auto
```

The second run is a control: if `initial_prompt` alone drops WER as much as training
would, training adds no value. Record both numbers before proceeding.

## 2. Training

```
uv run python train_lora.py
```

Roughly 56 steps per epoch at the default settings (batch 4, gradient accumulation 1).
Evaluation runs every 50 steps; `load_best_model_at_end` selects the checkpoint.
If eval WER rises from the very first evaluation — overfitting: try `--epochs 1` or
`--rank 8`. OOM → `--batch-size 2`.

## 3. Export to faster-whisper

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

## 5. Full pipeline in one pass

```powershell
.\run_eval.ps1 -BaseModelDir <path/to/base-ct2> -OutputDir <output-dir>
```

Runs export → baseline → fine-tuned → bootstrap → term hits in a single invocation.
Run as a single pass because the dataset grows with every recording: baseline and model
measured in separate windows may have different train/test splits and are not comparable.

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
Use `run_eval.ps1` to guarantee both measurements use the same split.

**WER aggregates too slowly to answer "does it know the terms?"**
A proper noun counts the same as a function word and disappears in the mean. Use
`term_hits.py` separately to measure vocabulary coverage.

**Term accuracy is the right criterion when vocabulary is the goal.**
If the user's priority is proper nouns and technical terms over punctuation, term hit
rate measures that directly. Overall WER (especially "raw" WER including punctuation)
is a poor proxy for this goal.
