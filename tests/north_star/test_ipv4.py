"""North Star: IPv4 — docs/HMK.md"""

from himark import parser
from himark.engine import find_matches

PATTERN = "{@d:0..255}{.}{@d:0..255}{.}{@d:0..255}{.}{@d:0..255}"


def matches(text):
    trees = parser.parse(PATTERN)
    return [m.text for m in find_matches(trees[0], text)]


def test_typical_address():
    assert matches("192.168.1.1") == ["192.168.1.1"]


def test_loopback():
    assert matches("127.0.0.1") == ["127.0.0.1"]


def test_broadcast():
    assert matches("255.255.255.255") == ["255.255.255.255"]


def test_out_of_range_octet_not_matched():
    result = matches("256.0.0.1")
    assert "256.0.0.1" not in result


def test_extracted_from_prose():
    result = matches("connect to 10.0.0.1 and 172.16.0.1")
    assert "10.0.0.1" in result
    assert "172.16.0.1" in result
