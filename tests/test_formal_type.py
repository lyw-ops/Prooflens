import unittest

from lean_agent.formal_type import decompose_formal_type


class FormalTypeTests(unittest.TestCase):
    def test_decomposes_semantic_forall_type(self) -> None:
        formal = decompose_formal_type("forall (n : Nat) (h : n = n), Eq.{1} Nat n n")

        self.assertEqual([parameter.names for parameter in formal.parameters], [["n"], ["h"]])
        self.assertEqual([parameter.role for parameter in formal.parameters], ["parameter", "assumption"])
        self.assertEqual(formal.conclusion, "Eq.{1} Nat n n")
        self.assertEqual([parameter.type for parameter in formal.assumptions], ["n = n"])

    def test_decomposes_static_theorem_statement(self) -> None:
        formal = decompose_formal_type("theorem ok (n : Nat) (h : n = n) : n = n")

        self.assertEqual([parameter.names for parameter in formal.parameters], [["n"], ["h"]])
        self.assertEqual([parameter.role for parameter in formal.parameters], ["parameter", "assumption"])
        self.assertEqual(formal.conclusion, "n = n")

    def test_plain_semantic_type_is_conclusion(self) -> None:
        formal = decompose_formal_type("Nat -> Nat")

        self.assertEqual(formal.parameters, [])
        self.assertEqual(formal.conclusion, "Nat -> Nat")


if __name__ == "__main__":
    unittest.main()
