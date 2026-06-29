from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from lean_agent.models import LeanDeclaration


@dataclass(frozen=True)
class SymbolResolution:
    query: str
    matches: tuple[LeanDeclaration, ...]

    @property
    def resolved(self) -> LeanDeclaration | None:
        return self.matches[0] if len(self.matches) == 1 else None

    @property
    def ambiguous(self) -> bool:
        return len(self.matches) > 1


class DeclarationIndex:
    def __init__(self, declarations: Iterable[LeanDeclaration]):
        self.declarations = list(declarations)
        self.by_name: dict[str, list[LeanDeclaration]] = defaultdict(list)
        self.by_short_name: dict[str, list[LeanDeclaration]] = defaultdict(list)
        self.by_suffix: dict[str, list[LeanDeclaration]] = defaultdict(list)
        self.by_file: dict[str, list[LeanDeclaration]] = defaultdict(list)
        for declaration in self.declarations:
            self.by_name[declaration.name].append(declaration)
            self.by_short_name[declaration.short_name].append(declaration)
            self.by_file[declaration.file].append(declaration)
            for suffix in _name_suffixes(declaration.name):
                self.by_suffix[suffix].append(declaration)

    def resolve(self, symbol: str) -> LeanDeclaration | None:
        return self.lookup(symbol).resolved

    def resolve_first(self, symbol: str) -> LeanDeclaration | None:
        matches = self.lookup(symbol).matches
        return matches[0] if matches else None

    def lookup(self, symbol: str) -> SymbolResolution:
        normalized = symbol.strip()
        if not normalized:
            return SymbolResolution(query=symbol, matches=())
        if normalized in self.by_name:
            return SymbolResolution(query=symbol, matches=_sorted_unique(self.by_name[normalized]))
        if normalized in self.by_short_name:
            return SymbolResolution(query=symbol, matches=_sorted_unique(self.by_short_name[normalized]))
        if normalized in self.by_suffix:
            return SymbolResolution(query=symbol, matches=_sorted_unique(self.by_suffix[normalized]))
        suffix_matches = [
            declaration
            for declaration in self.declarations
            if declaration.name.endswith("." + normalized)
        ]
        return SymbolResolution(query=symbol, matches=_sorted_unique(suffix_matches))

    def names_for_token(self, token: str) -> list[str]:
        if token in self.by_name:
            return sorted({declaration.name for declaration in self.by_name[token]})
        if "." in token and token in self.by_suffix:
            return sorted({declaration.name for declaration in self.by_suffix[token]})
        if token in self.by_short_name:
            return sorted({declaration.name for declaration in self.by_short_name[token]})
        return []

    def compatible_declaration_map(self) -> dict[str, LeanDeclaration]:
        result: dict[str, LeanDeclaration] = {}
        for declaration in self.declarations:
            result.setdefault(declaration.name, declaration)
            result.setdefault(declaration.short_name, declaration)
        return result

    def ambiguous_symbols(self) -> dict[str, list[str]]:
        symbols: dict[str, list[str]] = {}
        for name, declarations in self.by_short_name.items():
            unique_names = sorted({declaration.name for declaration in declarations})
            if len(unique_names) > 1:
                symbols[name] = unique_names
        return symbols

    def to_dict(self) -> dict[str, Any]:
        return {
            "declarations": len(self.declarations),
            "files": len(self.by_file),
            "short_names": len(self.by_short_name),
            "ambiguous_symbols": self.ambiguous_symbols(),
        }


def _name_suffixes(name: str) -> list[str]:
    parts = [part for part in name.split(".") if part]
    return [".".join(parts[index:]) for index in range(len(parts))]


def _sorted_unique(declarations: Iterable[LeanDeclaration]) -> tuple[LeanDeclaration, ...]:
    by_name: dict[str, LeanDeclaration] = {}
    for declaration in declarations:
        by_name.setdefault(declaration.name, declaration)
    return tuple(sorted(by_name.values(), key=lambda item: (item.file, item.line, item.name)))
