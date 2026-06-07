test_cases = [
    "[a]",
    "[abc]",
    "[a||c]",
    "[hello||world]",
    "[hello][ ..][world]",
    "[a..z][.][a..z]",
    "[a..z]",
    "[A..Z]",
    "[a..Z]",
    "[a..c||H]",
    "[a..c||F..H]",
    "[..]",
    "[0..]",
    "[a..]",
    "[ ..]",
    "[5..99]",
    "[0..9](b10)",
    "[0..f](hex)",
    "[0..v](b32)",
    "[1..z](b58)",
    "[A../](b64)",
    "[hello](i)",
    "[0..99]",
    "[0..ff](hex)",
    "[0..99](pad:2)",
    "[0..ff](hex, pad:2)",
    "[f..fff](hex, pad:4)",
    "[[a]]",
    "[[a..z]]",
    "[[abc]]",
    "[[hello||world]]",
    "[a](1..3)",
    "<<foo>>",
    "{{ . }}",
    "{{ 1 }}",
    "{{ 1.2 }}",
    "{{ 1.2..3.1 }}",
    "{{ :tada: }}",
    "{{ $\pi$ }}"
]


class HMKNode:
    def __init__(self, node_type, content, children=None, metadata=None):
        self.type = node_type
        self.content = content
        self.children = children or []
        self.metadata = metadata or {}

    def __repr__(self):
        if self.children:
            children_str = ", ".join(repr(c) for c in self.children)
            return f"HMK({self.type!r}, {self.content!r}, [{children_str}])"
        if self.metadata:
            return f"HMK({self.type!r}, {self.content!r}, meta={self.metadata})"
        return f"HMK({self.type!r}, {self.content!r})"


def parse_hmk_recursive(text):
    """Recursively parse HMK text into an AST."""
    import re

    parenthesis = r"\(([^)]+)\)"
    single_brackets = r"\[([^\]]+)\]"
    double_brackets = r"\[\[([^\]]+)\]\]"
    brackets = f"{double_brackets}|{single_brackets}"
    brackets_with_opts = f"{brackets}(?:{parenthesis})?"
    double_chevrons = r"<<((?:[^>]|>[^>])*)>>"
    double_braces = r"{{((?:[^}]|}[^}])*)}}"

    possible_matches = f"{brackets_with_opts}|{double_chevrons}|{double_braces}"

    # Map group index to node type
    group_types = ["double_brackets", "single_brackets", "options", "double_chevrons", "double_braces"]

    nodes = []
    pos = 0

    while pos < len(text):
        match = re.match(possible_matches, text[pos:])
        if not match:
            nodes.append(HMKNode("leaf", text[pos:]))
            break

        if match.start() > 0:
            nodes.append(HMKNode("leaf", text[pos:pos + match.start()]))

        groups = match.groups()
        matched_idx = next(i for i, g in enumerate(groups) if g is not None)
        node_type = group_types[matched_idx]
        content = groups[matched_idx]

        # Create node with recursive children
        node = HMKNode(node_type, content, parse_hmk_recursive(content).children)

        # Handle options for single brackets
        if matched_idx == 1 and groups[2]:  # Single brackets with options
            node.metadata["options"] = parse_hmk_recursive(groups[2]).children

        nodes.append(node)
        pos += match.end()

    return HMKNode("root", text, nodes or [HMKNode("leaf", text)])


def print_tree(node, indent=0):
    """Pretty print the AST."""
    prefix = "  " * indent
    if node.type == "leaf":
        print(f"{prefix}LEAF: {node.content!r}")
    else:
        print(f"{prefix}{node.type}: {node.content!r}")
        if node.metadata:
            for key, val in node.metadata.items():
                print(f"{prefix}  @{key}:")
                for child in val:
                    print_tree(child, indent + 2)
        for child in node.children:
            print_tree(child, indent + 1)


def main():
    print("=" * 70)
    print("HMK Recursive Parser - AST Output")
    print("=" * 70)
    print()

    for test in test_cases:
        print(f"Input: {test!r}")
        ast = parse_hmk_recursive(test)
        print_tree(ast)
        print()


if __name__ == "__main__":
    main()