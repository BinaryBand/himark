"""Emoji shortcode -> Unicode via the `emoji` library.

Accepts GitHub-style aliases (e.g. :white_check_mark:) as well as CLDR names.
Falls back to the original :code: string when the shortcode is not recognised.
"""

import emoji as _emoji_lib

from marky.utils.resolver import register


def resolve(code: str) -> str:
    """Return the Unicode grapheme cluster for *code*, or ':code:' if unknown."""
    text = f":{code}:"
    result = _emoji_lib.emojize(text, language="alias")
    if result == text:
        result = _emoji_lib.emojize(text)
    return result


register("emoji", resolve)
