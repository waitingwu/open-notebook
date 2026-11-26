"""Repo KB configuration (YAML)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

import yaml  # type: ignore[import-untyped]

from open_notebook.repo_kb.policy import PathRules


@dataclass
class RepoConfig:
    name: str
    path: str
    role: str  # "doc" | "src"
    rules: PathRules = field(default_factory=PathRules)


@dataclass
class KBConfig:
    data_dir: str
    repos: List[RepoConfig]

    def repo(self, name: str) -> RepoConfig:
        for r in self.repos:
            if r.name == name:
                return r
        raise KeyError(f"unknown repo: {name}")


def load_config(path: str) -> KBConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    base = os.path.dirname(os.path.abspath(path))

    def expand(p: str) -> str:
        p = os.path.expanduser(p)
        return p if os.path.isabs(p) else os.path.join(base, p)

    repos = [
        RepoConfig(
            name=r["name"],
            path=expand(r["path"]),
            role=r.get("role", "doc"),
            rules=PathRules(
                include=r.get("include") or ["*"], exclude=r.get("exclude") or []
            ),
        )
        for r in raw["repos"]
    ]
    return KBConfig(data_dir=expand(raw.get("data_dir", "kb-data")), repos=repos)
