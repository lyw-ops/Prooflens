from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lean_agent.project import find_lean_files, scan_project


class ProjectScanTests(unittest.TestCase):
    def test_rejects_missing_path(self) -> None:
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"

            with self.assertRaises(FileNotFoundError):
                scan_project(missing)

    def test_rejects_non_lean_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.tex"
            path.write_text(r"\lean{Demo.ok}", encoding="utf-8")

            with self.assertRaises(ValueError):
                scan_project(path)

    def test_rejects_directory_without_lean_files(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Empty artifact\n", encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                scan_project(root)

    def test_ignores_generated_directories_relative_to_scan_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Main.lean").write_text(
                "theorem ok (n : Nat) : n = n := by\n  rfl\n",
                encoding="utf-8",
            )
            generated = root / ".lake" / "packages" / "Ghost.lean"
            generated.parent.mkdir(parents=True)
            generated.write_text("theorem ghost : True := by\n  trivial\n", encoding="utf-8")

            files = find_lean_files(root)

        self.assertEqual([path.name for path in files], ["Main.lean"])

    def test_ignores_lakefile_as_project_source(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lakefile.lean").write_text("import Lake\n", encoding="utf-8")
            (root / "Main.lean").write_text("theorem ok : True := by\n  trivial\n", encoding="utf-8")

            files = find_lean_files(root)

        self.assertEqual([path.name for path in files], ["Main.lean"])


if __name__ == "__main__":
    unittest.main()
