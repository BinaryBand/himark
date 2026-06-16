"""North Star: in-place document transpilation via `splice`.

A `=>` chain produces one branch per match. `execute` renders them as a **list**;
`splice` lays each render back over its source span, keeping the text between
matches verbatim (the in-place transform). Both come from the same branches.
"""

from marky import parser
from marky.engine import execute, splice


def test_execute_returns_list_of_matches():
    assert execute(parser.parse("{a..z} => <p>"), "a1b2c") == ["<p>", "<p>", "<p>"]


def test_splice_returns_whole_text_spliced():
    assert splice(parser.parse("{a..z} => <p>"), "a1b2c") == "<p>1<p>2<p>"


def test_splice_no_match_is_identity():
    assert splice(parser.parse("{a..z} => <p>"), "123") == "123"
