/// Phase 0: split a raw HMK statement on top-level `=>` arrows.
/// Mirrors himark/parser/phase0.py.

pub fn split_statement(text: &str) -> Vec<String> {
    let mut steps: Vec<String> = Vec::new();
    let mut remaining = text;
    loop {
        match find_arrow(remaining) {
            None => {
                steps.push(remaining.trim().to_string());
                break;
            }
            Some(idx) => {
                steps.push(remaining[..idx].trim().to_string());
                remaining = &remaining[idx + 2..];
            }
        }
    }
    steps
}

/// Returns the byte index of the first top-level `=>`, or `None`.
fn find_arrow(text: &str) -> Option<usize> {
    let bytes = text.as_bytes();
    let n = text.len();
    let mut depth = 0i32;
    let mut i = 0usize;
    while i < n {
        let b = bytes[i];
        if b == b'\\' {
            i += 2;
            continue;
        }
        if b == b'=' && i + 1 < n && bytes[i + 1] == b'>' && depth == 0 {
            return Some(i);
        }
        if b == b'[' || b == b'{' {
            depth += 1;
        } else if b == b']' || b == b'}' {
            depth = depth.saturating_sub(1);
        }
        i += 1;
    }
    None
}
