"""N-Triples export: canonical RDF 1.1 lines that parse back to the same triples."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from okf_graph import graph as kg
from tests.helpers import BASIC, active_map, document, load


_IRI = r'<((?:[^\x00-\x20<>"{}|^`\\]|\\u[0-9A-F]{4}|\\U[0-9A-F]{8})*)>'
_LITERAL = r'"((?:[^"\\\n\r]|\\["\\nr])*)"(?:\^\^' + _IRI + r"|@([a-zA-Z]+(?:-[a-zA-Z0-9]+)*))?"
_LINE = re.compile(rf"^{_IRI} {_IRI} (?:{_IRI}|{_LITERAL}) \.$")
_ECHAR = {'\\"': '"', "\\\\": "\\", "\\n": "\n", "\\r": "\r"}


def _unescape_literal(text: str) -> str:
    return re.sub(r'\\["\\nr]', lambda match: _ECHAR[match.group(0)], text)


def _unescape_iri(text: str) -> str:
    return re.sub(
        r"\\u([0-9A-F]{4})|\\U([0-9A-F]{8})",
        lambda match: chr(int(match.group(1) or match.group(2), 16)),
        text,
    )


def _parse(ntriples: str) -> set:
    parsed = set()
    for number, line in enumerate(ntriples.split("\n")[:-1], start=1):
        match = _LINE.match(line)
        if match is None:
            raise AssertionError(f"line {number} is not canonical N-Triples: {line!r}")
        subject, predicate, iri_object, literal, datatype, language = match.groups()
        if iri_object is not None:
            triple = kg.Triple(_unescape_iri(subject), _unescape_iri(predicate), _unescape_iri(iri_object))
        else:
            triple = kg.Triple(
                _unescape_iri(subject),
                _unescape_iri(predicate),
                _unescape_literal(literal),
                "literal",
                _unescape_iri(datatype) if datatype else None,
                language,
            )
        parsed.add(triple)
    return parsed


class TestNTriples(unittest.TestCase):
    def test_every_triple_becomes_one_canonical_line_that_round_trips(self) -> None:
        graph = load(BASIC)
        text = graph.to_ntriples()
        self.assertTrue(text.endswith(" .\n"))
        self.assertEqual(len(graph.triples), text.count("\n"))
        self.assertEqual(set(graph.triples), _parse(text))
        self.assertEqual(text, load(BASIC).to_ntriples())
        self.assertIn(
            '"2026-08-07T20:00:01+08:00"^^<http://www.w3.org/2001/XMLSchema#dateTimeStamp>',
            text,
        )

    def test_literals_escape_only_quote_backslash_newline_and_carriage_return(self) -> None:
        triple = kg.Triple(
            "https://kg.example.invalid/s", "https://kg.example.invalid/p",
            'say "hi" \\ there\nnext\rend\ttab é', "literal",
        )
        self.assertEqual(
            '"say \\"hi\\" \\\\ there\\nnext\\rend\ttab é"', kg._nt_object(triple)
        )
        tagged = kg.Triple("https://s", "https://p", "chat", "literal", None, "fr")
        self.assertEqual('"chat"@fr', kg._nt_object(tagged))
        plain = kg.Triple("https://s", "https://p", "x", "literal", kg.XSD + "string")
        self.assertEqual('"x"', kg._nt_object(plain))
        self.assertEqual("<https://kg.example.invalid/a\\u0020b>", kg._nt_iri("https://kg.example.invalid/a b"))

    def test_claim_text_with_quotes_and_line_breaks_round_trips(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-ntriples-") as tmp:
            root = Path(tmp)
            (root / "knowledge-map.md").write_text(
                active_map(("SOURCE", "source.md")), encoding="utf-8"
            )
            body = '### CLM-QUOTE\n\nShe said "yes" \\ twice.\nSecond line 第二行.\n'
            (root / "source.md").write_text(document("SOURCE", body), encoding="utf-8")
            graph = load(root)
            text = graph.to_ntriples()
            self.assertIn('"She said \\"yes\\" \\\\ twice.\\nSecond line 第二行."', text)
            self.assertEqual(set(graph.triples), _parse(text))


if __name__ == "__main__":
    unittest.main()
