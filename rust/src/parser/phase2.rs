/// Phase 2: tokenize HMK source into a tree of leaf + brace nodes.
/// Mirrors himark/parser/phase2.py.

use crate::parser::nodes::{ChildNode, RootNode};
use crate::parser::text::{brace_end, unescape};

/// Raw brace group before semantic resolution.
#[derive(Clone, Debug)]
pub struct RawBrace {
    pub content: String,
    pub count_src: Option<String>,
}

/// Intermediate node produced by phase2 (before phase3 resolves semantics).
#[derive(Clone, Debug)]
pub enum RawNode {
    Leaf(String),
    Brace(RawBrace),
}

const ESCAPES: &[(&str, char)] = &[
    ("n", '\n'),
    ("t", '\t'),
    ("r", '\r'),
    ("\\", '\\'),
    ("{", '{'),
    ("}", '}'),
    ("\"", '"'),
];

pub fn tokenize(text: &str) -> Result<Vec<RawNode>, String> {
    let bytes = text.as_bytes();
    let n = text.len();
    let mut nodes: Vec<RawNode> = Vec::new();
    let mut leaf_buf = String::new();
    let mut pos = 0usize;

    macro_rules! flush_leaf {
        () => {
            if !leaf_buf.is_empty() {
                nodes.push(RawNode::Leaf(leaf_buf.clone()));
                leaf_buf.clear();
            }
        };
    }

    while pos < n {
        let ch = text[pos..].chars().next().unwrap();
        let ch_len = ch.len_utf8();

        // Escape sequence
        if ch == '\\' && pos + 1 < n {
            let esc_ch = text[pos + 1..].chars().next().unwrap();
            let esc_str = &esc_ch.to_string();
            if let Some(&(_, c)) = ESCAPES.iter().find(|(k, _)| *k == esc_str) {
                flush_leaf!();
                nodes.push(RawNode::Leaf(c.to_string()));
                pos += 1 + esc_ch.len_utf8();
            } else {
                leaf_buf.push(ch);
                pos += ch_len;
            }
            continue;
        }

        // Quoted literal "..."
        if ch == '"' {
            flush_leaf!();
            let end = scan_string(text, pos)?;
            let content = unescape(&text[pos + 1..end - 1]);
            nodes.push(RawNode::Leaf(content));
            pos = end;
            continue;
        }

        // Brace group {expr}[count?] or !{expr}[count?]
        if ch == '{' || (ch == '!' && text[pos + 1..].starts_with('{')) {
            flush_leaf!();
            let complement = ch == '!';
            let brace_start = if complement { pos + 1 } else { pos };
            let span = brace_end(&text[brace_start..])
                .ok_or_else(|| format!("Unclosed '{{' at position {}", brace_start))?;
            let brace_abs_end = brace_start + span;
            let inner = &text[brace_start + 1..brace_abs_end - 1];
            let content = if complement {
                format!("!{}", inner)
            } else {
                inner.to_string()
            };
            let mut after = brace_abs_end;
            let count_src = if text[after..].starts_with('[') {
                match scan_count_bracket(text, after) {
                    Some((cs, end_pos)) => {
                        after = end_pos;
                        Some(cs)
                    }
                    None => None,
                }
            } else {
                None
            };
            nodes.push(RawNode::Brace(RawBrace { content, count_src }));
            pos = after;
            continue;
        }

        leaf_buf.push(ch);
        pos += ch_len;
    }
    flush_leaf!();

    if nodes.is_empty() {
        nodes.push(RawNode::Leaf(text.to_string()));
    }

    Ok(nodes)
}

fn scan_string(text: &str, pos: usize) -> Result<usize, String> {
    let bytes = text.as_bytes();
    let mut i = pos + 1;
    while i < bytes.len() {
        if bytes[i] == b'\\' {
            i += 2;
            continue;
        }
        if bytes[i] == b'"' {
            return Ok(i + 1);
        }
        i += 1;
    }
    Err(format!("Unclosed '\"' at position {pos}"))
}

/// Scan `[...]` at `pos` in `text`. Returns `(count_src, end)` where
/// `count_src` is the content between the brackets and `end` is the byte
/// position just past `]`.
fn scan_count_bracket(text: &str, pos: usize) -> Option<(String, usize)> {
    let bytes = text.as_bytes();
    if pos >= bytes.len() || bytes[pos] != b'[' {
        return None;
    }
    let mut i = pos + 1;
    while i < bytes.len() {
        if bytes[i] == b']' {
            let cs = text[pos + 1..i].to_string();
            return Some((cs, i + 1));
        }
        i += 1;
    }
    None
}

/// Convert raw phase-2 nodes to the final ChildNode form (with unresolved
/// semantics represented as leaf+brace). Phase3 uses this output.
pub fn raw_to_root(nodes: Vec<RawNode>) -> RootNode {
    // We can't fill in semantics here — that's phase3.
    // Instead we keep this as a raw representation.
    // (This function exists to satisfy the same structural interface phase3 expects.)
    let children: Vec<ChildNode> = nodes
        .into_iter()
        .filter_map(|n| match n {
            RawNode::Leaf(s) => Some(ChildNode::Leaf { content: s }),
            RawNode::Brace(_) => None, // phase3 handles these
        })
        .collect();
    RootNode::new(children)
}
