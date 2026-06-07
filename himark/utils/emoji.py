"""Emoji shortcode → Unicode lookup for {{ :name: }} template expressions."""

_CODES: dict[str, str] = {
    # Symbols
    "white_check_mark": "✅",
    "x": "❌",
    "warning": "⚠️",
    "heavy_check_mark": "✔️",
    "question": "❓",
    "exclamation": "❗",
    "fire": "\U0001f525",
    "star": "⭐",
    "sparkles": "✨",
    # Objects
    "tada": "\U0001f389",
    "rocket": "\U0001f680",
    "heart": "❤️",
    "thumbsup": "\U0001f44d",
    "thumbsdown": "\U0001f44e",
    "clap": "\U0001f44f",
    "wave": "\U0001f44b",
    "eyes": "\U0001f440",
    "100": "\U0001f4af",
    "zap": "⚡",
    # Faces
    "smile": "\U0001f604",
    "laughing": "\U0001f606",
    "sob": "\U0001f62d",
    "thinking": "\U0001f914",
    "wink": "\U0001f609",
    # Tech
    "computer": "\U0001f4bb",
    "lock": "\U0001f512",
    "key": "\U0001f511",
    "bug": "\U0001f41b",
    "wrench": "\U0001f527",
    "hammer": "\U0001f528",
    "memo": "\U0001f4dd",
    "book": "\U0001f4d6",
    "package": "\U0001f4e6",
    "inbox_tray": "\U0001f4e5",
    "outbox_tray": "\U0001f4e4",
}


def resolve(code: str) -> str:
    """Return the Unicode character(s) for *code*, or ':code:' if unknown."""
    return _CODES.get(code, f":{code}:")
