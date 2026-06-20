//! The compiled program: serde mirrors of the Python `Element` / matcher subset.
//!
//! These deserialize from the JSON that `himark/engine/backend/_translate.py`
//! emits — one-to-one with the supported `_compile` types. Anything outside the
//! subset never reaches here (the Python translator raises `Unsupported` and the
//! pattern runs on the Python backend instead).

use serde::Deserialize;

/// A resolved repetition spec — mirrors `_compile.Reps` (without `count_ref`,
/// which the translator rejects).
#[derive(Deserialize)]
pub struct Reps {
    pub min: usize,
    pub max: Option<usize>,
    pub allowed: Option<Vec<usize>>,
}

impl Reps {
    pub fn accepts(&self, k: usize) -> bool {
        if let Some(a) = &self.allowed {
            return a.contains(&k);
        }
        k >= self.min && self.max.is_none_or(|m| k <= m)
    }
}

/// A compiled exclusion set (`_compile._Excluder`): single strings plus
/// inclusive string ranges. Membership/comparison is by Unicode scalar order,
/// matching Python's `str` comparison.
#[derive(Deserialize)]
pub struct Excluder {
    pub singles: Vec<String>,
    pub ranges: Vec<(String, String)>,
}

impl Excluder {
    pub fn excludes(&self, s: &str) -> bool {
        self.singles.iter().any(|x| x == s)
            || self
                .ranges
                .iter()
                .any(|(lo, hi)| lo.as_str() <= s && s <= hi.as_str())
    }
}

/// A single-position matcher — the char-class grammar inside a capturing group.
#[derive(Deserialize)]
#[serde(tag = "k")]
pub enum Matcher {
    /// `_Literal`: an exact (possibly multi-char) string.
    #[serde(rename = "lit")]
    Lit { s: String },
    /// `_CharRange`: one char in `[lo, hi]`, minus exclusions. Bounds are single
    /// chars (serde decodes a 1-char JSON string straight into `char`).
    #[serde(rename = "range")]
    Range {
        lo: char,
        hi: char,
        excl: Option<Excluder>,
    },
    /// `_Union`: first arm (in order) whose match is not excluded.
    #[serde(rename = "union")]
    Union {
        arms: Vec<Matcher>,
        excl: Option<Excluder>,
    },
    /// `_Complement`: one char the inner matcher does NOT match here.
    #[serde(rename = "compl")]
    Compl { inner: Box<Matcher> },
    /// `_Group`: ordered congruence groups — `(member, group_index)`,
    /// longest-first (so multi-char members win), as Python sorts them.
    #[serde(rename = "group")]
    Group { members: Vec<(String, usize)> },
    /// `_Het`: the `{{U}}` wrapper — repetition frees every member each position
    /// (its `equal_unit` is a fresh match of the inner matcher).
    #[serde(rename = "het")]
    Het { inner: Box<Matcher> },
}

/// A sequence element — mirrors the supported `_compile` `*El` types.
#[derive(Deserialize)]
#[serde(tag = "k")]
pub enum Element {
    #[serde(rename = "lit")]
    Lit { s: String },
    #[serde(rename = "anchor")]
    Anchor { at: String },
    #[serde(rename = "group")]
    Group { m: Matcher, reps: Reps, het: bool },
    #[serde(rename = "backref")]
    BackRef { g: usize, reps: Reps },
}
