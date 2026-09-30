# Export adapter + both measurements in a single pass.
# Together because without a timestamp cutoff every new recording changes the
# train/test split — baseline and model measured in separate time windows would
# not be comparable.
param(
    [Parameter(Mandatory=$true)]
    [string]$BaseModelDir,   # path to the base CTranslate2 model (e.g. ../models/turbo)
    [Parameter(Mandatory=$true)]
    [string]$OutputDir       # destination for the exported fine-tuned model
)
Set-Location $PSScriptRoot

if (Test-Path $OutputDir) {
    # only wipe a previous CTranslate2 export, never an arbitrary directory
    if (-not (Test-Path (Join-Path $OutputDir "model.bin"))) {
        throw "Refusing to delete '$OutputDir': not a CTranslate2 export (no model.bin)"
    }
    Remove-Item $OutputDir -Recurse -Force
}

Write-Output "=== EXPORT ==="
uv run python export_ct2.py --adapter out/best --output $OutputDir
if ($LASTEXITCODE -ne 0) { Write-Output "EXPORT FAILED"; exit 1 }

Write-Output "=== BASELINE ==="
uv run python eval_wer.py --model-dir $BaseModelDir --dump dump_base.json

Write-Output "=== FINE-TUNED ==="
uv run python eval_wer.py --model-dir $OutputDir --dump dump_ft.json

Write-Output "=== BOOTSTRAP ==="
uv run python bootstrap.py dump_base.json dump_ft.json

Write-Output "=== TERM HITS ==="
uv run python term_hits.py dump_base.json dump_ft.json
Write-Output "=== DONE ==="
