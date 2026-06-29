from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lean_agent.environment import EnvironmentReport, inspect_environment
from lean_agent.models import Finding, ProjectAnalysis


@dataclass
class BuildDiagnostic:
    severity: str
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditReport:
    root: str
    findings: list[Finding] = field(default_factory=list)
    environment: EnvironmentReport | None = None
    build_command: list[str] = field(default_factory=lambda: ["lake", "build"])
    build_status: str = "not_run"
    build_ran: bool = False
    build_exit_code: int | None = None
    build_stdout: str = ""
    build_stderr: str = ""
    build_diagnostics: list[BuildDiagnostic] = field(default_factory=list)

    def ok(self) -> bool:
        return self.build_exit_code in {None, 0} and not any(
            finding.severity in {"error", "warning"} for finding in self.findings
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "ok": self.ok(),
            "environment": self.environment.to_dict() if self.environment else None,
            "findings": [finding.to_dict() for finding in self.findings],
            "build": {
                "command": self.build_command,
                "status": self.build_status,
                "ran": self.build_ran,
                "exit_code": self.build_exit_code,
                "stdout": self.build_stdout,
                "stderr": self.build_stderr,
                "diagnostics": [diagnostic.to_dict() for diagnostic in self.build_diagnostics],
            },
        }


def audit_project(
    analysis: ProjectAnalysis,
    run_build: bool = False,
    timeout: int = 120,
) -> AuditReport:
    root = Path(analysis.root)
    report = AuditReport(root=str(root))
    report.environment = inspect_environment(root, timeout=min(timeout, 10))
    _check_project_files(root, report)
    _check_readme(root, report)
    if run_build:
        _run_lake_build(root, report, timeout)
    return report


def audit_to_markdown(report: AuditReport) -> str:
    lines: list[str] = []
    lines.append("# Lean Project Audit")
    lines.append("")
    lines.append(f"- Root: `{report.root}`")
    lines.append(f"- Status: {'OK' if report.ok() else 'Needs attention'}")
    lines.append(f"- Lake build: {report.build_status}")
    if report.build_exit_code is not None:
        lines.append(f"- Build exit code: {report.build_exit_code}")
    lines.append("")
    if report.environment:
        lines.extend(_environment_lines(report.environment))
        lines.append("")
    if report.findings:
        lines.append("## Findings")
        lines.append("")
        for finding in report.findings:
            location = f" at `{finding.location}`" if finding.location else ""
            lines.append(f"- **{finding.severity.upper()}**{location}: {finding.message}")
            if finding.suggestion:
                lines.append(f"  Suggestion: {finding.suggestion}")
        lines.append("")
    if report.build_status not in {"not_run", "ok"} and report.build_stderr:
        lines.append("## Build stderr")
        lines.append("")
        lines.append("```text")
        lines.append(report.build_stderr.strip()[-4000:])
        lines.append("```")
    if report.build_diagnostics:
        lines.append("")
        lines.append("## Build diagnostics")
        lines.append("")
        for diagnostic in report.build_diagnostics[:50]:
            location = ""
            if diagnostic.file:
                location = f" at `{diagnostic.file}`"
                if diagnostic.line is not None:
                    location += f":{diagnostic.line}"
                    if diagnostic.column is not None:
                        location += f":{diagnostic.column}"
            lines.append(f"- **{diagnostic.severity.upper()}**{location}: {diagnostic.message}")
    if not report.findings and report.build_status in {"not_run", "ok"} and not report.build_diagnostics:
        lines.append("No reproducibility issues found by the static audit.")
    return "\n".join(lines).rstrip() + "\n"


def audit_to_json(report: AuditReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


def _check_project_files(root: Path, report: AuditReport) -> None:
    if not (root / "lean-toolchain").exists():
        report.findings.append(
            Finding(
                severity="warning",
                message="Missing `lean-toolchain`.",
                suggestion="Commit `lean-toolchain` so readers can reproduce the exact Lean version.",
            )
        )
    if not ((root / "lakefile.lean").exists() or (root / "lakefile.toml").exists()):
        report.findings.append(
            Finding(
                severity="warning",
                message="Missing `lakefile.lean` or `lakefile.toml`.",
                suggestion="Add a Lake configuration or run this command on the actual Lean project root.",
            )
        )
    if not (root / "lake-manifest.json").exists():
        report.findings.append(
            Finding(
                severity="info",
                message="Missing `lake-manifest.json`.",
                suggestion="For Mathlib-based artifacts, commit the manifest used for the paper artifact.",
            )
        )


def _environment_lines(environment: EnvironmentReport) -> list[str]:
    lines: list[str] = []
    lines.append("## Environment")
    lines.append("")
    lines.append(f"- lean-toolchain: `{environment.lean_toolchain}`" if environment.lean_toolchain else "- lean-toolchain: not found")
    lines.append(f"- Lake file: `{environment.lakefile}`" if environment.lakefile else "- Lake file: not found")
    lines.append(f"- Lake manifest: `{environment.lake_manifest}`" if environment.lake_manifest else "- Lake manifest: not found")
    lines.append(f"- Git HEAD: `{environment.git_head}`" if environment.git_head else "- Git HEAD: unavailable")
    mathlib = [dependency for dependency in environment.dependencies if dependency.is_mathlib]
    lines.append(f"- Mathlib dependencies: {len(mathlib)}")
    for dependency in mathlib:
        details = dependency.input_rev or dependency.rev or dependency.url or dependency.source
        lines.append(f"  - `{dependency.name}`: {details}")
    for tool in environment.tools:
        version = f" - {tool.version}" if tool.version else ""
        lines.append(f"- `{tool.name}`: {tool.status}{version}")
    if environment.lake_env_lean:
        version = f" - {environment.lake_env_lean.version}" if environment.lake_env_lean.version else ""
        lines.append(f"- `lake env lean`: {environment.lake_env_lean.status}{version}")
    return lines


def _check_readme(root: Path, report: AuditReport) -> None:
    readme = _find_readme(root)
    if readme is None:
        report.findings.append(
            Finding(
                severity="warning",
                message="Missing README.",
                suggestion="Add artifact instructions with Lean version, build command, expected output, and theorem map.",
            )
        )
        return
    text = readme.read_text(encoding="utf-8", errors="replace").lower()
    required_terms = {
        "lean version or toolchain": ["lean-toolchain", "lean version", "lean4", "elan"],
        "build instructions": ["lake build", "build"],
        "reproducibility or artifact note": ["artifact", "reproduc", "camera-ready"],
        "commit hash": ["commit", "hash", "revision"],
    }
    for label, terms in required_terms.items():
        if not any(term in text for term in terms):
            report.findings.append(
                Finding(
                    severity="info",
                    message=f"README may be missing {label}.",
                    location=str(readme.name),
                    suggestion="Add a short reproducibility section for paper reviewers and artifact evaluators.",
                )
            )


def _find_readme(root: Path) -> Path | None:
    for name in ("README.md", "README.rst", "README.txt", "Readme.md"):
        path = root / name
        if path.exists():
            return path
    return None


def _run_lake_build(root: Path, report: AuditReport, timeout: int) -> None:
    report.build_status = "starting"
    if not ((root / "lakefile.lean").exists() or (root / "lakefile.toml").exists()):
        report.build_status = "skipped"
        report.build_exit_code = 2
        report.build_stderr = "No `lakefile.lean` or `lakefile.toml` was found in the project root."
        report.findings.append(
            Finding(
                severity="error",
                message="Cannot run `lake build` without a Lake project file.",
                suggestion="Run this command on the Lean project root or add `lakefile.lean`/`lakefile.toml`.",
            )
        )
        return
    if shutil.which("lake") is None:
        report.build_status = "missing_lake"
        report.build_exit_code = 127
        report.build_stderr = "`lake` executable was not found on PATH."
        report.findings.append(
            Finding(
                severity="error",
                message="Cannot run `lake build` because `lake` is not installed or not on PATH.",
                suggestion="Install Lean via elan, then rerun the audit with `--run-build`.",
            )
        )
        return

    report.build_ran = True
    try:
        result = subprocess.run(
            report.build_command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        report.build_status = "missing_lake"
        report.build_ran = False
        report.build_exit_code = 127
        report.build_stderr = "`lake` executable was not found on PATH."
        report.findings.append(
            Finding(
                severity="error",
                message="Cannot run `lake build` because `lake` is not installed or not on PATH.",
                suggestion="Install Lean via elan, then rerun the audit with `--run-build`.",
            )
        )
        return
    except subprocess.TimeoutExpired as exc:
        report.build_status = "timeout"
        report.build_exit_code = 124
        report.build_stdout = exc.stdout or ""
        report.build_stderr = exc.stderr or ""
        report.build_diagnostics = _parse_build_diagnostics(report.build_stdout, report.build_stderr)
        report.findings.append(
            Finding(
                severity="error",
                message=f"`lake build` timed out after {timeout} seconds.",
                suggestion="Increase `--timeout` or inspect whether dependency downloads/builds are still running.",
            )
        )
        return
    report.build_status = "ok" if result.returncode == 0 else "failed"
    report.build_exit_code = result.returncode
    report.build_stdout = result.stdout
    report.build_stderr = result.stderr
    report.build_diagnostics = _parse_build_diagnostics(result.stdout, result.stderr)
    if result.returncode != 0:
        report.findings.append(
            Finding(
                severity="error",
                message="`lake build` failed.",
                suggestion="Inspect build stderr and fix the first Lean error before rerunning.",
            )
        )


LOCATION_DIAGNOSTIC_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+):\s+"
    r"(?P<severity>error|warning|info):\s+(?P<message>.+)$"
)
LINE_DIAGNOSTIC_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):\s+"
    r"(?P<severity>error|warning|info):\s+(?P<message>.+)$"
)
GLOBAL_DIAGNOSTIC_RE = re.compile(
    r"^(?P<severity>error|warning|info):\s+(?P<message>.+)$"
)


def _parse_build_diagnostics(stdout: str, stderr: str) -> list[BuildDiagnostic]:
    diagnostics: list[BuildDiagnostic] = []
    for raw_line in (stdout + "\n" + stderr).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        diagnostic = _parse_diagnostic_line(line)
        if diagnostic:
            diagnostics.append(diagnostic)
    return diagnostics


def _parse_diagnostic_line(line: str) -> BuildDiagnostic | None:
    match = LOCATION_DIAGNOSTIC_RE.match(line)
    if match:
        return BuildDiagnostic(
            severity=match.group("severity"),
            message=match.group("message"),
            file=match.group("file"),
            line=int(match.group("line")),
            column=int(match.group("column")),
            raw=line,
        )
    match = LINE_DIAGNOSTIC_RE.match(line)
    if match:
        return BuildDiagnostic(
            severity=match.group("severity"),
            message=match.group("message"),
            file=match.group("file"),
            line=int(match.group("line")),
            raw=line,
        )
    match = GLOBAL_DIAGNOSTIC_RE.match(line)
    if match:
        return BuildDiagnostic(
            severity=match.group("severity"),
            message=match.group("message"),
            raw=line,
        )
    return None
