# Eksport adaptera + oba pomiary w jednym przebiegu.
# Razem, bo bez CUTOFF_TS każde nowe nagranie zmienia podział train/test —
# baseline i model zmierzone w osobnych oknach czasowych byłyby nieporównywalne.
Set-Location D:\Tools\ww-llm\training

$out = "D:/Tools/whisper-writer/models/turbo-ft-fixed"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }

Write-Output "=== EKSPORT ==="
uv run python export_ct2.py --adapter out/best --output $out
if ($LASTEXITCODE -ne 0) { Write-Output "EKSPORT PADL"; exit 1 }

Write-Output "=== BASELINE ==="
uv run python eval_wer.py --model-dir D:/Tools/whisper-writer/models/turbo --dump dump_base.json

Write-Output "=== FINE-TUNED ==="
uv run python eval_wer.py --model-dir $out --dump dump_ft.json

Write-Output "=== BOOTSTRAP ==="
uv run python bootstrap.py dump_base.json dump_ft.json

Write-Output "=== TERMINY ==="
uv run python term_hits.py dump_base.json dump_ft.json
Write-Output "=== KONIEC ==="
