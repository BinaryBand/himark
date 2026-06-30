use std::collections::{HashMap, HashSet};
use std::rc::Rc;

// ── Reps ─────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct Reps {
    pub min: usize,
    pub max: Option<usize>,
    pub allowed: Option<HashSet<usize>>,
    pub count_ref: Option<usize>,
}

impl Reps {
    pub fn exact(n: usize) -> Self {
        Reps { min: n, max: Some(n), allowed: None, count_ref: None }
    }

    pub fn accepts(&self, k: usize) -> bool {
        if let Some(ref set) = self.allowed {
            return set.contains(&k);
        }
        k >= self.min && self.max.map_or(true, |m| k <= m)
    }
}

impl Default for Reps {
    fn default() -> Self {
        Reps::exact(1)
    }
}

// ── Capture ───────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct Capture {
    pub text: String,
    pub span: (usize, usize),
    // Per-repetition byte spans into the source text. Only `reps.len()` is ever
    // consulted (count refs, `#` moustaches) -- the span contents are never read
    // -- so these stay cheap Copy tuples instead of owned Strings. Materializing
    // a `String` per unit here is what made the unbounded-repetition backtracking
    // (e.g. dedup's `!{...}[..]`) allocate O(n^2) and run ~10x slower than Go,
    // whose `text[a:b]` substring is a no-copy slice header.
    pub reps: Vec<(usize, usize)>,
    pub subs: Vec<Capture>,
    pub count: i64, // -1 = use reps.len()
}

impl Capture {
    pub fn rep_count(&self) -> usize {
        if self.count >= 0 { self.count as usize } else { self.reps.len() }
    }
}

// ── Match ─────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct HMatch {
    pub text: String,
    pub start: usize,
    pub end: usize,
    pub captures: Vec<Capture>,
}

impl HMatch {
    pub fn capture_at(&self, path: &[usize]) -> Option<&Capture> {
        let mut caps = &self.captures;
        let mut cap = None;
        for &idx in path {
            if idx >= caps.len() {
                return None;
            }
            cap = Some(&caps[idx]);
            caps = &caps[idx].subs;
        }
        cap
    }
}

// ── Alphabet ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub enum Alphabet {
    Range { lo: u32, hi: u32, base: usize },
    Groups { index: HashMap<String, usize>, base: usize },
}

impl Alphabet {
    pub fn from_range(lo: u32, hi: u32) -> Self {
        Alphabet::Range { lo, hi, base: (hi - lo + 1) as usize }
    }

    pub fn from_groups(groups: Vec<Vec<String>>) -> Self {
        let mut index = HashMap::new();
        let base = groups.len();
        for (i, grp) in groups.into_iter().enumerate() {
            for m in grp {
                index.insert(m, i);
            }
        }
        Alphabet::Groups { index, base }
    }

    pub fn contains_char(&self, ch: char) -> bool {
        match self {
            Alphabet::Range { lo, hi, .. } => *lo <= ch as u32 && ch as u32 <= *hi,
            Alphabet::Groups { index, .. } => index.contains_key(&ch.to_string()),
        }
    }

    // Returns the numeric value of string `s` over this alphabet.
    // Uses f64 to handle base^n values that overflow i64/u128 (e.g. base58^33).
    // Precision is approximate for very large values, but sufficient for range checks.
    pub fn value(&self, s: &str) -> Option<f64> {
        let mut v: f64 = 0.0;
        match self {
            Alphabet::Range { lo, base, .. } => {
                let hi = lo + *base as u32 - 1;
                for ch in s.chars() {
                    let cp = ch as u32;
                    if cp < *lo || cp > hi {
                        return None;
                    }
                    v = v * (*base as f64) + (cp - lo) as f64;
                }
            }
            Alphabet::Groups { index, base } => {
                for ch in s.chars() {
                    let idx = index.get(&ch.to_string())?;
                    v = v * (*base as f64) + *idx as f64;
                }
            }
        }
        Some(v)
    }
}

// ── VM State ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct State {
    pub captures: Vec<Capture>,
    // Stages are shared by reference-counted pointer: find_matches rebuilds a
    // State per scan position, so cloning this Vec must stay O(stages) pointer
    // bumps, not a deep clone of every ancestor's text + capture tree.
    pub stages: Vec<Rc<HMatch>>,
    // Back-refs inside a SEQ_GROUP child see only captures[0..root_len].
    // usize::MAX means "no restriction" (top-level, outside any SEQ_GROUP).
    pub root_len: usize,
}

impl State {
    pub fn new(stages: Vec<Rc<HMatch>>) -> Self {
        State { captures: Vec::new(), stages, root_len: usize::MAX }
    }
}
