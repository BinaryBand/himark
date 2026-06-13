"""North Star: in-place document transpilation via replace-mode (`=>+`).

`=>` extracts -- the statement returns the list of rendered matches. `=>+`
replaces -- it splices each rendered match back into the source and returns the
whole string, keeping the text between matches verbatim.
"""

from marky import parser
from marky.engine import execute


def transform(pattern, text):
    return execute(parser.parse(pattern), text)


def test_extract_returns_list_of_matches():
    assert transform("{a..z} => <p>{{.}}</p>", "a1b2c") == [
        "<p>a</p>",
        "<p>b</p>",
        "<p>c</p>",
    ]


def test_replace_returns_whole_text_spliced():
    assert transform("{a..z} =>+ <p>{{.}}</p>", "a1b2c") == "<p>a</p>1<p>b</p>2<p>c</p>"


def test_replace_no_match_is_identity():
    assert transform("{a..z} =>+ <p>{{.}}</p>", "123") == "123"
