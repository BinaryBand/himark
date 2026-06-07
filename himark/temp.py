import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class HMKPattern:
    pattern: str
    transformer: Optional[str] = None


class HMKCompiler:
    def __init__(self):
        self.pos = 0
        self.text = ""
        self.groups = 0

    def compile(self, hmk: str) -> tuple[str, Optional[str]]:
        self.text = hmk
        self.pos = 0
        self.groups = 0

        pattern = self.parse_sequence()
        return pattern, None

    def current(self) -> Optional[str]:
        if self.pos < len(self.text):
            return self.text[self.pos]
        return None

    def peek(self, offset=1) -> Optional[str]:
        p = self.pos + offset
        if p < len(self.text):
            return self.text[p]
        return None

    def advance(self, count=1):
        self.pos += count

    def parse_sequence(self) -> str:
        parts = []
        while self.pos < len(self.text):
            curr = self.current()
            if curr == "[":
                parts.append(self.parse_bracket_group())
            elif curr == "^":
                parts.append("^")
                self.advance()
            elif curr == "$":
                parts.append("$")
                self.advance()
            elif curr and curr in " \t\n":
                self.advance()
            else:
                break
        return "".join(parts)

    def parse_bracket_group(self) -> str:
        self.advance()
        content, needs_group = self.parse_bracket_content()

        if self.current() == "]":
            self.advance()

        repetition = self.parse_repetition()

        if repetition:
            if needs_group or "|" in content:
                return f"({content}){repetition}"
            else:
                return f"{content}{repetition}"
        return content

    def parse_bracket_content(self) -> tuple[str, bool]:
        negate = False

        if self.current() == "[" and self.peek() == "[":
            negate = True
            self.advance(2)

        content = ""
        curr = self.current()
        while curr and curr != "]":
            content += curr
            self.advance()
            curr = self.current()

        if negate:
            return f"[^{content}]+", False

        if ".." in content:
            return self.compile_range(content), False
        elif "||" in content:
            return self.compile_alternation(content), True
        else:
            return re.escape(content), False

    def compile_range(self, content: str) -> str:
        parts = content.split("..")
        if len(parts) != 2:
            return re.escape(content)

        start, end = parts[0], parts[1]

        if start == "" and end == "":
            return "."
        elif start == "0" and end == "":
            return r"\d+"
        elif start == "a" and end == "":
            return r"[a-zA-Z0-9_]+"
        elif start == " " and end == "":
            return r"\s+"
        elif start and end and len(start) == 1 and len(end) == 1:
            if start.isdigit() and end.isdigit():
                return f"[{start}-{end}]"
            elif start.islower() and end.islower():
                return f"[{start}-{end}]"
            elif start.isupper() and end.isupper():
                return f"[{start}-{end}]"
            elif start.islower() and end.isupper():
                return f"[{start}-z|A-{end}]"
            else:
                return f"[{re.escape(start)}-{re.escape(end)}]"

        return re.escape(content)

    def compile_alternation(self, content: str) -> str:
        parts = content.split("||")
        if len(parts) == 1:
            return re.escape(content)

        escaped = [re.escape(p.strip()) if len(p.strip()) > 1 else p.strip() for p in parts]
        return "|".join(escaped)

    def parse_escape(self) -> str:
        self.advance()
        char = self.current()
        if char == "\\":
            self.advance()
            return re.escape("\\")
        elif char == "[":
            self.advance()
            return re.escape("[")
        elif char == "]":
            self.advance()
            return re.escape("]")
        elif char == "t":
            self.advance()
            return r"\t"
        elif char == "n":
            self.advance()
            return r"\n"
        elif char == "r":
            self.advance()
            return r"\r"
        elif char == "|":
            self.advance()
            return re.escape("|")
        else:
            return re.escape(char) if char else ""

    def parse_repetition(self) -> str:
        if self.current() != "(":
            return ""

        self.advance()
        count_spec = ""
        curr = self.current()

        while curr and curr != ")":
            count_spec += curr
            self.advance()
            curr = self.current()

        if self.current() == ")":
            self.advance()

        return self.compile_repetition(count_spec.strip())

    def compile_repetition(self, spec: str) -> str:
        if not spec:
            return ""

        spec = spec.strip()

        if spec == "0..":
            return "*"
        elif spec == "1..":
            return "+"
        elif spec.isdigit():
            return f"{{{spec}}}"
        elif ".." in spec:
            parts = spec.split("..")
            if parts[0] and parts[1]:
                return f"{{{parts[0]},{parts[1]}}}"
            elif parts[0]:
                return f"{{{parts[0]},}}"
            elif parts[1]:
                return f"{{0,{parts[1]}}}"

        return ""


def execute_hmk(hmk_pattern: str, text: str) -> list[str]:
    """Compile HMK pattern and execute against text."""
    compiler = HMKCompiler()
    regex_pattern, _ = compiler.compile(hmk_pattern)

    try:
        matches = re.findall(regex_pattern, text)
        return matches
    except re.error as e:
        print(f"RegEx Error: {e}")
        return []


def apply_transformer(template: str, matches: list[str]) -> list[str]:
    """Apply a transformer template to matches.

    Supports:
    {{ . }} - full matched text
    {{ 1 }} - first capture group
    """
    results = []
    for match in matches:
        result = template
        result = result.replace("{{ . }}", match)
        result = result.replace("{{.}}", match)
        results.append(result)
    return results


def main():
    print("=" * 70)
    print("HMK Compiler - Minimal Proof of Concept")
    print("=" * 70)
    print()

    examples = [
        ("[a]", "cat", ["a"]),
        ("[abc]", "xabcy", ["abc"]),
        ("[a||c]", "abc", ["a", "c"]),
        ("[a..z](1..)", "abc123xyz", ["abc", "xyz"]),
        ("[0..9](1..)", "test123end456", ["123", "456"]),
        ("[a](2)", "aaa", ["aa"]),
        ("[a](1..3)", "aaaa", ["aaa", "a"]),
    ]

    print("PATTERN TESTS")
    print("-" * 70)

    for hmk_pat, text, expected in examples:
        compiler = HMKCompiler()
        regex, _ = compiler.compile(hmk_pat)
        matches = execute_hmk(hmk_pat, text)

        status = "[OK]" if matches == expected else "[FAIL]"
        print(f"{status} HMK: {hmk_pat:20} -> RegEx: {regex:15} Match: {matches}")

    print()
    print("TRANSFORMER EXAMPLES")
    print("-" * 70)
    text = "The price is 25px"
    pattern = "[0..9](1..)"
    compiler = HMKCompiler()
    regex, _ = compiler.compile(pattern)
    matches = re.findall(regex, text)
    print(f"Text:     {text!r}")
    print(f"Pattern:  {pattern}")
    print(f"RegEx:    {regex}")
    print(f"Matches:  {matches}")

    template = "<span>{{ . }}</span>"
    transformed = apply_transformer(template, matches)
    print(f"Template: {template}")
    print(f"Output:   {transformed}")
    print()

    print("ADVANCED FEATURES")
    print("-" * 70)
    print("Supported HMK features in this POC:")
    print("  * Basic literals: [a], [abc]")
    print("  * Alternation: [a||b||c] -> (a|b|c)")
    print("  * Character ranges: [a..z], [0..9]")
    print("  * Cross-case ranges: [a..Z] -> [a-zA-Z]")
    print("  * Shortcuts: [0..], [a..], [ ..]")
    print("  * Repetition: [a](2), [a](1..3), [a](0..)")
    print("  * Anchors: ^, $")
    print("  * Basic transformers: {{ . }}")
    print()
    print("Not yet implemented:")
    print("  * Separator statements (<<...>>)")
    print("  * Advanced template variables ({{ 1 }}, {{ 1.2 }}, etc.)")
    print("  * Captures and group references")
    print("  * Negation ([[...]])")
    print("  * Varied repetition (variables)")
    print("  * Emoji/LaTeX interpolation")
    print()


if __name__ == "__main__":
    main()