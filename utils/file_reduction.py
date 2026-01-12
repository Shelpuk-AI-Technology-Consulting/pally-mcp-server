"""
Structure-preserving file reduction helpers.

These helpers intentionally avoid LLM calls and aim to preserve semantic boundaries
when a full file cannot fit into the remaining token budget.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from utils.token_utils import estimate_tokens


@dataclass(frozen=True)
class ReducedFile:
    content: str
    estimated_tokens: int
    was_reduced: bool


def _first_nonempty_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _trim_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    lines = text.splitlines()
    if not lines:
        return ""

    # Keep head + tail and shrink until within budget.
    head = 120
    tail = 60
    while head > 10 and tail > 10:
        candidate_lines = lines[:head] + ["", "... (truncated) ...", ""] + lines[-tail:]
        candidate = "\n".join(candidate_lines)
        if estimate_tokens(candidate) <= max_tokens:
            return candidate
        head = max(10, int(head * 0.8))
        tail = max(10, int(tail * 0.8))

    # Final fallback: only head.
    candidate = "\n".join(lines[: max(10, head)])
    return candidate


def reduce_python_source(source: str, *, max_tokens: int) -> ReducedFile:
    if estimate_tokens(source) <= max_tokens:
        return ReducedFile(content=source, estimated_tokens=estimate_tokens(source), was_reduced=False)

    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    outline_parts: list[str] = []
    outline_parts.append("[NOTE: File reduced to fit token budget. Showing outline of structure.]")

    try:
        tree = ast.parse(normalized)
    except Exception:
        snippet = _trim_to_tokens(normalized, max_tokens=max(0, max_tokens - 50))
        content = "\n".join(
            [
                "[NOTE: File reduced (parse failed). Showing head/tail excerpt.]",
                "",
                snippet,
            ]
        )
        content = _trim_to_tokens(content, max_tokens=max_tokens)
        return ReducedFile(content=content, estimated_tokens=estimate_tokens(content), was_reduced=True)

    # Imports first (cheap signal).
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None) or start
            if start is None:
                continue
            start = max(1, start)
            end = max(start, end or start)
            outline_parts.extend(lines[start - 1 : min(len(lines), end)])

    # Then top-level class/function signatures (+ docstring line if present).
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue

        start = getattr(node, "lineno", None)
        if start is None:
            continue
        decos = getattr(node, "decorator_list", []) or []
        for deco in decos:
            deco_line = getattr(deco, "lineno", None)
            if deco_line is not None:
                start = min(start, deco_line)

        start = max(1, start)
        # Capture signature lines until ':' is seen or 12 lines.
        signature_lines: list[str] = []
        for i in range(start - 1, min(len(lines), start - 1 + 12)):
            signature_lines.append(lines[i])
            if ":" in lines[i]:
                break
        outline_parts.extend(signature_lines)

        # Docstring (first statement) if present.
        try:
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
                doc = node.body[0].value.value
                if isinstance(doc, str):
                    doc_line = _first_nonempty_line(doc)
                    if doc_line:
                        outline_parts.append(f'""" {doc_line} """')
        except Exception:
            pass

    reduced = "\n".join(outline_parts)
    reduced = _trim_to_tokens(reduced, max_tokens=max_tokens)
    return ReducedFile(content=reduced, estimated_tokens=estimate_tokens(reduced), was_reduced=True)


def reduce_generic_text(source: str, *, max_tokens: int, file_path: str | None = None) -> ReducedFile:
    if estimate_tokens(source) <= max_tokens:
        return ReducedFile(content=source, estimated_tokens=estimate_tokens(source), was_reduced=False)

    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    header = "[NOTE: File reduced to fit token budget. Showing head/tail excerpt.]"
    if file_path:
        header = f"[NOTE: File reduced to fit token budget: {Path(file_path).name}]"
    trimmed = _trim_to_tokens("\n".join([header, "", normalized]), max_tokens=max_tokens)
    return ReducedFile(content=trimmed, estimated_tokens=estimate_tokens(trimmed), was_reduced=True)

