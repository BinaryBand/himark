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
    else:
        print(f"{prefix}{node.type}: {node.content!r}")
        if node.metadata:
            for key, val in node.metadata.items():
                print(f"{prefix}  @{key}:")
                for child in val:
                    print_tree(child, indent + 2)
        for child in node.children:
            print_tree(child, indent + 1)
