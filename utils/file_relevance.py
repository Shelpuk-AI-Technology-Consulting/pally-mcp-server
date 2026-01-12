"""
Deterministic file relevance scoring for review-oriented tools.

The goal is to prioritize "most useful" files under token budgets for code review and
system design review, without relying on additional LLM calls.
"""

from __future__ import annotations

import os
import re
import ast
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from utils.file_types import get_file_category


@dataclass(frozen=True)
class FileRankingContext:
    prompt: str
    explicit_paths: set[str]
    project_root: str | None
    recency_order: dict[str, int] | None = None
    include_dependencies: bool = True
    dependency_depth: int = 1
    max_dependency_files: int = 200


_PATHLIKE_RE = re.compile(r"(?P<path>(?:[A-Za-z]:)?[\\w./\\\\-]+\\.[A-Za-z0-9_]{1,8})")
_LOCKFILE_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pdm.lock",
    "pipfile.lock",
    "composer.lock",
    "cargo.lock",
    "go.sum",
}


def infer_project_root(paths: Iterable[str]) -> str | None:
    existing: list[str] = []
    for path in paths:
        try:
            p = Path(path)
        except Exception:
            continue
        if p.exists():
            existing.append(str(p))
    if not existing:
        return None
    try:
        return os.path.commonpath(existing)
    except Exception:
        return None


def extract_path_mentions(prompt: str) -> set[str]:
    if not prompt:
        return set()
    mentions = set()
    for match in _PATHLIKE_RE.finditer(prompt):
        mentions.add(match.group("path"))
    return mentions


@lru_cache(maxsize=8_192)
def file_type_weight(file_path: str) -> float:
    name = Path(file_path).name.lower()
    if name in _LOCKFILE_NAMES or name.endswith(".lock"):
        return 0.05
    if name.endswith(".min.js") or name.endswith(".min.css"):
        return 0.10

    category = get_file_category(file_path)
    if category == "programming":
        return 1.0
    if category == "scripts":
        return 0.9
    if category == "web":
        return 0.7
    if category == "configs":
        return 0.6
    if category == "docs":
        return 0.4
    if category == "text_data":
        return 0.2
    return 0.3


def _normalize_path_set(paths: Iterable[str]) -> set[str]:
    normalized = set()
    for path in paths:
        try:
            normalized.add(str(Path(path).resolve()))
        except Exception:
            normalized.add(path)
    return normalized


def rank_files(files: list[str], *, ctx: FileRankingContext) -> list[str]:
    """
    Rank files in descending order of relevance for review tasks.

    Scoring is deterministic and combines:
    - explicit path mentions
    - file type weighting (source > docs > lock)
    - optional recency ordering (lower index == more recent)
    """

    explicit = _normalize_path_set(ctx.explicit_paths)
    mentioned_tokens = extract_path_mentions(ctx.prompt)

    # Map mention tokens to actual files by suffix/basename match.
    mention_hits: set[str] = set()
    if mentioned_tokens:
        for file_path in files:
            resolved = str(Path(file_path).resolve())
            basename = Path(resolved).name
            for token in mentioned_tokens:
                if token == basename:
                    mention_hits.add(resolved)
                    break
                if ("/" in token or "\\" in token) and resolved.endswith(token):
                    mention_hits.add(resolved)
                    break

    recency = ctx.recency_order or {}

    scored: list[tuple[float, str]] = []
    for file_path in files:
        resolved = str(Path(file_path).resolve())
        score = 0.0

        if resolved in explicit:
            score += 10_000.0
        if resolved in mention_hits:
            score += 15_000.0

        score += 1_000.0 * file_type_weight(resolved)

        if resolved in recency:
            # Newer == larger bonus; keep bounded.
            score += max(0.0, 250.0 - float(recency[resolved]) * 2.0)

        scored.append((score, resolved))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [path for _score, path in scored]


def collect_python_dependencies(*, seed_files: Iterable[str], project_root: str | None, max_files: int) -> set[str]:
    """
    Best-effort local dependency closure for Python files (depth=1).

    Only resolves imports to files that exist under project_root.
    """

    if not project_root:
        return set()

    root = Path(project_root)
    resolved: set[str] = set()
    queue: list[Path] = []

    for path in seed_files:
        try:
            p = Path(path)
        except Exception:
            continue
        if p.is_file() and p.suffix.lower() == ".py":
            queue.append(p)

    def _resolve_module(module: str) -> set[Path]:
        candidates: set[Path] = set()
        if not module:
            return candidates
        rel = Path(*module.split("."))
        candidates.add(root / (str(rel) + ".py"))
        candidates.add(root / rel / "__init__.py")
        return candidates

    for seed in queue:
        if len(resolved) >= max_files:
            break
        try:
            text = seed.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text)
        except Exception:
            continue

        for node in ast.walk(tree):
            if len(resolved) >= max_files:
                break
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for candidate in _resolve_module(alias.name):
                        if candidate.is_file():
                            resolved.add(str(candidate.resolve()))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level and node.level > 0:
                    # Resolve relative to seed's directory.
                    base = seed.parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    rel = Path(*module.split(".")) if module else Path()
                    candidates = {base / (str(rel) + ".py"), base / rel / "__init__.py"}
                    # Handle "from . import foo" (module == ""). Include imported names as modules.
                    if not module:
                        for alias in node.names:
                            name_rel = Path(alias.name)
                            candidates.add(base / (str(name_rel) + ".py"))
                            candidates.add(base / name_rel / "__init__.py")
                    for candidate in candidates:
                        if candidate.is_file():
                            resolved.add(str(candidate.resolve()))
                else:
                    for candidate in _resolve_module(module):
                        if candidate.is_file():
                            resolved.add(str(candidate.resolve()))

    return resolved
