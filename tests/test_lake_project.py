from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from lean_agent.lake_project import detect_lake_dependencies, mathlib_dependencies


class LakeProjectTests(unittest.TestCase):
    def test_detects_mathlib_from_manifest_and_lakefiles(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lake-manifest.json").write_text(
                json.dumps(
                    {
                        "packages": [
                            {
                                "name": "mathlib",
                                "type": "git",
                                "url": "https://github.com/leanprover-community/mathlib4.git",
                                "rev": "manifest-rev",
                                "inputRev": "v4.10.0",
                            },
                            {"name": "batteries", "type": "git", "url": "https://example.test/batteries"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "lakefile.lean").write_text(
                'require mathlib from git "https://github.com/leanprover-community/mathlib4.git" @ "v4.10.0"\n',
                encoding="utf-8",
            )
            (root / "lakefile.toml").write_text(
                """
[[require]]
name = "Cli"
git = "https://github.com/leanprover/lean4-cli"
rev = "main"
""".lstrip(),
                encoding="utf-8",
            )

            dependencies = detect_lake_dependencies(root)
            mathlib = mathlib_dependencies(root)

        self.assertEqual([dependency.name for dependency in dependencies], ["batteries", "Cli", "mathlib"])
        self.assertEqual(len(mathlib), 1)
        self.assertEqual(mathlib[0].name, "mathlib")
        self.assertEqual(mathlib[0].input_rev, "v4.10.0")
        self.assertIn("lake-manifest.json", mathlib[0].source)
        self.assertIn("lakefile.lean", mathlib[0].source)


if __name__ == "__main__":
    unittest.main()
