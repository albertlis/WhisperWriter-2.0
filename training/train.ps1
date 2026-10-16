# One command: train -> export -> measure baseline vs new model -> switch the app to it.
#   .\train.ps1
# Baseline and model are measured in one pass on purpose: every new recording changes
# the train/test split, so measurements from separate runs are not comparable.
param(
    [double]$Epochs = 3,
    [double]$Lr = 2e-4,
    [string]$BaseModelDir = "..\models\turbo",
    [string]$OutputDir = "..\models\turbo-ft-$(Get-Date -Format yyyyMMdd-HHmm)",
    [switch]$SkipTrain,   # reuse the existing out/best adapter
    [switch]$NoSwitch     # do not point src/config.yaml at the new model
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($name, [scriptblock]$cmd) {
    Write-Output "=== $name ==="
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$name FAILED (exit $LASTEXITCODE)" }
}

if (-not $SkipTrain) {
    Step "TRAIN" { uv run python train_lora.py --epochs $Epochs --lr $Lr }
}
if (Test-Path $OutputDir) {
    # only wipe a previous CTranslate2 export, never an arbitrary directory
    if (-not (Test-Path (Join-Path $OutputDir "model.bin"))) {
        throw "Refusing to delete '$OutputDir': not a CTranslate2 export (no model.bin)"
    }
    Remove-Item $OutputDir -Recurse -Force
}
Step "EXPORT"     { uv run python export_ct2.py --adapter out/best --output $OutputDir }
Step "BASELINE"   { uv run python eval_wer.py --model-dir $BaseModelDir --dump dump_base.json }
Step "FINE-TUNED" { uv run python eval_wer.py --model-dir $OutputDir --dump dump_ft.json }
Step "BOOTSTRAP"  { uv run python bootstrap.py dump_base.json dump_ft.json }
Step "TERM HITS"  { uv run python term_hits.py dump_base.json dump_ft.json }

if (-not $NoSwitch) {
    $model = (Resolve-Path $OutputDir).Path -replace '\\', '/'
    $cfg = "..\src\config.yaml"
    $text = Get-Content $cfg -Raw
    if ($text -notmatch '(?m)^\s*model_path:') { throw "model_path not found in $cfg" }
    $text -replace '(?m)^(\s*model_path:).*$', "`$1 $model" | Set-Content $cfg -NoNewline -Encoding utf8
    Write-Output "App now uses $model - restart the app."
}
Write-Output "=== DONE ==="
