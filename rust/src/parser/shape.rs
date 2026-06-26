/// Shape detection: is a brace interior a σ-grammar alphabet, or a
/// concatenation of constructs (grouping brace)?
/// Mirrors himark/parser/_shape.py.

use crate::parser::phase2::{tokenize, RawNode};
use crate::parser::text::{split_top, strip_unescaped};

pub fn is_sequence_brace(content: &str) -> bool {
    // A bound `{floor:alphabet:ceiling}` is never a sequence brace.
    if split_top(":", content).len() == 3 {
        return false;
    }
    let body = if content.starts_with('!') {
        &content[1..]
    } else {
        content
    };
    for arm in split_top(",", body) {
        for part in split_top("..", &arm) {
            if !is_sigma_atom(&part) {
                return true;
            }
        }
    }
    false
}

fn is_sigma_atom(part: &str) -> bool {
    let part = strip_unescaped(part);
    let part = if part.starts_with('!') {
        part[1..].trim().to_string()
    } else {
        part
    };
    if part.is_empty() {
        return true;
    }
    let nodes = match tokenize(&part) {
        Ok(n) => n,
        Err(_) => return false,
    };
    let braces: Vec<_> = nodes
        .iter()
        .filter(|n| matches!(n, RawNode::Brace(_)))
        .collect();
    if braces.is_empty() {
        return true; // bare token
    }
    if braces.len() > 1 {
        return false;
    }
    // One brace — check it's not glued to adjacent text, and has at most exact count.
    let has_adjacent_text = nodes.iter().any(|n| match n {
        RawNode::Leaf(s) => !s.trim().is_empty(),
        _ => false,
    });
    if has_adjacent_text {
        return false;
    }
    if let Some(RawNode::Brace(b)) = braces.first() {
        if let Some(ref cs) = b.count_src {
            let cs = cs.trim();
            if !cs.chars().all(|c| c.is_ascii_digit()) {
                return false; // ranged/star count
            }
        }
    }
    true
}
