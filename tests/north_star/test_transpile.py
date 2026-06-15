"""North Star: in-place document transpilation via replace-mode (`=>+`).

`=>` extracts -- the statement returns the list of rendered matches. `=>+`
replaces -- it splices each rendered match back into the source and returns the
whole string, keeping the text between matches verbatim. With references removed
from the language, a `=>` step emits a constant for every match.
"""

from marky import parser
from marky.engine import execute


def transform(pattern, text):
    return execute(parser.parse(pattern), text)


def test_extract_returns_list_of_matches():
    assert transform("{a..z} => <p>", "a1b2c") == ["<p>", "<p>", "<p>"]


def test_replace_returns_whole_text_spliced():
    assert transform("{a..z} =>+ <p>", "a1b2c") == "<p>1<p>2<p>"


def test_replace_no_match_is_identity():
    assert transform("{a..z} =>+ <p>", "123") == "123"
