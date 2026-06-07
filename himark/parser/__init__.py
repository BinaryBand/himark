from himark.parser import phase1, phase2, phase3
from himark.node import HMKNode


def parse(text: str) -> tuple[HMKNode, HMKNode | None]:
    """Run all three phases and return (pattern_tree, template_tree | None)."""
    pattern_text, template_text = phase1.split_statement(text)

    pattern_tree = phase3.parse(phase2.parse(pattern_text))
    template_tree = phase3.parse(phase2.parse(template_text)) if template_text else None

    return pattern_tree, template_tree
