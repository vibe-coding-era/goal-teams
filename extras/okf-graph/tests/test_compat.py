"""Python 3.9 compatibility guard and the public API surface."""

from __future__ import annotations

import ast
import io
import tokenize
import unittest

import okf_graph
from tests.helpers import EXTRA_ROOT


NEWER_IMPORTS = {
    "tomllib": None,
    "itertools": {"pairwise", "batched"},
    "datetime": {"UTC"},
    "enum": {"StrEnum"},
    "contextlib": {"aclosing", "chdir"},
    "typing": {
        "Concatenate", "LiteralString", "Never", "NotRequired", "ParamSpec",
        "Required", "Self", "TypeAlias", "TypeGuard", "TypeVarTuple", "Unpack",
        "assert_never", "override", "reveal_type",
    },
}
NEWER_ATTRIBUTES = {"UTC", "pairwise", "batched", "bit_count", "file_digest", "StrEnum", "TaskGroup"}
NEWER_NAMES = {"anext", "aiter", "ExceptionGroup", "BaseExceptionGroup", "EncodingWarning"}
NEWER_KEYWORDS = {
    "zip": {"strict"},
    "dataclass": {"slots", "kw_only", "match_args"},
    "write_text": {"newline"},
    "read_text": {"newline"},
    "bisect": {"key"},
    "bisect_left": {"key"},
    "bisect_right": {"key"},
    "insort": {"key"},
    "insort_left": {"key"},
    "insort_right": {"key"},
}


def _python_files() -> list:
    return sorted(
        path for path in EXTRA_ROOT.rglob("*.py") if "__pycache__" not in path.parts
    )


def _call_name(node: ast.Call) -> str:
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _newer_api_uses(tree: ast.AST) -> list:
    found = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            found += [
                (line, alias.name)
                for alias in node.names
                if alias.name in NEWER_IMPORTS and NEWER_IMPORTS[alias.name] is None
            ]
        elif isinstance(node, ast.ImportFrom) and node.module in NEWER_IMPORTS:
            names = NEWER_IMPORTS[node.module]
            found += [
                (line, f"{node.module}.{alias.name}")
                for alias in node.names
                if names is None or alias.name in names
            ]
        elif isinstance(node, ast.Attribute) and node.attr in NEWER_ATTRIBUTES:
            found.append((line, "." + node.attr))
        elif isinstance(node, ast.Name) and node.id in NEWER_NAMES:
            found.append((line, node.id))
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            banned = NEWER_KEYWORDS.get(name, set())
            found += [(line, f"{name}({kw.arg}=)") for kw in node.keywords if kw.arg in banned]
            if name in {"isinstance", "issubclass"} and any(
                isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.BitOr)
                for arg in node.args[1:]
            ):
                found.append((line, f"{name}(X | Y)"))
    return found


def _parenthesized_with_items(source: str) -> list:
    """``with (a as b, ...):`` is 3.10 grammar, though 3.9's parser tolerates it."""

    tokens = [
        token
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type not in {tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT}
    ]
    found = []
    for index, token in enumerate(tokens[:-1]):
        if token.string != "with" or tokens[index + 1].string != "(":
            continue
        depth = 0
        for inner in tokens[index + 1:]:
            if inner.string in "([{":
                depth += 1
            elif inner.string in ")]}":
                depth -= 1
                if depth == 0:
                    break
            elif depth == 1 and inner.string == "as":
                found.append(token.start[0])
                break
    return found


def _has_annotations(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args
            every = arguments.posonlyargs + arguments.args + arguments.kwonlyargs
            every += [arg for arg in (arguments.vararg, arguments.kwarg) if arg]
            if node.returns is not None or any(arg.annotation for arg in every):
                return True
    return False


def _has_future_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


class TestPython39Compatibility(unittest.TestCase):
    def test_every_module_is_python_39_syntax_and_api(self) -> None:
        files = _python_files()
        self.assertGreaterEqual(len(files), 15)
        for path in files:
            relative = path.relative_to(EXTRA_ROOT).as_posix()
            with self.subTest(path=relative):
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=relative, feature_version=(3, 9))
                self.assertEqual([], _newer_api_uses(tree))
                self.assertEqual([], _parenthesized_with_items(source))
                if _has_annotations(tree):
                    # Annotations such as ``str | None`` must never be evaluated.
                    self.assertTrue(_has_future_annotations(tree))

    def test_guard_detects_what_it_claims_to_detect(self) -> None:
        sample = (
            "import tomllib\nfrom itertools import pairwise\nimport datetime\n"
            "zip(a, b, strict=True)\nisinstance(x, int | str)\ndatetime.UTC\n"
            "@dataclass(slots=True)\nclass A: pass\n"
        )
        self.assertEqual(
            [
                "tomllib",
                "itertools.pairwise",
                "zip(strict=)",
                "isinstance(X | Y)",
                ".UTC",
                "dataclass(slots=)",
            ],
            [name for _, name in sorted(_newer_api_uses(ast.parse(sample)))],
        )
        self.assertEqual(
            [1], _parenthesized_with_items("with (open(a) as f, open(b) as g):\n    pass\n")
        )
        self.assertEqual([], _parenthesized_with_items("with (lock):\n    pass\n"))
        with self.assertRaises(SyntaxError):
            ast.parse("match x:\n    case 1:\n        pass\n", feature_version=(3, 9))


class TestPublicApi(unittest.TestCase):
    def test_package_exports_only_the_documented_entry_points(self) -> None:
        self.assertEqual(
            [
                "CAPABILITIES",
                "DEFAULT_ENTRY_MAP",
                "DEFAULT_KG_BASE_IRI",
                "DocumentGraph",
                "GraphSecurityError",
                "Triple",
                "discover_markdown_files",
                "load_graph",
                "normalize_nfc17",
                "pct_segment",
            ],
            sorted(okf_graph.__all__),
        )
        for name in okf_graph.__all__:
            self.assertTrue(hasattr(okf_graph, name), name)
        for removed in ("load_current_graph", "load_replay_graph"):
            self.assertFalse(hasattr(okf_graph, removed), removed)
            self.assertFalse(hasattr(okf_graph.graph, removed), removed)
        self.assertEqual("knowledge-map.md", okf_graph.DEFAULT_ENTRY_MAP)
        self.assertEqual("https://kg.example.invalid/okf", okf_graph.DEFAULT_KG_BASE_IRI)


if __name__ == "__main__":
    unittest.main()
