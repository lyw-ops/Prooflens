from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class LakeDependency:
    name: str
    source: str
    kind: str | None = None
    url: str | None = None
    rev: str | None = None
    input_rev: str | None = None
    scope: str | None = None

    @property
    def is_mathlib(self) -> bool:
        return self.name.lower() == "mathlib" or "mathlib" in (self.url or "").lower()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_lake_dependencies(root: str | Path) -> list[LakeDependency]:
    root_path = Path(root)
    dependencies: list[LakeDependency] = []
    dependencies.extend(_dependencies_from_manifest(root_path / "lake-manifest.json"))
    dependencies.extend(_dependencies_from_lakefile_lean(root_path / "lakefile.lean"))
    dependencies.extend(_dependencies_from_lakefile_toml(root_path / "lakefile.toml"))
    return _dedupe_dependencies(dependencies)


def mathlib_dependencies(root: str | Path) -> list[LakeDependency]:
    return [
        dependency
        for dependency in detect_lake_dependencies(root)
        if dependency.is_mathlib
    ]


def _dependencies_from_manifest(path: Path) -> list[LakeDependency]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    dependencies: list[LakeDependency] = []
    for package in _manifest_packages(data):
        if not isinstance(package, dict):
            continue
        name = _string_or_none(package.get("name"))
        if not name:
            continue
        dependencies.append(
            LakeDependency(
                name=name,
                source="lake-manifest.json",
                kind=_string_or_none(package.get("type")),
                url=_string_or_none(package.get("url")),
                rev=_string_or_none(package.get("rev")),
                input_rev=_string_or_none(package.get("inputRev") or package.get("input_rev")),
                scope=_string_or_none(package.get("scope")),
            )
        )
    return dependencies


def _manifest_packages(data: Any) -> list[Any]:
    if isinstance(data, dict):
        packages = data.get("packages")
        if isinstance(packages, list):
            return packages
        package_entries = data.get("packageEntries")
        if isinstance(package_entries, list):
            return package_entries
    return []


def _dependencies_from_lakefile_lean(path: Path) -> list[LakeDependency]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    dependencies: list[LakeDependency] = []
    require_re = re.compile(
        r"require\s+(?P<name>[A-Za-z0-9_'.-]+)"
        r"(?:\s+from\s+(?P<kind>git|Git|path|Path)\s+\"(?P<url>[^\"]+)\")?"
        r"(?:\s*@\s+\"(?P<rev>[^\"]+)\")?",
        flags=re.MULTILINE,
    )
    for match in require_re.finditer(text):
        dependencies.append(
            LakeDependency(
                name=match.group("name"),
                source="lakefile.lean",
                kind=_normalize_kind(match.group("kind")),
                url=match.group("url"),
                input_rev=match.group("rev"),
            )
        )
    return dependencies


def _dependencies_from_lakefile_toml(path: Path) -> list[LakeDependency]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    dependencies: list[LakeDependency] = []
    for block in _toml_require_blocks(text):
        name = _toml_string(block, "name")
        if not name:
            continue
        dependencies.append(
            LakeDependency(
                name=name,
                source="lakefile.toml",
                kind="git" if _toml_string(block, "git") else None,
                url=_toml_string(block, "git") or _toml_string(block, "path"),
                rev=_toml_string(block, "rev"),
                input_rev=_toml_string(block, "rev"),
            )
        )
    return dependencies


def _toml_require_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    in_require = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[["):
            if in_require and current:
                blocks.append("\n".join(current))
            in_require = stripped == "[[require]]"
            current = [line] if in_require else []
            continue
        if in_require:
            current.append(line)
    if in_require and current:
        blocks.append("\n".join(current))
    return blocks


def _toml_string(block: str, key: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*\"([^\"]+)\"", block, flags=re.MULTILINE)
    return match.group(1) if match else None


def _dedupe_dependencies(dependencies: list[LakeDependency]) -> list[LakeDependency]:
    merged: dict[str, LakeDependency] = {}
    for dependency in dependencies:
        key = dependency.name.lower()
        existing = merged.get(key)
        if existing is None:
            merged[key] = dependency
            continue
        existing.kind = existing.kind or dependency.kind
        existing.url = existing.url or dependency.url
        existing.rev = existing.rev or dependency.rev
        existing.input_rev = existing.input_rev or dependency.input_rev
        existing.scope = existing.scope or dependency.scope
        if dependency.source not in existing.source.split(", "):
            existing.source += ", " + dependency.source
    return sorted(merged.values(), key=lambda item: item.name.lower())


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _normalize_kind(value: str | None) -> str | None:
    return value.lower() if value else None
