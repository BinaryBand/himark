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
    if node.type == "leaf":
        print(f"{prefix}LEAF: {node.content!r}")
    elif node.type == "literal":
        print(f"{prefix}literal: {node.content!r}")
    elif node.type == "range":
        start, end = node.metadata.get("start", ""), node.metadata.get("end", "")
        print(f"{prefix}range: {start!r}..{end!r}")
    elif node.type in ("repetition_range",):
        mn, mx = node.metadata.get("min", ""), node.metadata.get("max", "")
        print(f"{prefix}repetition_range: {mn!r}..{mx!r}")
    elif node.type == "pad":
        print(f"{prefix}pad: {node.metadata.get('width')!r}")
    elif node.type == "option":
        print(f"{prefix}option: {node.content!r}")
    else:
        print(f"{prefix}{node.type}: {node.content!r}")
        if node.metadata:
            for key, val in node.metadata.items():
                if isinstance(val, list):
                    print(f"{prefix}  @{key}:")
                    for child in val:
                        print_tree(child, indent + 2)
        for child in node.children:
            print_tree(child, indent + 1)
