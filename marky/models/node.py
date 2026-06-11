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


def print_tree(node, indent=0):
    prefix = "  " * indent
    t = node.type
    m = node.metadata

    if t == "leaf":
        print(f"{prefix}LEAF: {node.content!r}")
    elif t == "root":
        print(f"{prefix}root")
        for child in node.children:
            print_tree(child, indent + 1)
    elif t == "brace_group":
        count = m.get("count")
        count_str = f"[{count}]" if count else ""
        print(f"{prefix}brace_group{count_str}: {node.content!r}")
        for child in node.children:
            print_tree(child, indent + 1)
    elif t == "separator":
        count = m.get("count")
        count_str = f"[{count}]" if count else ""
        print(f"{prefix}separator{count_str}: {node.content!r}")
    elif t == "literal":
        print(f"{prefix}literal: {node.content!r}")
    elif t == "char_range":
        print(f"{prefix}char_range: {m['start']!r}..{m['end']!r}")
    elif t == "named_alpha":
        print(f"{prefix}named_alpha: {m['name']}")
    elif t == "full_alpha":
        print(f"{prefix}full_alpha")
        for child in node.children:
            print_tree(child, indent + 1)
    elif t == "upper_bound":
        print(f"{prefix}upper_bound: ..{m['upper']!r}")
        print_tree(m["alpha"], indent + 1)
    elif t == "lower_bound":
        print(f"{prefix}lower_bound: {m['lower']!r}..")
        print_tree(m["alpha"], indent + 1)
    elif t == "bounded_range":
        print(f"{prefix}bounded_range: {m['lower']!r}..{m['upper']!r}")
        print_tree(m["alpha"], indent + 1)
    elif t == "zip_range":
        print(f"{prefix}zip_range")
        print_tree(m["left"], indent + 1)
        print_tree(m["right"], indent + 1)
    elif t == "union":
        excl = m.get("exclusions", [])
        print(f"{prefix}union (exclusions: {excl})")
        for child in node.children:
            print_tree(child, indent + 1)
    elif t == "complement":
        print(f"{prefix}complement")
        for child in node.children:
            print_tree(child, indent + 1)
    elif t == "token_set":
        print(f"{prefix}token_set: {m['tokens']}")
    elif t == "group_class":
        print(f"{prefix}group_class: {m['groups']}")
    elif t == "padded":
        width = m.get("width")
        print(f"{prefix}padded: width={width}")
        for child in node.children:
            print_tree(child, indent + 1)
    elif t == "full_match":
        print(f"{prefix}full_match")
    elif t == "group_ref":
        idx = ".".join(str(i) for i in m["index"])
        print(f"{prefix}group_ref: {idx}")
    elif t == "span_ref":
        start = ".".join(str(i) for i in m["start"])
        end = ".".join(str(i) for i in m["end"])
        print(f"{prefix}span_ref: {start}..{end}")
    elif t == "count_ref":
        print(f"{prefix}count_ref: #{m['group']}")
    elif t == "emoji":
        print(f"{prefix}emoji: :{m['code']}:")
    elif t == "latex":
        print(f"{prefix}latex: {m['expr']!r}")
    else:
        print(f"{prefix}{t}: {node.content!r}")
        for child in node.children:
            print_tree(child, indent + 1)
