"""Minimal, FAIL-CLOSED PyYAML compatibility shim (Chip Convergence, 2026-07-23).

Why this exists: the organizer's `rtl_gen_lib/rtl_gen_main.py` tries `import yaml`
and, on ImportError, falls back to `_load_yaml_minimal`, which is unconditionally
broken (`result, stack = {}, [(0, result)]` → UnboundLocalError before parsing
any spec). The organizer documents PyYAML as OPTIONAL and their DEPENDENCIES.md
says the env is stdlib-only, so the generator can crash at eval and zero our run.

This module is placed on the rtl_gen SUBPROCESS `PYTHONPATH` **only when the real
PyYAML is absent** (see nxp_agent._rtl_gen_env), so `import yaml` resolves here and
the correct loader is used. It parses ONLY the canonical flat `key: value` subset
the agent emits (verified: all 8 specs are flat strings + decimal ints), plus
simple indent-nested mappings, and FAILS CLOSED (raises) on anything else — never
silently misparses. No unsafe tags / object construction (Codex acceptance §4.1).

Contract vs real PyYAML: implements `safe_load` for the supported subset only.
"""
from __future__ import annotations


class YAMLError(Exception):
    pass


def _scalar(v: str):
    """string | int (decimal/hex) | bool | None — never executes anything."""
    s = v.strip()
    if s == "" or s == "~" or s.lower() == "null":
        return None
    if (s[0], s[-1]) in (('"', '"'), ("'", "'")) and len(s) >= 2:
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    body = s[1:] if s[:1] == "-" else s
    if body.isdigit():
        return int(s)
    if body[:2].lower() == "0x" and len(body) > 2 and \
            all(c in "0123456789abcdefABCDEF" for c in body[2:]):
        return int(s, 16)
    return s          # bare/unquoted string


def safe_load(stream):
    """Parse the supported flat/indent-nested mapping subset. Raises YAMLError
    on unsupported constructs (lists, tags, anchors, block scalars, flow
    collections) and on a non-mapping top level or duplicate keys."""
    text = stream.read() if hasattr(stream, "read") else stream
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    root: dict = {}
    stack = [(-1, root)]          # (indent, dict) — no walrus/order trap
    seen_at = [set()]            # duplicate-key guard per level
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # fail closed on constructs this subset does not support
        if stripped[0] in "-&*!?[{|>":
            raise YAMLError(f"line {lineno}: unsupported YAML construct "
                            f"{stripped[0]!r} (shim handles flat/nested "
                            f"key:value only)")
        if ":" not in stripped:
            raise YAMLError(f"line {lineno}: expected 'key: value', got "
                            f"{stripped!r}")
        indent = len(line) - len(line.lstrip())
        key, _, val = stripped.partition(":")
        key = key.strip()
        if not key:
            raise YAMLError(f"line {lineno}: empty key")
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
            seen_at.pop()
        d = stack[-1][1]
        if key in seen_at[-1]:
            raise YAMLError(f"line {lineno}: duplicate key {key!r}")
        seen_at[-1].add(key)
        v = val.strip()
        if v == "":                     # opens a nested mapping
            child: dict = {}
            d[key] = child
            stack.append((indent, child))
            seen_at.append(set())
        else:
            if v[0] in "[{":            # flow collections unsupported
                raise YAMLError(f"line {lineno}: flow collections unsupported")
            d[key] = _scalar(v)
    if not isinstance(root, dict):
        raise YAMLError("top-level YAML must be a mapping")
    return root


def load(stream, Loader=None):          # organizer only calls safe_load; alias
    return safe_load(stream)


__version__ = "shim-1.0-chipconvergence"
