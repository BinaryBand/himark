/// Phase 1: macro expansion, structural rewrites, implicit wrapping.
/// Mirrors himark/parser/phase1.py and himark/parser/rewrites.py.

// Macros from macros.toml, sorted longest-name-first for greedy matching.
static MACROS: &[(&str, &str)] = &[
    ("ascii", "\u{0000}..\u{007f}"),
    ("b256", "\u{0000}..\u{00ff}"),
    ("b32", "{@d},{:@w:v}"),
    ("b58", "{@d},{@u},{@l},!{0,l,I,O}"),
    ("b64", "{@d},{@l},{@u},+,/"),
    ("hex", "{@d},{:@w:f}"),
    ("uni", "\u{0000}..\u{10FFFF}"),
    ("d", "0..9"),
    ("l", "a..z"),
    ("s", "\n,\r, ,\t"),
    ("u", "A..Z"),
    ("w", "{{a,A},{b,B},{c,C},{d,D},{e,E},{f,F},{g,G},{h,H},{i,I},{j,J},{k,K},{l,L},{m,M},{n,N},{o,O},{p,P},{q,Q},{r,R},{s,S},{t,T},{u,U},{v,V},{w,W},{x,X},{y,Y},{z,Z}},_"),
    ("x", "!@s"),
];

pub fn preprocess(step: &str, first: bool) -> Result<String, String> {
    let expanded = apply_rewrites(&expand_macros(step)?);
    if first && needs_wrap(&expanded) {
        Ok(format!("{{{}}}", expanded))
    } else {
        Ok(expanded)
    }
}

fn needs_wrap(step: &str) -> bool {
    !step.is_empty() && !step.contains('{')
}

// ── Macro expansion ──────────────────────────────────────────────────────────

fn expand_macros(text: &str) -> Result<String, String> {
    let mut out = text.to_string();
    for _ in 0..10 {
        let new = expand_once(&out);
        if new == out {
            break;
        }
        out = new;
    }
    // Check for remaining known-macro references (circular / undefined).
    if has_unresolved_macros(&out) {
        return Err(format!(
            "Unresolved macros (circular or undefined): {:?}",
            find_at_words(&out)
        ));
    }
    Ok(out)
}

/// One pass: replace every `@name` (followed by a word boundary) with its expansion.
fn expand_once(text: &str) -> String {
    let bytes = text.as_bytes();
    let n = text.len();
    let mut out = String::with_capacity(n);
    let mut i = 0usize;
    while i < n {
        if bytes[i] != b'@' {
            let ch_len = text[i..].chars().next().map_or(1, |c| c.len_utf8());
            out.push_str(&text[i..i + ch_len]);
            i += ch_len;
            continue;
        }
        // Try each macro name (longest first).
        let mut matched = false;
        for &(name, expansion) in MACROS {
            let name_end = i + 1 + name.len();
            if name_end > n {
                continue;
            }
            if &text[i + 1..name_end] != name {
                continue;
            }
            // Word boundary: the char after the name must not be alphanumeric or `_`.
            let after = text.get(name_end..).and_then(|s| s.chars().next());
            if after.map_or(false, |c| c.is_alphanumeric() || c == '_') {
                continue;
            }
            out.push_str(expansion);
            i = name_end;
            matched = true;
            break;
        }
        if !matched {
            out.push('@');
            i += 1;
        }
    }
    out
}

fn has_unresolved_macros(text: &str) -> bool {
    let bytes = text.as_bytes();
    let n = text.len();
    let mut i = 0usize;
    while i < n {
        if bytes[i] != b'@' {
            i += 1;
            continue;
        }
        for &(name, _) in MACROS {
            let end = i + 1 + name.len();
            if end > n {
                continue;
            }
            if &text[i + 1..end] != name {
                continue;
            }
            let after = text.get(end..).and_then(|s| s.chars().next());
            if !after.map_or(false, |c| c.is_alphanumeric() || c == '_') {
                return true;
            }
        }
        i += 1;
    }
    false
}

fn find_at_words(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let bytes = text.as_bytes();
    let n = text.len();
    let mut i = 0;
    while i < n {
        if bytes[i] == b'@' {
            let start = i;
            i += 1;
            while i < n && (text.as_bytes()[i].is_ascii_alphanumeric() || text.as_bytes()[i] == b'_') {
                i += 1;
            }
            out.push(text[start..i].to_string());
        } else {
            i += 1;
        }
    }
    out
}

// ── Rewrites (bind_count + substitute) ───────────────────────────────────────

fn apply_rewrites(src: &str) -> String {
    // 1. bind_count  2. substitute {|..} → {|}[..]
    let after_bind = bind_count(src);
    substitute(&after_bind, "{|..}", "{|}[..]")
}

fn substitute(src: &str, find: &str, into: &str) -> String {
    src.replace(find, into)
}

/// Unroll every self-binding count `[…#…]` (where `#` is not followed by a
/// digit). Mirrors `rewrites.bind_count`.
fn bind_count(src: &str) -> String {
    let mut s = src.to_string();
    loop {
        let Some((bracket_start, bracket_end)) = find_hash_count(&s) else {
            break;
        };
        let marker = s[bracket_start..bracket_end].to_string();
        let inner = &marker[1..marker.len() - 1]; // strip [ and ]
        let free = format!("[{}]", hash_bounds_to_free(inner));
        let bound_template = "[#@]";
        match unroll(&s, bracket_start, &marker, &free, bound_template) {
            None => break,
            Some(new) => s = new,
        }
    }
    s
}

/// Find a `[…#…]` bracket (# not followed by digit, no second #). Returns byte
/// range `(start, end)` of the bracket in `src`.
fn find_hash_count(src: &str) -> Option<(usize, usize)> {
    let bytes = src.as_bytes();
    let n = bytes.len();
    let mut i = 0;
    while i < n {
        if bytes[i] != b'[' {
            i += 1;
            continue;
        }
        let start = i;
        let mut j = i + 1;
        let mut hash_at: Option<usize> = None;
        let mut ok = false;
        while j < n {
            let b = bytes[j];
            if b == b']' {
                ok = hash_at.is_some();
                break;
            }
            if b == b'#' {
                if hash_at.is_some() {
                    break; // second # — not a bind-count
                }
                if j + 1 < n && bytes[j + 1].is_ascii_digit() {
                    break; // #N is a count-ref, not a bind-count
                }
                hash_at = Some(j);
            }
            j += 1;
        }
        if ok && j < n {
            return Some((start, j + 1));
        }
        i += 1;
    }
    None
}

/// Replace `(\.\.)?#(\.\.)?` with `..` inside the bracket content.
fn hash_bounds_to_free(inner: &str) -> String {
    let bytes = inner.as_bytes();
    let Some(hash_pos) = bytes.iter().position(|&b| b == b'#') else {
        return inner.to_string();
    };
    let has_lead = hash_pos >= 2 && bytes[hash_pos - 2] == b'.' && bytes[hash_pos - 1] == b'.';
    let replace_start = if has_lead { hash_pos - 2 } else { hash_pos };
    let has_trail =
        hash_pos + 3 <= bytes.len() && bytes[hash_pos + 1] == b'.' && bytes[hash_pos + 2] == b'.';
    let replace_end = if has_trail { hash_pos + 3 } else { hash_pos + 1 };
    format!("{}{}{}", &inner[..replace_start], "..", &inner[replace_end..])
}

/// Mirrors `rewrites._unroll`: find the enclosing `{…}[count]` around the
/// `marker_at` position, then emit `first_body + {bound_body} + count`.
fn unroll(
    src: &str,
    marker_at: usize,
    marker: &str,
    free: &str,
    bound_template: &str,
) -> Option<String> {
    let open_idx = enclosing_brace(src, marker_at)?;
    let span = crate::parser::text::brace_end(&src[open_idx..])?;
    let brace_end_abs = open_idx + span;
    let count_src = count_match(src, brace_end_abs)?;
    let body = &src[open_idx + 1..brace_end_abs - 1];
    let g = count_top_groups(&src[..open_idx]);
    let first = body.replacen(marker, free, 1);
    let bound = bound_template.replace('@', &g.to_string());
    let rest_body = body.replacen(marker, &bound, 1);
    Some(format!(
        "{}{}{{{}}}{}{}",
        &src[..open_idx],
        first,
        rest_body,
        count_src,
        &src[brace_end_abs + count_src.len()..]
    ))
}

fn enclosing_brace(src: &str, pos: usize) -> Option<usize> {
    let bytes = src.as_bytes();
    let mut depth = 0i32;
    let mut i = pos as isize - 1;
    while i >= 0 {
        let b = bytes[i as usize];
        if b == b'}' {
            depth += 1;
        } else if b == b'{' {
            if depth == 0 {
                return Some(i as usize);
            }
            depth -= 1;
        }
        i -= 1;
    }
    None
}

/// Match `[…]` immediately at `pos` in `src`. Returns the matched string.
fn count_match(src: &str, pos: usize) -> Option<String> {
    let bytes = src.as_bytes();
    if pos >= bytes.len() || bytes[pos] != b'[' {
        return None;
    }
    let mut i = pos + 1;
    while i < bytes.len() {
        if bytes[i] == b']' {
            return Some(src[pos..=i].to_string());
        }
        i += 1;
    }
    None
}

fn count_top_groups(text: &str) -> usize {
    let mut depth = 0i32;
    let mut n = 0usize;
    for b in text.bytes() {
        if b == b'{' {
            if depth == 0 {
                n += 1;
            }
            depth += 1;
        } else if b == b'}' {
            depth = depth.saturating_sub(1);
        }
    }
    n
}
