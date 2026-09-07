"""Operator-only, exact-plan duplicate maintenance; never invoked by MCP tools."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path

import yaml

from .config import sanitize_scope_path
from .governance import Visibility, record_index
from .models import ThoughtRecord
from .transactions import _file_lock, _sync_directory, journal_path, persist_governance


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _scan(root: Path, *, allow_journal: bool = False) -> dict[str, str]:
    """No JJ invocation or lock creation: dry runs never write repository metadata."""
    if not allow_journal and journal_path(root).exists():
        raise ValueError("Interrupted governance transaction: recover it before planning a migration")
    texts = {}
    for path in sorted((root / "trails").glob("**/thoughts/**/*.md")):
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root):
            raise ValueError("Symlinked thought paths are not supported for migration")
        text = path.read_bytes().decode("utf-8")
        texts[path.relative_to(root).as_posix()] = text
    if not allow_journal and journal_path(root).exists():
        raise ValueError("Governance changed during scan; retry")
    return texts


def capture(root: Path) -> dict[str, str]:
    """Optimistic stable read, with no writes even when the governance lock is absent.

    A plan is also revalidated under the exclusive governance lock at apply time.
    """
    root = root.resolve(strict=True)
    first = _scan(root)
    if first != _scan(root):
        raise ValueError("Thoughts changed during scan; retry")
    return first


def _frontmatter(text: str) -> dict:
    def default(value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise ValueError("Frontmatter contains a value unsupported by migration JSON")

    return json.loads(json.dumps(yaml.safe_load(text.split("---", 2)[1]), default=default))


def _rewrite(record: ThoughtRecord, original: str) -> str:
    # Preserve extension fields and exact body bytes that the typed model ignores.
    fm = _frontmatter(original)
    model = record.frontmatter.model_dump(mode="json")
    for field in ("parent_id", "intent_ref", "superseded_by", "supersedes_id", "relationships"):
        if field in fm or model[field] is not None:
            fm[field] = model[field]
    if "duplicate_migrations" in record.frontmatter.metadata.extra:
        fm.setdefault("metadata", {}).setdefault("extra", {})["duplicate_migrations"] = (
            record.frontmatter.metadata.extra["duplicate_migrations"]
        )
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---" + original.split("---", 2)[2]


def _scope(name: str) -> str:
    return name.removeprefix("trails/").split("/thoughts/", 1)[0]


def _parse_issues(texts: dict[str, str]) -> dict[str, str]:
    issues = {}
    for name, text in texts.items():
        try:
            if not text.startswith(("---\n", "---\r\n")) or len(text.split("---", 2)) != 3:
                raise ValueError("Explicit frontmatter required")
            fm = _frontmatter(text)
            if not isinstance(fm, dict) or not fm.get("thought_id") or not fm.get("created_at"):
                raise ValueError("Explicit identity and timestamp required")
            ThoughtRecord.from_markdown(text)
        except (ValueError, TypeError, yaml.YAMLError) as exc:
            issues[name] = type(exc).__name__ + ": invalid or missing governed frontmatter"
    return issues


def _records(root: Path, texts: dict[str, str]):
    invalid = _parse_issues(texts)
    records = {name: ThoughtRecord.from_markdown(text) for name, text in texts.items() if name not in invalid}
    index = record_index({root / name: record for name, record in records.items()}, root / "trails")
    return records, index


def _refs(record):
    fm = record.frontmatter
    for field, scope in (
        ("parent_id", fm.supersedes_scope if fm.parent_id == fm.supersedes_id else None),
        ("intent_ref", None),
        ("superseded_by", fm.superseded_scope),
        ("supersedes_id", fm.supersedes_scope),
    ):
        if target := getattr(fm, field):
            yield field, target, scope
    for rel in fm.relationships:
        yield f"relationships.{rel.type}", rel.target_id, None


def _report(root: Path, scope: str, texts: dict[str, str]) -> dict:
    records, index = _records(root, texts)
    buckets = {}
    for name in records:
        if _scope(name) == scope:
            # Exact stored body bytes, including whitespace. No semantic/near matching.
            body = texts[name].split("---", 2)[2]
            buckets.setdefault(_hash(body), []).append(name)
    groups = []
    for body_hash, names in sorted(buckets.items()):
        if len(names) < 2:
            continue
        members = []
        ids = {records[name].thought_id for name in names}
        inbound = [
            {"path": name, "field": field, "target_id": target, "target_scope": target_scope}
            for name, record in records.items()
            for field, target, target_scope in _refs(record)
            if target in ids and target_scope in (None, scope)
        ]
        for name in names:
            record = records[name]
            members.append(
                {
                    "path": name,
                    "scope": scope,
                    "current_approved": Visibility().allows(record, index),
                    "sha256": _hash(texts[name]),
                    "frontmatter": _frontmatter(texts[name]),
                }
            )
        groups.append({"body_sha256": body_hash, "members": members, "inbound": inbound})
    return {
        "schema": 1,
        "repository": str(root),
        "scope": scope,
        "body_matching": "exact UTF-8 bytes after closing frontmatter delimiter",
        "snapshot": {name: _hash(text) for name, text in texts.items()},
        "counts": {"repository": len(texts), "scope": sum(_scope(n) == scope for n in texts), "groups": len(groups)},
        "invalid_records": _parse_issues(texts),
        "groups": groups,
    }


def report(root: Path, scope: str) -> dict:
    root = root.resolve(strict=True)
    scope = sanitize_scope_path(scope)
    if not (root / "trails" / scope).is_dir():
        raise ValueError("Scope does not exist")
    return _report(root, scope, capture(root))


def _validation_context(text: str) -> dict:
    fm = _frontmatter(text)
    extra = fm.get("metadata", {}).get("extra", {})
    return {
        "frontmatter": {
            k: v
            for k, v in fm.items()
            if k != "validation_status" and ("valid" in k.lower() or "trust_gate" in k.lower())
        },
        "extra": {k: v for k, v in extra.items() if "valid" in k.lower() or "trust_gate" in k.lower()},
    }


def build_plan(root: Path, scope: str, canonical: dict[str, str], *, texts=None) -> dict:
    """Canonical map is body hash -> exact repository-relative path; no automatic winner."""
    root = root.resolve(strict=True)
    scope = sanitize_scope_path(scope)
    texts = capture(root) if texts is None else texts
    details = _report(root, scope, texts)
    records, index = _records(root, texts)
    groups = {g["body_sha256"]: g for g in details["groups"]}
    blockers = [f"Unparseable thought requires review: {name}" for name in details["invalid_records"]]
    redirects = {}
    removed = {}
    merged = {}
    all_ids = {}
    for name, record in records.items():
        all_ids.setdefault(record.thought_id, []).append(name)
    for group_hash, keep in sorted(canonical.items()):
        group = groups.get(group_hash)
        if group is None or keep not in [m["path"] for m in group["members"]]:
            blockers.append(f"Invalid canonical selection: {group_hash}")
            continue
        selected = records[keep]
        candidates = [m["path"] for m in group["members"]]
        statuses = {records[n].frontmatter.validation_status.value for n in candidates}
        if "approved" in statuses and not Visibility().allows(selected, index):
            blockers.append(f"Canonical must be approved current truth: {keep}")
        elif "approved" not in statuses and len(statuses) != 1:
            blockers.append(f"Mixed unapproved lifecycle requires a decision: {keep}")
        for name in candidates:
            record = records[name]
            fm = record.frontmatter
            if len(all_ids[record.thought_id]) != 1:
                blockers.append(f"Ambiguous thought identity: {name}")
            if fm.validation_status.value not in {"approved", "draft", "proposed"}:
                blockers.append(f"Conflicting lifecycle {fm.validation_status}: {name}")
            if fm.superseded_by or fm.supersedes_id:
                blockers.append(f"Existing supersession requires a separate lineage decision: {name}")
            if fm.source_type != selected.frontmatter.source_type or fm.confidence != selected.frontmatter.confidence:
                blockers.append(f"Source/confidence conflict: {name}")
            # Retain distinct review provenance, but never merge contradictory validation decisions.
            validations = _validation_context(texts[name])
            selected_validations = _validation_context(texts[keep])
            if any(validations.values()) and validations != selected_validations:
                blockers.append(f"Validation conflict: {name}")
            if name != keep:
                redirects[record.thought_id] = selected.thought_id
                removed[name] = keep
        merged[keep] = candidates
    after_records = {name: record.model_copy(deep=True) for name, record in records.items() if name not in removed}
    # Outbound semantic links must already agree, so collapsing identity cannot discard them.
    for keep, names in merged.items():
        expected = sorted((f, redirects.get(t, t), s) for f, t, s in _refs(records[keep]))
        for name in names:
            observed = sorted((f, redirects.get(t, t), s) for f, t, s in _refs(records[name]))
            if observed != expected:
                blockers.append(f"Outbound lineage/relationship conflict: {name}")
        fm = after_records[keep].frontmatter
        fm.metadata.extra.setdefault("duplicate_migrations", []).append(
            {
                "body_sha256": next(h for h, path in canonical.items() if path == keep),
                "retained_id": fm.thought_id,
                "removed_count": len(names) - 1,
                "operator_audit": digest({"before_snapshot": details["snapshot"], "canonical": canonical}),
            }
        )
    changed = set(merged)
    for name, record in after_records.items():
        fm = record.frontmatter
        for field in ("parent_id", "intent_ref", "superseded_by", "supersedes_id"):
            target = getattr(fm, field)
            target_scope = (
                fm.superseded_scope
                if field == "superseded_by"
                else fm.supersedes_scope
                if field == "supersedes_id" or (field == "parent_id" and fm.parent_id == fm.supersedes_id)
                else None
            )
            if target in redirects and target_scope in (None, scope):
                setattr(fm, field, redirects[target])
                changed.add(name)
        for rel in fm.relationships:
            if rel.target_id in redirects:
                rel.target_id = redirects[rel.target_id]
                changed.add(name)
        for field, target, _ in _refs(record):
            if name in changed and target == record.thought_id:
                blockers.append(f"Redirect would create a self link: {name} {field}")
    # A changed parent/supersession edge must not introduce any cycle.
    for name in changed:
        for field in ("parent_id", "superseded_by", "supersedes_id"):
            current, seen = records[name].thought_id, set()
            by_id = {r.thought_id: r for r in after_records.values() if len(all_ids[r.thought_id]) == 1}
            while current in by_id:
                if current in seen:
                    blockers.append(f"Cyclic {field} chain after redirect: {name}")
                    break
                seen.add(current)
                current = getattr(by_id[current].frontmatter, field)

    def unresolved(source_records):
        source_index = record_index({root / n: r for n, r in source_records.items()}, root / "trails")
        return sorted(
            (name, field, target, target_scope or "")
            for name in changed
            for field, target, target_scope in _refs(source_records[name])
            if (f"{target_scope}:{target}" if target_scope else target) not in source_index
        )

    unresolved_before, unresolved_after = unresolved(records), unresolved(after_records)
    for edge in set(unresolved_after) - set(unresolved_before):
        blockers.append(f"Redirect creates an unresolved reference: {edge[0]} {edge[1]}")
    lineage = {
        "redirected_identities": redirects,
        "unresolved_before": [list(edge) for edge in unresolved_before],
        "unresolved_after": [list(edge) for edge in unresolved_after],
        "approved_current_before": sum(
            Visibility().allows(records[n], index) for names in merged.values() for n in names
        ),
        "approved_current_after": sum(
            Visibility().allows(
                after_records[n], record_index({root / p: r for p, r in after_records.items()}, root / "trails")
            )
            for n in merged
        ),
    }
    operations = []
    for name in sorted(changed | set(removed)):
        after = None if name in removed else _rewrite(after_records[name], texts[name])
        operations.append({"path": name, "before": texts[name], "after": after})
    after_texts = dict(texts)
    for operation in operations:
        if operation["after"] is None:
            after_texts.pop(operation["path"])
        else:
            after_texts[operation["path"]] = operation["after"]
    result = {
        "schema": 1,
        "repository": str(root),
        "scope": scope,
        "canonical": canonical,
        "before_snapshot": details["snapshot"],
        "after_snapshot": {n: _hash(t) for n, t in after_texts.items()},
        "counts": {"before": len(texts), "after": len(after_texts), "deleted": len(removed), "rewritten": len(changed)},
        "blockers": sorted(set(blockers)),
        "lineage": lineage,
        "operations": operations,
    }
    result["digest"] = digest(result)
    return result


def write_private(path: Path, value) -> None:
    """Artifacts include governed content; create outside source control, owner-only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def _validate_plan(root: Path, plan: dict, confirmation: str) -> None:
    unsigned = {k: v for k, v in plan.items() if k != "digest"}
    if digest(unsigned) != plan.get("digest") or confirmation != plan["digest"]:
        raise ValueError("Plan digest mismatch: review the exact plan and provide its digest")
    if plan.get("schema") != 1 or plan.get("repository") != str(root):
        raise ValueError("Plan repository/schema mismatch")
    if plan["blockers"] or not plan["operations"]:
        raise ValueError("Plan has blockers or no selected operations")
    for operation in plan["operations"]:
        name = operation["path"]
        path = root / name
        if (
            path.resolve() != path
            or not path.is_relative_to(root / "trails")
            or "/thoughts/" not in name
            or path.suffix != ".md"
        ):
            raise ValueError("Unsafe migration path")


def _verify_rules(root: Path, plan: dict, texts: dict[str, str], *, after: bool) -> None:
    original = dict(texts)
    if after:
        for operation in plan["operations"]:
            original[operation["path"]] = operation["before"]
    if build_plan(root, plan["scope"], plan["canonical"], texts=original) != plan:
        raise ValueError("Plan does not match safe migration rules")


def _read_receipt(path: Path, plan: dict, rollback: bool, *, committed: bool = False) -> dict:
    try:
        receipt = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("Recovery receipt is missing or invalid; inspect it before retrying") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("plan") != plan
        or receipt.get("rollback") != rollback
        or receipt.get("status") not in {"prepared", "rolled_back" if rollback else "applied"}
    ):
        raise ValueError("Recovery receipt is invalid; inspect it before retrying")
    fields = ("recovery_commit", "recovery_operation") + (
        ("committed_commit", "committed_operation") if committed else ()
    )
    for field in fields:
        size = 40 if field.endswith("commit") else 128
        if not isinstance(receipt.get(field), str) or not re.fullmatch(r"[0-9a-f]{" + str(size) + "}", receipt[field]):
            raise ValueError("Recovery receipt lacks valid durable VCS evidence")
    return receipt


def _save_receipt(path: Path, receipt: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False, newline=""
        ) as stream:
            temporary = Path(stream.name)
            json.dump(receipt, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def _verify_committed(vcs, receipt: dict, message: str) -> None:
    dirty, _ = await vcs._run("diff", "--name-only")
    if dirty or await vcs.conflicts():
        raise ValueError("Recovery verification requires a clean conflict-free repository")
    commit = receipt["committed_commit"]
    proof, _ = await vcs._run(
        "log", "-r", f"{commit} & ancestors(@)", "--no-graph", "-T", 'commit_id ++ "\\n" ++ description'
    )
    if proof != commit + "\n" + message:
        raise ValueError("Recovery receipt does not identify the durable migration in current history")


async def apply_plan(vcs, plan: dict, confirmation: str, *, rollback: bool = False) -> dict:
    """Explicit operator maintenance with private, recoverable publication evidence."""
    root = vcs.repo_root.resolve(strict=True)
    _validate_plan(root, plan, confirmation)
    source = plan["after_snapshot"] if rollback else plan["before_snapshot"]
    target = plan["before_snapshot"] if rollback else plan["after_snapshot"]
    status = "rolled_back" if rollback else "applied"
    message = ("Rollback" if rollback else "Migrate") + " exact duplicates " + plan["digest"]
    receipt_path = root / ".jj" / "fava-migrations" / (plan["digest"] + ("-rollback" if rollback else "") + ".json")
    current = capture(root) if not journal_path(root).exists() else None
    if current is not None and {n: _hash(t) for n, t in current.items()} == target:
        # Matching bytes alone cannot prove that an operator migration committed.
        _read_receipt(receipt_path, plan, rollback, committed=True)
        async with vcs.repo_lock:
            with _file_lock(root, exclusive=True):
                current = capture(root)
                if {n: _hash(t) for n, t in current.items()} != target:
                    raise ValueError("Repository changed during recovery verification")
                _verify_rules(root, plan, current, after=not rollback)
                receipt = _read_receipt(receipt_path, plan, rollback, committed=True)
                await _verify_committed(vcs, receipt, message)
                if receipt["status"] == "prepared":
                    receipt["status"] = status
                    _save_receipt(receipt_path, receipt)
        return {"status": "already_" + status, "digest": plan["digest"]}

    async def prepare():
        texts = capture(root)
        if {n: _hash(t) for n, t in texts.items()} != source:
            raise ValueError("Repository changed since review; create and review a new plan")
        _verify_rules(root, plan, texts, after=rollback)
        if await vcs.conflicts():
            raise ValueError("Resolve repository conflicts before migration")
        dirty, _ = await vcs._run("diff", "--name-only")
        if dirty:
            raise ValueError("Repository must have a clean working change before migration")
        commit, _ = await vcs._run("log", "-r", "@", "--no-graph", "-T", "commit_id")
        operation, _ = await vcs._run("op", "log", "--limit", "1", "--no-graph", "-T", "id")
        receipt = {
            "status": "prepared",
            "recovery_commit": commit,
            "recovery_operation": operation,
            "rollback": rollback,
            "plan": plan,
        }
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        _sync_directory(receipt_path.parent.parent)
        if receipt_path.exists():
            _read_receipt(receipt_path, plan, rollback)
        else:
            write_private(receipt_path, receipt)

    async def committed():
        # This runs under the transaction lock before journal removal publishes.
        if {n: _hash(t) for n, t in _scan(root, allow_journal=True).items()} != target:
            raise RuntimeError("Post-migration verification failed; inspect the recovery receipt")
        receipt = _read_receipt(receipt_path, plan, rollback)
        receipt["status"] = "prepared"
        receipt["committed_commit"], _ = await vcs._run("log", "-r", "@-", "--no-graph", "-T", "commit_id")
        receipt["committed_operation"], _ = await vcs._run("op", "log", "--limit", "1", "--no-graph", "-T", "id")
        await _verify_committed(vcs, receipt, message)
        _save_receipt(receipt_path, receipt)

    writes = {root / o["path"]: o["before"] if rollback else o["after"] for o in plan["operations"]}
    await persist_governance(vcs, writes, message, prepare=prepare, committed=committed)
    # A crash here is recoverable: the prepared receipt already proves durability.
    receipt = _read_receipt(receipt_path, plan, rollback, committed=True)
    receipt["status"] = status
    _save_receipt(receipt_path, receipt)
    return {"status": status, "digest": plan["digest"], "counts": plan["counts"], "receipt": str(receipt_path)}
