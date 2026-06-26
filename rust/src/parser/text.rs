/// Lexical text helpers: brace scanning, depth-aware splitting, escape handling.
/// Mirrors himark/parser/_text.py at the byte level (all delimiters are ASCII).

pub fn unescape(s: &str) -> String {
    if !s.contains('\\') {
        return s.to_string();
    }
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars().peekable();
    while let Some(ch) = chars.next() {
        if ch == '\\' {
            if let Some(esc) = chars.next() {
                out.push(match esc {
                    'n' => '\n',
                    't' => '\t',
                    'r' => '\r',
                    '\\' => '\\',
                    '{' => '{',
                    '}' => '}',
                    '"' => '"',
                    other => other,
                });
            }
        } else {
            out.push(ch);
        }
    }
    out
}

fn is_escaped_byte(bytes: &[u8], i: usize) -> bool {
    let mut n = 0usize;
    let mut j = i as isize - 1;
    while j >= 0 && bytes[j as usize] == b'\\' {
        n += 1;
        j -= 1;
    }
    n % 2 == 1
}

/// Strip unescaped leading/trailing ASCII whitespace.
pub fn strip_unescaped(s: &str) -> String {
    let bytes = s.as_bytes();
    let n = bytes.len();
    let mut start = 0;
    while start < n && (bytes[start] == b' ' || bytes[start] == b'\t') {
        start += 1;
    }
    let mut end = n;
    while end > start && (bytes[end - 1] == b' ' || bytes[end - 1] == b'\t')
        && !is_escaped_byte(bytes, end - 1)
    {
        end -= 1;
    }
    s[start..end].to_string()
}

/// Returns the byte offset just past the `}` that closes the `{` at position 0,
/// or `None` if unbalanced. Backslash-escaped braces are ignored.
pub fn brace_end(expr: &str) -> Option<usize> {
    let mut depth = 0i32;
    let mut chars = expr.char_indices().peekable();
    while let Some((byte_pos, ch)) = chars.next() {
        if ch == '\\' {
            chars.next();
            continue;
        }
        match ch {
            '{' => depth += 1,
            '}' => {
                depth -= 1;
                if depth == 0 {
                    return Some(byte_pos + ch.len_utf8());
                }
            }
            _ => {}
        }
    }
    None
}

/// The content between the outer braces of `{...}`.
pub fn inner_of(part: &str) -> &str {
    match brace_end(part) {
        Some(end) => &part[1..end - 1],
        None => &part[1..part.len() - 1],
    }
}

/// Split `text` on `sep` only at depth 0 (outside `{…}` and `[…]`).
/// Backslash-escaped brackets are not counted as depth changers.
pub fn split_top(sep: &str, text: &str) -> Vec<String> {
    let sep_len = sep.len();
    let sep_bytes = sep.as_bytes();
    let bytes = text.as_bytes();
    let n = text.len();
    let mut parts: Vec<String> = Vec::new();
    let mut depth = 0i32;
    let mut cur_start = 0usize;
    let mut i = 0usize;

    while i < n {
        if bytes[i] == b'\\' {
            // Skip one more UTF-8 char after the backslash
            i += 1;
            if i < n {
                let ch_len = text[i..].chars().next().map_or(1, |c| c.len_utf8());
                i += ch_len;
            }
            continue;
        }
        let ch = text[i..].chars().next().unwrap();
        let ch_len = ch.len_utf8();
        match ch {
            '{' | '[' => {
                depth += 1;
                i += ch_len;
            }
            '}' | ']' => {
                if depth > 0 {
                    depth -= 1;
                }
                i += ch_len;
            }
            _ if depth == 0
                && i + sep_len <= n
                && &bytes[i..i + sep_len] == sep_bytes =>
            {
                parts.push(text[cur_start..i].to_string());
                i += sep_len;
                cur_start = i;
            }
            _ => {
                i += ch_len;
            }
        }
    }
    parts.push(text[cur_start..].to_string());
    parts
}

/// `split_top` that rejects parts with unescaped surrounding whitespace.
pub fn strict_split(sep: &str, text: &str, context: &str) -> Result<Vec<String>, String> {
    let parts = split_top(sep, text);
    for p in &parts {
        let stripped = strip_unescaped(p);
        if !stripped.is_empty() && stripped != *p {
            return Err(format!(
                "Unexpected whitespace in {:?}: remove spaces around {:?} \
                 (or escape a literal space as '\\ ')",
                context, sep
            ));
        }
    }
    Ok(parts)
}
