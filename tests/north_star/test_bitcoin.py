"""North Star: Bitcoin P2PKH address — docs/HMK.md"""

from marky import parser
from marky.engine._match import find_matches

# Matches a leading '1' then a b58 body bounded to the P2PKH value range.
PATTERN = "{1}{11111111111111111111111..{b58}..zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz}"


def matches(text):
    trees = parser.parse(PATTERN)
    return [m.text for m in find_matches(trees[0], text)]


def test_genesis_address():
    # The coinbase address of block 0.
    assert "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" in matches(
        "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    )


def test_p2sh_address_not_matched_whole():
    # P2SH addresses start with '3'; the full address is not a valid P2PKH match.
    # HMK has no anchors so the engine may still find sub-matches at an inner '1'.
    result = matches("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
    assert "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy" not in result


def test_extracted_from_prose():
    text = "send to 1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2 or hold"
    result = matches(text)
    assert "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2" in result


def test_leading_one_required():
    # Strip the leading '1' — should not match as a whole address.
    result = matches("A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
    assert "A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" not in result
