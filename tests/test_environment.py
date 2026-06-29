from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest

from lean_agent.audit import audit_project
from lean_agent.environment import inspect_environment
from lean_agent.project import scan_project


class EnvironmentTests(unittest.TestCase):
    def test_detects_lean_lake_and_project_environment(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_project_files(root)
            bin_dir = root / "bin"
            _write_fake_tools(bin_dir)
            with _path_prepend(bin_dir):
                report = inspect_environment(root, timeout=5)

        self.assertEqual(report.lean_toolchain, "leanprover/lean4:v4.8.0")
        self.assertEqual(report.lakefile, "lakefile.lean")
        self.assertEqual(report.lake_manifest, "lake-manifest.json")
        self.assertEqual(len(report.dependencies), 1)
        self.assertTrue(report.dependencies[0].is_mathlib)
        self.assertEqual(report.dependencies[0].input_rev, "v4.8.0")
        self.assertEqual(report.git_head, "0123456789abcdef0123456789abcdef01234567")
        self.assertEqual(report.tool("lean").status, "ok")
        self.assertEqual(report.tool("lake").status, "ok")
        self.assertEqual(report.tool("elan").status, "ok")
        self.assertEqual(report.lake_env_lean.status, "ok")
        self.assertEqual(report.lake_env_lean.version, "Lean (version 4.8.0)")

    def test_audit_records_successful_lake_build(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_project_files(root)
            bin_dir = root / "bin"
            _write_fake_tools(bin_dir)
            with _path_prepend(bin_dir):
                analysis = scan_project(root)
                report = audit_project(analysis, run_build=True, timeout=5)

        self.assertTrue(report.ok())
        self.assertEqual(report.build_status, "ok")
        self.assertEqual(report.build_exit_code, 0)
        self.assertIn("Build completed successfully", report.build_stdout)
        self.assertIsNotNone(report.environment)
        self.assertEqual(report.environment.tool("lake").status, "ok")
        self.assertEqual(report.environment.dependencies[0].name, "mathlib")

    def test_audit_parses_lake_build_diagnostics(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_project_files(root)
            bin_dir = root / "bin"
            _write_fake_tools(bin_dir)
            _write_failing_lake(bin_dir)
            with _path_prepend(bin_dir):
                analysis = scan_project(root)
                report = audit_project(analysis, run_build=True, timeout=5)

        self.assertFalse(report.ok())
        self.assertEqual(report.build_status, "failed")
        self.assertEqual(report.build_exit_code, 1)
        self.assertEqual(len(report.build_diagnostics), 2)
        first = report.build_diagnostics[0]
        self.assertEqual(first.severity, "error")
        self.assertEqual(first.file, "Main.lean")
        self.assertEqual(first.line, 3)
        self.assertEqual(first.column, 8)
        self.assertIn("unknown identifier", first.message)


def _write_project_files(root: Path) -> None:
    (root / "Main.lean").write_text(
        "theorem ok (n : Nat) : n = n := by\n  rfl\n",
        encoding="utf-8",
    )
    (root / "lean-toolchain").write_text("leanprover/lean4:v4.8.0\n", encoding="utf-8")
    (root / "lakefile.lean").write_text("import Lake\n", encoding="utf-8")
    (root / "lake-manifest.json").write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "name": "mathlib",
                        "type": "git",
                        "url": "https://github.com/leanprover-community/mathlib4.git",
                        "rev": "0123456789abcdef0123456789abcdef01234567",
                        "inputRev": "v4.8.0",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "Use lean-toolchain. Run lake build. This artifact is reproducible. Commit hash recorded.\n",
        encoding="utf-8",
    )


def _write_fake_tools(bin_dir: Path) -> None:
    bin_dir.mkdir()
    _write_tool(
        bin_dir,
        "lean",
        """
if [ "$1" = "--version" ]; then
  echo "Lean (version 4.8.0)"
  exit 0
fi
echo "unexpected lean command" >&2
exit 2
""",
    )
    _write_tool(
        bin_dir,
        "lake",
        """
if [ "$1" = "--version" ]; then
  echo "Lake version 5.0.0"
  exit 0
fi
if [ "$1" = "env" ]; then
  shift
  "$@"
  exit $?
fi
if [ "$1" = "build" ]; then
  echo "Build completed successfully"
  exit 0
fi
echo "unexpected lake command" >&2
exit 2
""",
    )
    _write_tool(
        bin_dir,
        "elan",
        """
if [ "$1" = "--version" ]; then
  echo "elan 4.1.0"
  exit 0
fi
echo "unexpected elan command" >&2
exit 2
""",
    )
    _write_tool(
        bin_dir,
        "git",
        """
if [ "$1" = "--version" ]; then
  echo "git version 2.40.0"
  exit 0
fi
if [ "$1" = "rev-parse" ] && [ "$2" = "HEAD" ]; then
  echo "0123456789abcdef0123456789abcdef01234567"
  exit 0
fi
echo "unexpected git command" >&2
exit 2
""",
    )


def _write_failing_lake(bin_dir: Path) -> None:
    _write_tool(
        bin_dir,
        "lake",
        """
if [ "$1" = "--version" ]; then
  echo "Lake version 5.0.0"
  exit 0
fi
if [ "$1" = "env" ]; then
  shift
  "$@"
  exit $?
fi
if [ "$1" = "build" ]; then
  echo "Main.lean:3:8: error: unknown identifier 'bad'"
  echo "warning: build completed with warnings" >&2
  exit 1
fi
echo "unexpected lake command" >&2
exit 2
""",
    )


def _write_tool(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + body.lstrip(), encoding="utf-8")
    path.chmod(0o755)


class _path_prepend:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.original = ""

    def __enter__(self) -> None:
        self.original = os.environ.get("PATH", "")
        os.environ["PATH"] = str(self.path) + os.pathsep + self.original

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        os.environ["PATH"] = self.original


if __name__ == "__main__":
    unittest.main()
