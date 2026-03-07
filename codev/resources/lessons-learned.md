# Lessons Learned

## SDK Migration Pattern (Spec 17 — Replace OpenAI SDK with any-llm-sdk)

### Inspect Before Specifying

Before writing the spec and plan for an SDK migration, inspect the target SDK in a Python REPL:

```python
from any_llm.exceptions import AnyLLMError, ProviderError
e = ProviderError("test", original_exception=None, provider_name="openai")
print(dir(e))               # Check available attributes
print(hasattr(e, "status_code"))  # Verify expected attributes exist
```

This catches attribute mismatches (e.g., `ProviderError` has no `.status_code`) before the spec
is finalized, avoiding rework.

### Use `getattr` for Exception Attributes from Wrapped Exceptions

When wrapping SDK exceptions, attributes on the underlying SDK exception may not be promoted
to the wrapper class:

```python
# WRONG — ProviderError has no .status_code
status_code = e.status_code

# CORRECT — get from the original exception with a fallback
status_code = getattr(e.original_exception, "status_code", "unknown")
```

### Spec Files Affected: Run grep Before Finalizing

Before finalizing the spec's Files Affected table, run:

```bash
grep -r "import <old_sdk>" src/
```

This catches transitive imports that would otherwise be missed (e.g., `trust_gate.py` importing
`openai` was not in the initial spec's Files Affected list).

### Timeout via `client_args`

When using `any-llm-sdk`, timeout is not a top-level `acompletion()` parameter:

```python
# WRONG
await any_llm.acompletion(model=..., timeout=60.0)

# CORRECT
await any_llm.acompletion(model=..., client_args={"timeout": 60.0})
```
