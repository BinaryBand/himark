use std::collections::HashSet;
use crate::types::Alphabet;

// ── Exclusion spec ────────────────────────────────────────────────────────────

// Python: (singles, ranges, literals) triple produced by the compiler.
// singles = set of single chars
// ranges  = list of (lo_char, hi_char) pairs
// literals = list of multi-char strings
#[derive(Clone, Debug)]
pub struct Exclusions {
    pub singles: HashSet<char>,
    pub ranges: Vec<(char, char)>,
    pub literals: Vec<String>,
}

impl Exclusions {
    pub fn excludes_at(&self, text: &str, pos: usize) -> bool {
        let ch = match text[pos..].chars().next() {
            Some(c) => c,
            None => return false,
        };
        if self.singles.contains(&ch) {
            return true;
        }
        for &(lo, hi) in &self.ranges {
            if lo <= ch && ch <= hi {
                return true;
            }
        }
        for lit in &self.literals {
            if text[pos..].starts_with(lit.as_str()) {
                return true;
            }
        }
        false
    }
}

// ── Matcher trait ─────────────────────────────────────────────────────────────

pub trait Matcher: Send + Sync {
    // Returns end position of matched unit, or None on failure.
    fn match_one(&self, text: &str, pos: usize) -> Option<usize>;

    fn accepts(&self, s: &str) -> bool {
        self.match_one(s, 0) == Some(s.len())
    }

    // Match the same "group-index sequence" that `first` represents, starting at `pos`.
    fn equal_unit(&self, text: &str, pos: usize, first: &str) -> Option<usize> {
        if text[pos..].starts_with(first) {
            Some(pos + first.len())
        } else {
            None
        }
    }
}

// ── CharMatcher ───────────────────────────────────────────────────────────────

pub struct CharMatcher {
    pub lo: u32,
    pub hi: u32,
    pub excl: Option<Exclusions>,
}

impl Matcher for CharMatcher {
    fn match_one(&self, text: &str, pos: usize) -> Option<usize> {
        let ch = text[pos..].chars().next()?;
        let cp = ch as u32;
        if cp < self.lo || cp > self.hi {
            return None;
        }
        if let Some(ref excl) = self.excl {
            if excl.excludes_at(text, pos) {
                return None;
            }
        }
        Some(pos + ch.len_utf8())
    }
}

// ── GroupMatcher ──────────────────────────────────────────────────────────────

pub struct GroupMatcher {
    // (member_string, group_index), sorted longest-first
    pub members: Vec<(String, usize)>,
    pub accept_set: HashSet<String>,
}

impl GroupMatcher {
    pub fn new(groups: Vec<Vec<String>>) -> Self {
        let mut members: Vec<(String, usize)> = groups
            .into_iter()
            .enumerate()
            .flat_map(|(i, grp)| grp.into_iter().filter(|m| !m.is_empty()).map(move |m| (m, i)))
            .collect();
        members.sort_by(|a, b| b.0.len().cmp(&a.0.len()));
        let accept_set: HashSet<String> = members.iter().map(|(m, _)| m.clone()).collect();
        GroupMatcher { members, accept_set }
    }
}

impl Matcher for GroupMatcher {
    fn match_one(&self, text: &str, pos: usize) -> Option<usize> {
        for (m, _) in &self.members {
            if text[pos..].starts_with(m.as_str()) {
                return Some(pos + m.len());
            }
        }
        None
    }

    fn accepts(&self, s: &str) -> bool {
        self.accept_set.contains(s)
    }

    fn equal_unit(&self, text: &str, pos: usize, first: &str) -> Option<usize> {
        // Decode `first` into its group-index sequence, then re-match that sequence at pos.
        let mut seq: Vec<usize> = Vec::new();
        let mut i = 0;
        while i < first.len() {
            let found = self.members.iter().find(|(m, _)| first[i..].starts_with(m.as_str()));
            match found {
                Some((m, idx)) => { seq.push(*idx); i += m.len(); }
                None => return None,
            }
        }
        let mut cur = pos;
        for gidx in seq {
            let found = self.members.iter().find(|(m, idx)| *idx == gidx && text[cur..].starts_with(m.as_str()));
            match found {
                Some((m, _)) => cur += m.len(),
                None => return None,
            }
        }
        Some(cur)
    }
}

// ── ComplementMatcher ─────────────────────────────────────────────────────────

pub struct ComplementMatcher {
    pub inner_groups: Vec<Vec<String>>,
}

impl Matcher for ComplementMatcher {
    fn match_one(&self, text: &str, pos: usize) -> Option<usize> {
        if pos >= text.len() {
            return None;
        }
        for grp in &self.inner_groups {
            for m in grp {
                if !m.is_empty() && text[pos..].starts_with(m.as_str()) {
                    return None;
                }
            }
        }
        let ch = text[pos..].chars().next()?;
        Some(pos + ch.len_utf8())
    }

    fn equal_unit(&self, text: &str, pos: usize, _first: &str) -> Option<usize> {
        self.match_one(text, pos)
    }
}

// ── ValueMatcher ──────────────────────────────────────────────────────────────

pub struct ValueMatcher {
    pub alph: Alphabet,
    pub lo_val: Option<f64>,
    pub hi_val: Option<f64>,
    pub wmin: usize,
    pub wmax: Option<usize>,
    pub excl: Option<Exclusions>,
}

impl Matcher for ValueMatcher {
    fn match_one(&self, text: &str, pos: usize) -> Option<usize> {
        // Collect all chars that belong to the alphabet starting at pos (byte-indexed).
        let mut end = pos;
        for ch in text[pos..].chars() {
            if !self.alph.contains_char(ch) {
                break;
            }
            end += ch.len_utf8();
        }
        let avail = end - pos; // byte length of available alphabet chars

        // Build sorted list of candidate byte-widths (greedy first).
        let top = self.wmax.map_or(avail, |m| m.min(avail));
        if top < self.wmin {
            return None;
        }

        // We need to iterate over byte widths that correspond to valid char boundaries.
        // Collect valid char-boundary offsets.
        let mut offsets: Vec<usize> = vec![0];
        for ch in text[pos..end].chars() {
            let last = *offsets.last().unwrap();
            offsets.push(last + ch.len_utf8());
        }
        // offsets[i] = byte offset of i-th char boundary from pos

        let max_chars = offsets.len().saturating_sub(1);
        let wmax_chars = self.wmax.unwrap_or(max_chars).min(max_chars);

        for w_chars in (self.wmin..=wmax_chars).rev() {
            let byte_width = offsets[w_chars];
            let candidate = &text[pos..pos + byte_width];
            if let Some(ref excl) = self.excl {
                if excl.excludes_at(text, pos) && byte_width == 1 {
                    continue;
                }
                if self.excl.as_ref().map_or(false, |e| {
                    e.literals.iter().any(|lit| lit == candidate)
                        || (w_chars == 1 && {
                            let ch = candidate.chars().next().unwrap();
                            e.singles.contains(&ch)
                                || e.ranges.iter().any(|&(lo, hi)| lo <= ch && ch <= hi)
                        })
                }) {
                    continue;
                }
            }
            let val = match self.alph.value(candidate) {
                Some(v) => v,
                None => continue,
            };
            if self.lo_val.map_or(false, |lo| val < lo) {
                continue;
            }
            if self.hi_val.map_or(false, |hi| val > hi) {
                continue;
            }
            return Some(pos + byte_width);
        }
        None
    }
}
