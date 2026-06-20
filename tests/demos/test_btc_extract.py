"""End-to-end tests for the Bitcoin-address extractor (`himark/scripts/btc_extract.hmk`).

The script is a three-pass pipeline: it tags every address-shaped run with its
recomputed and embedded checksums, keeps the ones whose checksums match (a `{$3}`
back-reference is the equality test), and reverts the rest to plain text. So a
genuine P2PKH (`1…`) address becomes `<btc>1A1zP1eP…</btc>` and a base58 word that
only *looks* like an address is left untouched — the checksum filters the false
positives with no manual step. These tests pin that on small inputs, then stress
it on a long synthetic document of base58 noise with real addresses planted in it.
"""

import hashlib
import random
import re
import time
from pathlib import Path

from himark.tools import precompiled

SCRIPT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "btc_extract.hmk"
RESOURCES = Path(__file__).resolve().parent / "resources"
OUTPUT = Path(__file__).resolve().parent / "output"
_PIPELINE = precompiled.compile_pipeline(precompiled.load_script(SCRIPT))

# Real legacy mainnet addresses (the Genesis coinbase and two vanity ones).
ADDRS = [
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
    "12c6DSiU4Rq3P4ZxziKxzrL5LmMBrzjrJX",
    "1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
]
# Genesis with the final base58 digit changed: address-shaped, bad checksum.
LOOKALIKE = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_TAG = re.compile(r"<btc>([^<]+)</btc>")


def run(text: str) -> str:
    return precompiled.apply(_PIPELINE, text)


def tagged(text: str) -> list[str]:
    """The addresses the pipeline accepted as valid (wrapped in <btc>…</btc>)."""
    return _TAG.findall(run(text))


def is_valid(addr: str) -> bool:
    """Independent base58check: the trailing 4 bytes equal the double-SHA256 of
    the 21-byte body's leading 4 bytes."""
    value = 0
    for c in addr:
        value = value * 58 + B58.index(c)
    payload = value.to_bytes(25, "big")
    return hashlib.sha256(hashlib.sha256(payload[:21]).digest()).digest()[:4] == payload[21:]


def test_real_addresses_are_kept():
    assert is_valid(ADDRS[0]) and not is_valid(LOOKALIKE)  # sanity of the fixtures
    assert tagged(" pay 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa now") == [ADDRS[0]]


def test_tags_every_valid_address_in_a_line():
    assert tagged(" " + " ".join(ADDRS)) == ADDRS


def test_lookalike_is_filtered_and_left_as_plain_text():
    out = run(" send " + LOOKALIKE + " here")
    assert "<btc>" not in out  # checksum mismatch → not accepted
    assert out == " send " + LOOKALIKE + " here"  # reverted verbatim


def test_valid_and_invalid_mixed():
    out = run(" a 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa b " + LOOKALIKE + " c")
    assert out == " a <btc>1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa</btc> b " + LOOKALIKE + " c"


def test_skips_p2sh_address():
    # A `3…` P2SH address has an interior `1`, but the boundary anchor keeps it
    # from being read as the start of a P2PKH address.
    assert run(" send 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy here") == (
        " send 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy here"
    )


def test_non_address_text_is_preserved():
    text = " a 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa b end\n"
    assert _TAG.sub(lambda m: m.group(1), run(text)) == text


def _stress_target(seed: int = 0):
    """A long document: base58 noise with real addresses planted throughout.

    Noise is never a `1`-led address-shaped value, so the planted addresses are
    the only matches. `1`-led short tokens are included so the value matcher is
    entered and cleanly rejected (width below the floor), not merely skipped."""
    rng = random.Random(seed)
    parts: list[str] = []
    planted: list[str] = []
    for i in range(8000):
        if rng.random() < 0.15:  # `1`-led but too short to be an address
            parts.append("1" + "".join(rng.choice(B58) for _ in range(rng.randint(3, 20))))
        else:  # not `1`-led; varied lengths, including address-length runs
            head = rng.choice("23456789")
            parts.append(head + "".join(rng.choice(B58) for _ in range(rng.randint(3, 49))))
        if i % 400 == 200:
            a = ADDRS[i % len(ADDRS)]
            parts.append(a)
            planted.append(a)
    return " " + " ".join(parts) + " ", planted


def test_stress_extracts_and_validates_all_planted_addresses_quickly():
    target, planted = _stress_target()
    assert len(target) > 100_000  # a genuinely long document
    t0 = time.perf_counter()
    out = run(target)
    elapsed = time.perf_counter() - t0
    # Every planted (real, valid) address is tagged, in order; no false positives.
    assert _TAG.findall(out) == planted
    # Lossless apart from the tags.
    assert _TAG.sub(lambda m: m.group(1), out) == target
    # Generous time bound — a catastrophic-regression guard, not a benchmark.
    assert elapsed < 15.0, f"extraction took {elapsed:.2f}s for {len(target):,} chars"


# ── Runbook ───────────────────────────────────────────────────────────────────
# Run this file directly to apply the shipped script to a real input file and see
# the result, for fast manual iteration:  python tests/scripts/test_btc_extract.py
if __name__ == "__main__":
    text = (RESOURCES / "addresses.txt").read_text("utf-8")
    print(run(text))
