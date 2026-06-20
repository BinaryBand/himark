//! The match loop — a port of the supported subset of `_run.py`.
//!
//! Backtracking via recursion (the Python continuation chain becomes a recursive
//! `match_seq` over the element index). Positions are **code-point indices** (the
//! input is decoded to `Vec<char>` once), so behaviour matches Python's `str`
//! indexing exactly. Captures accumulate in a flat `Vec` and roll back by
//! truncation on a failed branch. Back-references read that same flat list —
//! grouping braces (which would need a root/sub split) are out of subset and run
//! on Python, so one flat capture list is sufficient here.
//!
//! Repetition pieces (`reps`) are kept **lazy** during the search — a trial
//! capture stores only a compact `RepSpec`, and the per-repetition strings are
//! materialised once, for the captures of a *successful* match. (Python gets this
//! for free because `list[:k]` shares string references; a naive Rust port that
//! re-collected each slice is `O(k²)` in allocations and dominates the cost.)

use std::rc::Rc;

use serde::Serialize;

use crate::program::{Element, Matcher, Reps};

/// A compact, lazily-expanded description of a capture's per-rep pieces.
#[derive(Clone)]
enum RepSpec {
    /// Group repetition: units bounded by `ends` (shared across all `k` tried at
    /// one position), the first starting at `start`.
    Units {
        ends: Rc<Vec<usize>>,
        start: usize,
        k: usize,
    },
    /// `k` copies of one string (a back-reference's referent, or `""`).
    Copies { unit: Rc<String>, k: usize },
}

impl RepSpec {
    fn expand(&self, chars: &[char]) -> Vec<String> {
        match self {
            RepSpec::Units { ends, start, k } => (0..*k)
                .map(|i| {
                    let a = if i == 0 { *start } else { ends[i - 1] };
                    collect(chars, a, ends[i])
                })
                .collect(),
            RepSpec::Copies { unit, k } => vec![(**unit).clone(); *k],
        }
    }
}

/// A capture with absolute code-point span; rebased to match-relative on output.
struct Capture {
    start: usize,
    end: usize,
    reps: RepSpec,
}

#[derive(Serialize)]
pub struct CapOut {
    pub s: usize,
    pub e: usize,
    pub reps: Vec<String>,
}

#[derive(Serialize)]
pub struct MatchOut {
    pub s: usize,
    pub e: usize,
    pub caps: Vec<CapOut>,
}

// ── small helpers over code-point slices ──────────────────────────────────────

/// End index if `s`'s chars occur at `pos`, else None (Python `text[pos:].startswith`).
fn lit_match(chars: &[char], pos: usize, s: &str) -> Option<usize> {
    let mut i = pos;
    for sc in s.chars() {
        if i >= chars.len() || chars[i] != sc {
            return None;
        }
        i += 1;
    }
    Some(i)
}

fn starts_with(chars: &[char], pos: usize, unit: &[char]) -> bool {
    pos + unit.len() <= chars.len() && chars[pos..pos + unit.len()] == *unit
}

fn collect(chars: &[char], a: usize, b: usize) -> String {
    chars[a..b].iter().collect()
}

// ── matcher evaluation ────────────────────────────────────────────────────────

impl Matcher {
    /// Greedy single-unit match at `pos` (longest member / the matched char).
    fn mtch(&self, chars: &[char], pos: usize) -> Option<usize> {
        match self {
            Matcher::Lit { s } => lit_match(chars, pos, s),
            Matcher::Range { lo, hi, excl } => {
                if pos >= chars.len() {
                    return None;
                }
                let ch = chars[pos];
                if ch < *lo || ch > *hi {
                    return None;
                }
                if let Some(e) = excl {
                    if e.excludes(&ch.to_string()) {
                        return None;
                    }
                }
                Some(pos + 1)
            }
            Matcher::Union { arms, excl } => {
                for arm in arms {
                    if let Some(end) = arm.mtch(chars, pos) {
                        let ok = match excl {
                            Some(e) => !e.excludes(&collect(chars, pos, end)),
                            None => true,
                        };
                        if ok {
                            return Some(end);
                        }
                    }
                }
                None
            }
            Matcher::Compl { inner } => {
                if pos >= chars.len() || inner.mtch(chars, pos).is_some() {
                    None
                } else {
                    Some(pos + 1)
                }
            }
            Matcher::Group { members } => {
                if pos >= chars.len() {
                    return None;
                }
                for (m, _) in members {
                    if let Some(end) = lit_match(chars, pos, m) {
                        return Some(end);
                    }
                }
                None
            }
            Matcher::Het { inner } => inner.mtch(chars, pos),
        }
    }

    /// Python `accepts(first)`: the matcher consumes exactly `len` chars at `pos`.
    fn accepts(&self, chars: &[char], pos: usize, len: usize) -> bool {
        len > 0 && self.mtch(chars, pos) == Some(pos + len)
    }

    /// Heterogeneous continuation (`equal_unit`): the next rep, with member
    /// freedom that depends on the matcher kind (see `_compile`).
    fn equal_unit(&self, chars: &[char], pos: usize, first: &[char]) -> Option<usize> {
        match self {
            // A congruence group stays in the matched member's group per position.
            Matcher::Group { members } => {
                let seq = group_seq(members, first)?;
                let mut cur = pos;
                for gidx in seq {
                    let mut advanced = false;
                    for (m, idx) in members {
                        if *idx == gidx {
                            if let Some(end) = lit_match(chars, cur, m) {
                                cur = end;
                                advanced = true;
                                break;
                            }
                        }
                    }
                    if !advanced {
                        return None;
                    }
                }
                Some(cur)
            }
            // Default (`_Base.equal_unit`): a fresh match — any member. `Het` lands
            // here too: its `mtch` is the inner matcher, i.e. any member per position.
            _ => self.mtch(chars, pos),
        }
    }
}

/// Parse `first` into the sequence of group indices it spells (longest-first
/// member matching), or None if it is not spellable in the alphabet.
fn group_seq(members: &[(String, usize)], first: &[char]) -> Option<Vec<usize>> {
    let mut seq = Vec::new();
    let mut i = 0;
    while i < first.len() {
        let mut found = false;
        for (m, idx) in members {
            if let Some(end) = lit_match(first, i, m) {
                seq.push(*idx);
                i = end;
                found = true;
                break;
            }
        }
        if !found {
            return None;
        }
    }
    Some(seq)
}

/// Acceptable rep counts in `0..=built`, greedy (longest-first), with the
/// zero-rep option tried last — mirrors `_run._counts`.
fn counts(reps: &Reps, built: usize) -> Vec<usize> {
    let mut ks = Vec::new();
    let mut k = built;
    while k >= 1 {
        if reps.accepts(k) {
            ks.push(k);
        }
        k -= 1;
    }
    if reps.accepts(0) {
        ks.push(0);
    }
    ks
}

// ── the sequence / continuation chain ─────────────────────────────────────────

fn match_seq(
    els: &[Element],
    idx: usize,
    chars: &[char],
    pos: usize,
    caps: &mut Vec<Capture>,
) -> Option<usize> {
    if idx >= els.len() {
        return Some(pos);
    }
    match &els[idx] {
        Element::Lit { s } => {
            lit_match(chars, pos, s).and_then(|end| match_seq(els, idx + 1, chars, end, caps))
        }
        Element::Anchor { at } => {
            let ok = match at.as_str() {
                "line_start" => pos == 0 || chars[pos - 1] == '\n',
                "line_end" => pos == chars.len() || chars[pos] == '\n',
                "scope_start" => pos == 0,
                "scope_end" => pos == chars.len(),
                _ => false,
            };
            if ok {
                match_seq(els, idx + 1, chars, pos, caps)
            } else {
                None
            }
        }
        Element::Group { m, reps, het } => run_matcher(m, *het, reps, els, idx, chars, pos, caps),
        Element::BackRef { g, reps } => {
            // The referent is a slice into `chars` (no copy); the per-rep string is
            // materialised once, lazily, only for a successful match's output.
            let referent = caps.get(*g).map(|c| &chars[c.start..c.end]);
            match_referent(referent, reps, els, idx, chars, pos, caps)
        }
    }
}

/// Push a capture, try the continuation, roll back on failure.
fn attempt(
    els: &[Element],
    idx: usize,
    chars: &[char],
    pos: usize,
    end: usize,
    reps: RepSpec,
    caps: &mut Vec<Capture>,
) -> Option<usize> {
    let mark = caps.len();
    caps.push(Capture {
        start: pos,
        end,
        reps,
    });
    if let Some(r) = match_seq(els, idx + 1, chars, end, caps) {
        return Some(r);
    }
    caps.truncate(mark);
    None
}

/// Port of `_run._run_matcher`: longest-first first-unit split, then the run's
/// acceptable counts in priority order. A primitive (`het == false`) repeats the
/// same string; a het matcher uses `equal_unit`.
fn run_matcher(
    m: &Matcher,
    het: bool,
    reps: &Reps,
    els: &[Element],
    idx: usize,
    chars: &[char],
    pos: usize,
    caps: &mut Vec<Capture>,
) -> Option<usize> {
    let greedy_end = match m.mtch(chars, pos) {
        Some(e) if e > pos => e,
        _ => {
            return if reps.accepts(0) {
                attempt(els, idx, chars, pos, pos, empty_units(pos), caps)
            } else {
                None
            };
        }
    };

    for unit_len in (1..=greedy_end - pos).rev() {
        if !m.accepts(chars, pos, unit_len) {
            continue;
        }
        let first: &[char] = &chars[pos..pos + unit_len];
        let mut ends = vec![pos + unit_len];
        let mut current = pos + unit_len;
        loop {
            if let Some(max) = reps.max {
                if ends.len() >= max {
                    break;
                }
            }
            let nxt = if het {
                m.equal_unit(chars, current, first)
            } else if starts_with(chars, current, first) {
                Some(current + first.len())
            } else {
                None
            };
            match nxt {
                Some(n) => {
                    ends.push(n);
                    current = n;
                }
                None => break,
            }
        }
        let ends = Rc::new(ends);
        for k in counts(reps, ends.len()) {
            let end = if k == 0 { pos } else { ends[k - 1] };
            let spec = RepSpec::Units {
                ends: Rc::clone(&ends),
                start: pos,
                k,
            };
            if let Some(r) = attempt(els, idx, chars, pos, end, spec, caps) {
                return Some(r);
            }
        }
    }
    if reps.accepts(0) {
        attempt(els, idx, chars, pos, pos, empty_units(pos), caps)
    } else {
        None
    }
}

fn empty_units(pos: usize) -> RepSpec {
    RepSpec::Units {
        ends: Rc::new(Vec::new()),
        start: pos,
        k: 0,
    }
}

/// Port of `_run._match_referent`: match `referent` (a value pulled from running
/// state) per `reps`. `None` = an undefined reference (matches only zero-width).
fn match_referent(
    referent: Option<&[char]>,
    reps: &Reps,
    els: &[Element],
    idx: usize,
    chars: &[char],
    pos: usize,
    caps: &mut Vec<Capture>,
) -> Option<usize> {
    // An empty captured referent matches zero-width for any count.
    if matches!(referent, Some(r) if r.is_empty()) {
        let spec = RepSpec::Copies {
            unit: Rc::new(String::new()),
            k: reps.min,
        };
        return attempt(els, idx, chars, pos, pos, spec, caps);
    }

    let unit = Rc::new(
        referent
            .map(|r| r.iter().collect::<String>())
            .unwrap_or_default(),
    );

    // Contiguous copies of the referent at `pos`, up to reps.max.
    let mut ends = vec![pos];
    if let Some(r) = referent {
        let mut current = pos;
        while reps.max.is_none_or(|c| ends.len() - 1 < c) && starts_with(chars, current, r) {
            current += r.len();
            ends.push(current);
        }
    }

    let built = ends.len() - 1;
    for k in counts(reps, built) {
        let end = ends[k];
        let spec = RepSpec::Copies {
            unit: Rc::clone(&unit),
            k,
        };
        if let Some(r) = attempt(els, idx, chars, pos, end, spec, caps) {
            return Some(r);
        }
    }
    None
}

// ── public entry ──────────────────────────────────────────────────────────────

pub fn find_matches(els: &[Element], chars: &[char]) -> Vec<MatchOut> {
    let mut matches = Vec::new();
    let n = chars.len();
    let mut pos = 0;
    while pos < n {
        let mut caps: Vec<Capture> = Vec::new();
        match match_seq(els, 0, chars, pos, &mut caps) {
            Some(end) if end > pos => {
                let caps_out = caps
                    .iter()
                    .map(|c| CapOut {
                        s: c.start - pos, // rebase to match-relative (Python `_finalize`)
                        e: c.end - pos,
                        reps: c.reps.expand(chars),
                    })
                    .collect();
                matches.push(MatchOut {
                    s: pos,
                    e: end,
                    caps: caps_out,
                });
                pos = end;
            }
            _ => pos += 1,
        }
    }
    matches
}
