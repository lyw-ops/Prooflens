from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lean_agent.lake_project import LakeDependency, detect_lake_dependencies


@dataclass
class CommandReport:
    name: str
    command: list[str]
    status: str
    path: str | None = None
    exit_code: int | None = None
    version: str | None = None
    stdout: str = ""
    stderr: str = ""
    message: str | None = None

    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EnvironmentReport:
    root: str
    lean_toolchain: str | None = None
    lakefile: str | None = None
    lake_manifest: str | None = None
    git_head: str | None = None
    dependencies: list[LakeDependency] = field(default_factory=list)
    tools: list[CommandReport] = field(default_factory=list)
    lake_env_lean: CommandReport | None = None

    def tool(self, name: str) -> CommandReport | None:
        for item in self.tools:
            if item.name == name:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "lean_toolchain": self.lean_toolchain,
            "lakefile": self.lakefile,
            "lake_manifest": self.lake_manifest,
            "git_head": self.git_head,
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
            "mathlib_dependencies": [
                dependency.to_dict()
                for dependency in self.dependencies
                if dependency.is_mathlib
            ],
            "tools": [tool.to_dict() for tool in self.tools],
            "lake_env_lean": self.lake_env_lean.to_dict() if self.lake_env_lean else None,
        }


def inspect_environment(root: str | Path = ".", timeout: int = 10) -> EnvironmentReport:
    root_path = Path(root).resolve()
    report = EnvironmentReport(root=str(root_path))
    report.lean_toolchain = _read_optional_file(root_path / "lean-toolchain")
    report.lakefile = _first_existing_name(root_path, ("lakefile.lean", "lakefile.toml"))
    report.lake_manifest = _first_existing_name(root_path, ("lake-manifest.json",))
    report.dependencies = detect_lake_dependencies(root_path)
    report.tools = [
        _probe_command("lean", ["lean", "--version"], root_path, timeout),
        _probe_command("lake", ["lake", "--version"], root_path, timeout),
        _probe_command("elan", ["elan", "--version"], root_path, timeout),
        _probe_command("git", ["git", "--version"], root_path, timeout),
    ]
    report.git_head = _git_head(root_path, timeout)
    report.lake_env_lean = _probe_lake_env_lean(report, root_path, timeout)
    return report


def environment_to_markdown(report: EnvironmentReport) -> str:
    lines: list[str] = []
    lines.append("# Lean Environment")
    lines.append("")
    lines.append(f"- Root: `{report.root}`")
    lines.append(f"- lean-toolchain: `{report.lean_toolchain}`" if report.lean_toolchain else "- lean-toolchain: not found")
    lines.append(f"- Lake file: `{report.lakefile}`" if report.lakefile else "- Lake file: not found")
    lines.append(f"- Lake manifest: `{report.lake_manifest}`" if report.lake_manifest else "- Lake manifest: not found")
    lines.append(f"- Git HEAD: `{report.git_head}`" if report.git_head else "- Git HEAD: unavailable")
    mathlib = [dependency for dependency in report.dependencies if dependency.is_mathlib]
    lines.append(f"- Mathlib dependencies: {len(mathlib)}")
    lines.append("")
    if report.dependencies:
        lines.append("## Lake Dependencies")
        lines.append("")
        for dependency in report.dependencies:
            details = []
            if dependency.url:
                details.append(dependency.url)
            if dependency.input_rev or dependency.rev:
                details.append(dependency.input_rev or dependency.rev or "")
            suffix = f" ({', '.join(details)})" if details else ""
            lines.append(f"- `{dependency.name}` from {dependency.source}{suffix}")
        lines.append("")
    lines.append("## Tools")
    lines.append("")
    for tool in report.tools:
        version = f" - {tool.version}" if tool.version else ""
        path = f" (`{tool.path}`)" if tool.path else ""
        lines.append(f"- `{tool.name}`: {tool.status}{path}{version}")
        if tool.message:
            lines.append(f"  Message: {tool.message}")
    if report.lake_env_lean:
        lines.append("")
        lines.append("## Lake Environment")
        lines.append("")
        tool = report.lake_env_lean
        version = f" - {tool.version}" if tool.version else ""
        lines.append(f"- `lake env lean --version`: {tool.status}{version}")
        if tool.message:
            lines.append(f"  Message: {tool.message}")
    return "\n".join(lines).rstrip() + "\n"


def environment_to_json(report: EnvironmentReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


def _probe_command(
    name: str,
    command: list[str],
    root: Path,
    timeout: int,
) -> CommandReport:
    executable = shutil.which(command[0])
    if executable is None:
        return CommandReport(
            name=name,
            command=command,
            status="missing",
            message=f"`{command[0]}` was not found on PATH.",
        )
    result = _run_command(command, root, timeout)
    result.name = name
    result.path = executable
    return result


def _probe_lake_env_lean(
    report: EnvironmentReport,
    root: Path,
    timeout: int,
) -> CommandReport:
    if not report.lakefile:
        return CommandReport(
            name="lake env lean",
            command=["lake", "env", "lean", "--version"],
            status="skipped",
            message="No lakefile was found in the project root.",
        )
    lake = report.tool("lake")
    if lake is None or not lake.ok():
        return CommandReport(
            name="lake env lean",
            command=["lake", "env", "lean", "--version"],
            status="skipped",
            message="Lake is not available, so `lake env lean --version` was not run.",
        )
    return _run_command(["lake", "env", "lean", "--version"], root, timeout, name="lake env lean")


def _run_command(
    command: list[str],
    root: Path,
    timeout: int,
    name: str = "",
) -> CommandReport:
    try:
        result = subprocess.run(
            command,
            cwd=root if root.exists() and root.is_dir() else None,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return CommandReport(
            name=name or command[0],
            command=command,
            status="missing",
            message=f"`{command[0]}` was not found on PATH.",
        )
    except subprocess.TimeoutExpired as exc:
        return CommandReport(
            name=name or command[0],
            command=command,
            status="timeout",
            exit_code=124,
            stdout=_safe_text(exc.stdout),
            stderr=_safe_text(exc.stderr),
            message=f"Command timed out after {timeout} seconds.",
        )
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    status = "ok" if result.returncode == 0 else "failed"
    return CommandReport(
        name=name or command[0],
        command=command,
        status=status,
        exit_code=result.returncode,
        version=_first_output_line(stdout, stderr),
        stdout=stdout,
        stderr=stderr,
        message=None if result.returncode == 0 else _first_output_line(stderr, stdout),
    )


def _git_head(root: Path, timeout: int) -> str | None:
    if shutil.which("git") is None:
        return None
    result = _run_command(["git", "rev-parse", "HEAD"], root, timeout, name="git rev-parse")
    if result.status != "ok":
        return None
    head = result.stdout.strip()
    return head or None


def _read_optional_file(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text or None


def _first_existing_name(root: Path, names: tuple[str, ...]) -> str | None:
    for name in names:
        if (root / name).exists():
            return name
    return None


def _first_output_line(primary: str, fallback: str = "") -> str | None:
    text = primary.strip() or fallback.strip()
    if not text:
        return None
    return text.splitlines()[0]


def _safe_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
