# Lessons Learned

Extracted from SPIR reviews. Stable patterns and gotchas for future builders.

---

## Spec 14: FAVA Trails CLI

### Dotfile temp paths
`Path.with_suffix(".tmp")` on a dotfile like `.env` gives `.tmp` (not `.env.tmp`) because Python treats `.env` as having an empty extension. Use `Path.with_name(path.name + ".tmp")` for reliable dotfile temp paths.

### subprocess health checks need timeouts
Any CLI `doctor`-style command calling an external binary must set `timeout=N`. A health check that hangs is worse than one that fails fast. Pattern:
```python
try:
    result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=2)
except (OSError, subprocess.TimeoutExpired) as e:
    print(f"  ERROR: {e}")
```

### YAML user-editable config needs error handling
`yaml.safe_load()` on any user-editable file needs `yaml.YAMLError` catch. Specs focus on `.env` write safety but miss YAML safety — code review will catch it, but better to add it preemptively.

### Argparse scope subcommands
When using argparse nested subparsers (`scope set`, `scope list`), set `func` on both the parent (`p_scope.set_defaults(func=cmd_scope)`) and each subcommand. In `main()`, a single `if hasattr(args, "func")` check handles both cases correctly — no special-casing needed.

### Spec renaming during plan phase
When an architect renames a command (`init-data` → `bootstrap`) between spec approval and plan approval, the builder must apply the rename to the plan file before proceeding. Do not infer intent — wait for explicit instruction and apply literally.
