"""Optional OKF Markdown -> RDF 1.1 document graph (in memory, Observe-only).

Not part of the default Goal Teams install.  See ``README.md`` next to this
package for the CLI and the input rules.
"""

from __future__ import annotations

from .graph import (
    CAPABILITIES,
    DEFAULT_ENTRY_MAP,
    DEFAULT_KG_BASE_IRI,
    DocumentGraph,
    GraphSecurityError,
    Triple,
    discover_markdown_files,
    load_graph,
    normalize_nfc17,
    pct_segment,
)

__all__ = [
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
]
