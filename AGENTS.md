# AGENTS.md

## Project overview

- This repository contains a PySide6 desktop application for guitar practice.
- Application code lives in `src/gt_trainer/`; tests live in `tests/`.
- `setup.py` and `Makefile` define the Windows cx_Freeze release workflow.

## Windows Python environment

- Build and verification must use the Windows uv executable at `/mnt/c/Users/katao/.local/bin/uv.exe`.
- Do not use the Linux `uv`, `python`, or `pytest` for project tests, dependency synchronization, or release builds.
- Prefer the repository's `make` targets instead of invoking uv commands directly.
- The `.venv` directory is the Windows uv environment. Do not replace it with a Linux virtual environment.
- Do not manually install packages into `.venv`; update `pyproject.toml` and run `make sync` when dependency changes are intentional.

## Common commands

- `make test`: run the complete test suite with Windows uv.
- `make check`: compile application and test modules, then run the tests.
- `make run`: launch the application from the Windows environment.
- `make build`: create the cx_Freeze application under `dist/gt_trainer/`.
- `make clean`: remove generated build and distribution directories.

Release builds are not routine verification. Run `make build` only when the user asks for a build or the task directly concerns packaging.

## Development guidance

- Preserve the SQLite schema and saved exercise/session compatibility unless a migration is included.
- Keep audio processing off the GUI thread.
- Keep pitch/timing algorithms independently testable without audio hardware.
- Hardware-dependent input/output checks may remain unverified when no Windows audio device is available; report that boundary.
- Preserve unrelated user changes and inspect `git status --short` before editing.

