# Contributing to FAVA Trails

Thank you for your interest in contributing! This guide covers everything you need to get started.

## Prerequisites

- **Python 3.11+** — [python.org](https://www.python.org/downloads/)
- **JJ (Jujutsu)** — required for running tests (FAVA Trails uses JJ as its VCS engine)
- **uv** — Python package manager ([docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/))

### Install JJ

```bash
bash scripts/install-jj.sh
```

This downloads a pre-built binary for your platform (Linux x86_64 or aarch64) to `~/.local/bin/jj`. Make sure `~/.local/bin` is in your `PATH`.

## Setup

```bash
# Clone the repo
git clone https://github.com/MachineWisdomAI/fava-trails.git
cd fava-trails

# Install dependencies (including dev tools)
uv sync
```

## Running Tests

```bash
uv run pytest -v
```

Tests create temporary JJ repositories in isolated directories — no external data repo required.

## Linting

```bash
uv run ruff check src/ tests/
```

All PRs must pass ruff with zero errors.

## Making Changes

1. Fork the repo and create a branch: `git checkout -b fix/my-fix`
2. Make your changes
3. Run tests and linting to verify everything passes
4. Push your branch and open a pull request

## PR Expectations

- Tests pass (`uv run pytest -v` exits 0)
- Lint passes (`uv run ruff check src/ tests/` exits 0)
- Descriptive commit messages (what changed and why)
- One logical change per PR — keep PRs focused

## About the `codev/` Directory

The `codev/` directory contains the internal development methodology (specs, plans, reviews) used by the Machine Wisdom team. External contributors are **not expected** to use or understand these files — they're here for transparency. Your PR does not need a spec or plan document.

## Reporting Issues

Use the [bug report template](https://github.com/MachineWisdomAI/fava-trails/issues/new?template=bug_report.yml). Include your JJ version (`jj --version`), OS, Python version, and steps to reproduce.

For security vulnerabilities, please use [GitHub Security Advisories](https://github.com/MachineWisdomAI/fava-trails/security/advisories/new) — do not file public issues for security bugs.
