from himark.parser import phase1, phase2, phase3
from himark.node import HMKNode


def parse(text: str) -> tuple[HMKNode, HMKNode | None]:
    """Run all three phases and return (pattern_tree, template_tree | None)."""
    stmt = phase1.split_statement(text)

    pattern_tree = phase3.parse(phase2.parse(stmt.pattern_text))
    template_tree = phase3.parse(phase2.parse(stmt.template_text)) if stmt.template_text else None

    return pattern_tree, template_tree
