"""URL slugs."""

import re

_NON_WORD = re.compile(r"[^a-z0-9]+")


def slugify(text):
    """Lower-case ``text`` and turn every run of non-alphanumerics into one dash.

    The result must not start or end with a dash.
    """
    return _NON_WORD.sub("-", text.lower())
