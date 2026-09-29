@echo off
cd /d "%~dp0"
rem Direct venv python: `uv run` re-checks the lock on every start (~1 s). After changing deps run `uv sync --extra local`.
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe run.py
) else (
    rem Fresh checkout: let uv create and sync the venv once.
    uv run --extra local python run.py
)
