use std::collections::HashSet;
use std::rc::Rc;
use serde_json::Value;

use crate::types::{Alphabet, Capture, HMatch, Reps, State};
use crate::matchers::{CharMatcher, ComplementMatcher, Exclusions, GroupMatcher, Matcher, ValueMatcher};

// ── Opcode constants ──────────────────────────────────────────────────────────

const LIT: u8 = 0;
const ANCHOR: u8 = 1;
const CHAR: u8 = 2;
const GROUP: u8 = 3;
const BACK_REF: u8 = 4;
const COUNT_REF: u8 = 5;
const STAGE_REF: u8 = 6;
const VALUE_RANGE: u8 = 7;
const DYN_RANGE: u8 = 8;
const COMPLEMENT: u8 = 10;
const SEQ_GROUP: u8 = 11;

// ── Element (prepared VM instruction) ─────────────────────────────────────────

pub enum Element {
    Lit(String),
    Anchor(u8),
    Char { lo: u32, hi: u32, excl: Option<Exclusions>, reps: Reps },
    Group { matcher: GroupMatcher, reps: Reps },
    Complement { inner_groups: Vec<Vec<String>>, reps: Reps },
    BackRef { idx: usize, reps: Reps },
    CountRef { idx: usize, reps: Reps },
    StageRef { stage: usize, path: Vec<usize>, reps: Reps },
    ValueRange { alph: Alphabet, lo_val: Option<f64>, hi_val: Option<f64>, wmin: usize, wmax: Option<usize>, excl: Option<Exclusions>, reps: Reps },
    DynRange { alph: Alphabet, lo_static: Option<String>, hi_static: Option<String>, lo_ref: Option<RefDesc>, hi_ref: Option<RefDesc>, excl: Option<Exclusions>, reps: Reps },
    SeqGroup { children: Vec<Element>, reps: Reps },
}

#[derive(Clone, Debug)]
pub struct RefDesc {
    pub kind: RefKind,
    pub idx: usize,
    pub path: Vec<usize>,
}

#[derive(Clone, Debug)]
pub enum RefKind {
    Back,
    Count,
    Stage,
}

// ── JSON deserialization helpers ──────────────────────────────────────────────

fn parse_reps(v: &Value) -> Reps {
    if v.is_null() {
        return Reps::exact(1);
    }
    let arr = match v.as_array() {
        Some(a) => a,
        None => return Reps::exact(1),
    };
    if arr.is_empty() {
        return Reps::exact(1);
    }
    if arr[0].as_str() == Some("#") {
        let idx = arr[1].as_u64().unwrap_or(0) as usize;
        return Reps { min: 0, max: None, allowed: None, count_ref: Some(idx) };
    }
    if arr[0].as_str() == Some("=") {
        let vals: HashSet<usize> = arr[1]
            .as_array()
            .unwrap_or(&vec![])
            .iter()
            .map(|x| x.as_u64().unwrap_or(0) as usize)
            .collect();
        let min = vals.iter().copied().min().unwrap_or(0);
        let max = vals.iter().copied().max();
        return Reps { min, max, allowed: Some(vals), count_ref: None };
    }
    let lo = arr[0].as_u64().unwrap_or(1) as usize;
    let hi_raw = arr[1].as_i64().unwrap_or(1);
    let hi = if hi_raw == -1 { None } else { Some(hi_raw as usize) };
    Reps { min: lo, max: hi, allowed: None, count_ref: None }
}

fn parse_excl(v: &Value) -> Option<Exclusions> {
    let arr = v.as_array()?;
    if arr.is_empty() {
        return None;
    }
    let singles: HashSet<char> = arr[0]
        .as_array()
        .unwrap_or(&vec![])
        .iter()
        .filter_map(|x| x.as_str()?.chars().next())
        .collect();
    let ranges: Vec<(char, char)> = arr[1]
        .as_array()
        .unwrap_or(&vec![])
        .iter()
        .filter_map(|pair| {
            let p = pair.as_array()?;
            let lo = p[0].as_str()?.chars().next()?;
            let hi = p[1].as_str()?.chars().next()?;
            Some((lo, hi))
        })
        .collect();
    let literals: Vec<String> = arr[2]
        .as_array()
        .unwrap_or(&vec![])
        .iter()
        .filter_map(|x| x.as_str().map(|s| s.to_string()))
        .collect();
    if singles.is_empty() && ranges.is_empty() && literals.is_empty() {
        return None;
    }
    Some(Exclusions { singles, ranges, literals })
}

fn parse_alphabet(v: &Value) -> Alphabet {
    let arr = v.as_array().expect("alphabet must be array");
    match arr[0].as_str().unwrap_or("") {
        "range" => {
            let lo = arr[1].as_u64().unwrap_or(0) as u32;
            let hi = arr[2].as_u64().unwrap_or(0) as u32;
            Alphabet::from_range(lo, hi)
        }
        _ => {
            let groups: Vec<Vec<String>> = arr[1]
                .as_array()
                .unwrap_or(&vec![])
                .iter()
                .map(|grp| {
                    grp.as_array()
                        .unwrap_or(&vec![])
                        .iter()
                        .filter_map(|x| x.as_str().map(|s| s.to_string()))
                        .collect()
                })
                .collect();
            Alphabet::from_groups(groups)
        }
    }
}

fn parse_groups(v: &Value) -> Vec<Vec<String>> {
    v.as_array()
        .unwrap_or(&vec![])
        .iter()
        .map(|grp| {
            grp.as_array()
                .unwrap_or(&vec![])
                .iter()
                .filter_map(|x| x.as_str().map(|s| s.to_string()))
                .collect()
        })
        .collect()
}

fn parse_ref_desc(v: &Value) -> Option<RefDesc> {
    // Ref format depends on context. For DYN_RANGE endpoints:
    // lo_ref / hi_ref are encoded as ["back"|"count"|"stage", idx, path?]
    let arr = v.as_array()?;
    let kind = match arr[0].as_str()? {
        "back" => RefKind::Back,
        "count" => RefKind::Count,
        "stage" => RefKind::Stage,
        _ => return None,
    };
    let idx = arr[1].as_u64().unwrap_or(0) as usize;
    let path: Vec<usize> = arr.get(2)
        .and_then(|p| p.as_array())
        .map(|p| p.iter().filter_map(|x| x.as_u64().map(|n| n as usize)).collect())
        .unwrap_or_default();
    Some(RefDesc { kind, idx, path })
}

pub fn prepare_elements(elements: &Value) -> Vec<Element> {
    let arr = match elements.as_array() {
        Some(a) => a,
        None => return vec![],
    };
    let mut out = Vec::with_capacity(arr.len());
    for el in arr {
        let el_arr = match el.as_array() {
            Some(a) => a,
            None => continue,
        };
        let opcode = el_arr[0].as_u64().unwrap_or(0) as u8;
        match opcode {
            LIT => {
                let s = el_arr[1].as_str().unwrap_or("").to_string();
                out.push(Element::Lit(s));
            }
            ANCHOR => {
                let kind = el_arr[1].as_u64().unwrap_or(0) as u8;
                out.push(Element::Anchor(kind));
            }
            CHAR => {
                let lo = el_arr[1].as_u64().unwrap_or(0) as u32;
                let hi = el_arr[2].as_u64().unwrap_or(0) as u32;
                let excl = parse_excl(&el_arr[3]);
                let reps = parse_reps(el_arr.last().unwrap_or(&Value::Null));
                out.push(Element::Char { lo, hi, excl, reps });
            }
            GROUP => {
                let groups = parse_groups(&el_arr[1]);
                let reps = parse_reps(el_arr.last().unwrap_or(&Value::Null));
                out.push(Element::Group { matcher: GroupMatcher::new(groups), reps });
            }
            BACK_REF => {
                let idx = el_arr[1].as_u64().unwrap_or(0) as usize;
                let reps = parse_reps(el_arr.last().unwrap_or(&Value::Null));
                out.push(Element::BackRef { idx, reps });
            }
            COUNT_REF => {
                let idx = el_arr[1].as_u64().unwrap_or(0) as usize;
                let reps = parse_reps(el_arr.last().unwrap_or(&Value::Null));
                out.push(Element::CountRef { idx, reps });
            }
            STAGE_REF => {
                let stage = el_arr[1].as_u64().unwrap_or(0) as usize;
                let path: Vec<usize> = el_arr[2]
                    .as_array()
                    .unwrap_or(&vec![])
                    .iter()
                    .filter_map(|x| x.as_u64().map(|n| n as usize))
                    .collect();
                let reps = parse_reps(el_arr.last().unwrap_or(&Value::Null));
                out.push(Element::StageRef { stage, path, reps });
            }
            VALUE_RANGE => {
                let alph = parse_alphabet(&el_arr[1]);
                let lo_val = if el_arr[2].is_null() { None } else { el_arr[2].as_f64() };
                let hi_val = if el_arr[3].is_null() { None } else { el_arr[3].as_f64() };
                let wmin = el_arr[4].as_u64().unwrap_or(1) as usize;
                let wmax = if el_arr[5].is_null() { None } else { el_arr[5].as_u64().map(|n| n as usize) };
                let excl = parse_excl(&el_arr[6]);
                let reps = parse_reps(el_arr.last().unwrap_or(&Value::Null));
                out.push(Element::ValueRange { alph, lo_val, hi_val, wmin, wmax, excl, reps });
            }
            DYN_RANGE => {
                let alph = parse_alphabet(&el_arr[1]);
                let lo_static = el_arr[2].as_str().map(|s| s.to_string());
                let hi_static = el_arr[3].as_str().map(|s| s.to_string());
                let lo_ref = if el_arr[4].is_null() { None } else { parse_ref_desc(&el_arr[4]) };
                let hi_ref = if el_arr[5].is_null() { None } else { parse_ref_desc(&el_arr[5]) };
                let excl = parse_excl(&el_arr[6]);
                let reps = parse_reps(el_arr.last().unwrap_or(&Value::Null));
                out.push(Element::DynRange { alph, lo_static, hi_static, lo_ref, hi_ref, excl, reps });
            }
            COMPLEMENT => {
                let inner_groups = parse_groups(&el_arr[1]);
                let reps = parse_reps(el_arr.last().unwrap_or(&Value::Null));
                out.push(Element::Complement { inner_groups, reps });
            }
            SEQ_GROUP => {
                let children = prepare_elements(&el_arr[1]);
                let reps = parse_reps(el_arr.last().unwrap_or(&Value::Null));
                out.push(Element::SeqGroup { children, reps });
            }
            _ => {}
        }
    }
    out
}

// ── Referent resolution ───────────────────────────────────────────────────────

fn resolve_referent_desc(desc: &RefDesc, state: &State, text: &str) -> Option<String> {
    let caps = &state.captures;
    match desc.kind {
        RefKind::Back => {
            if desc.idx < caps.len() {
                let span = caps[desc.idx].span;
                Some(text[span.0..span.1].to_string())
            } else {
                None
            }
        }
        RefKind::Count => {
            if desc.idx < caps.len() {
                Some(caps[desc.idx].rep_count().to_string())
            } else {
                None
            }
        }
        RefKind::Stage => {
            let stages = &state.stages;
            if desc.idx < stages.len() {
                let m = &stages[desc.idx];
                if desc.path.is_empty() {
                    Some(m.text.clone())
                } else {
                    m.capture_at(&desc.path).map(|c| c.text.clone())
                }
            } else {
                None
            }
        }
    }
}

fn resolve_back(idx: usize, state: &State, text: &str) -> Option<String> {
    let limit = state.root_len.min(state.captures.len());
    if idx < limit {
        let span = state.captures[idx].span;
        Some(text[span.0..span.1].to_string())
    } else {
        None
    }
}

fn resolve_count(idx: usize, state: &State) -> Option<String> {
    let limit = state.root_len.min(state.captures.len());
    if idx < limit {
        Some(state.captures[idx].rep_count().to_string())
    } else {
        None
    }
}

fn resolve_stage(stage_idx: usize, path: &[usize], state: &State) -> Option<String> {
    let stages = &state.stages;
    if stage_idx >= stages.len() {
        return None;
    }
    let m = &stages[stage_idx];
    if path.is_empty() {
        Some(m.text.clone())
    } else {
        m.capture_at(path).map(|c| c.text.clone())
    }
}

fn resolve_reps(reps: &Reps, state: &State) -> Option<Reps> {
    if let Some(cr) = reps.count_ref {
        let limit = state.root_len.min(state.captures.len());
        if cr >= limit {
            return None;
        }
        let k = state.captures[cr].rep_count();
        Some(Reps::exact(k))
    } else {
        Some(reps.clone())
    }
}

// ── Anchor check ──────────────────────────────────────────────────────────────

fn check_anchor(kind: u8, text: &str, pos: usize) -> bool {
    match kind {
        0 => pos == 0 || text.as_bytes().get(pos - 1) == Some(&b'\n'),
        1 => pos == text.len() || text.as_bytes().get(pos) == Some(&b'\n'),
        2 => pos == 0,
        _ => pos == text.len(),
    }
}

// ── _counts equivalent ────────────────────────────────────────────────────────

fn counts(reps: &Reps, built: usize) -> Vec<usize> {
    let mut ks: Vec<usize> = (1..=built).rev().filter(|&k| reps.accepts(k)).collect();
    if reps.accepts(0) {
        ks.push(0);
    }
    ks
}

// ── Core VM ───────────────────────────────────────────────────────────────────

pub fn run_program(elements: &[Element], idx: usize, text: &str, pos: usize, state: &mut State) -> Option<usize> {
    if idx >= elements.len() {
        return Some(pos);
    }

    match &elements[idx] {
        Element::Lit(s) => {
            if text[pos..].starts_with(s.as_str()) {
                run_program(elements, idx + 1, text, pos + s.len(), state)
            } else {
                None
            }
        }

        Element::Anchor(kind) => {
            if check_anchor(*kind, text, pos) {
                run_program(elements, idx + 1, text, pos, state)
            } else {
                None
            }
        }

        Element::Char { lo, hi, excl, reps } => {
            let reps = resolve_reps(reps, state)?;
            let matcher = CharMatcher { lo: *lo, hi: *hi, excl: excl.clone() };
            run_matcher(&matcher, &reps, elements, idx + 1, state, text, pos)
        }

        Element::Group { matcher, reps } => {
            let reps = resolve_reps(reps, state)?;
            run_matcher(matcher, &reps, elements, idx + 1, state, text, pos)
        }

        Element::Complement { inner_groups, reps } => {
            let reps = resolve_reps(reps, state)?;
            let matcher = ComplementMatcher { inner_groups: inner_groups.clone() };
            run_matcher(&matcher, &reps, elements, idx + 1, state, text, pos)
        }

        Element::BackRef { idx: ref_idx, reps } => {
            let reps = resolve_reps(reps, state)?;
            let referent = resolve_back(*ref_idx, state, text);
            match_referent(referent.as_deref(), &reps, elements, idx + 1, text, pos, state)
        }

        Element::CountRef { idx: ref_idx, reps } => {
            let reps = resolve_reps(reps, state)?;
            let referent = resolve_count(*ref_idx, state);
            match_referent(referent.as_deref(), &reps, elements, idx + 1, text, pos, state)
        }

        Element::StageRef { stage, path, reps } => {
            let reps = resolve_reps(reps, state)?;
            let referent = resolve_stage(*stage, path, state);
            match_referent(referent.as_deref(), &reps, elements, idx + 1, text, pos, state)
        }

        Element::ValueRange { alph, lo_val, hi_val, wmin, wmax, excl, reps } => {
            let reps = resolve_reps(reps, state)?;
            let matcher = ValueMatcher {
                alph: alph.clone(),
                lo_val: *lo_val,
                hi_val: *hi_val,
                wmin: *wmin,
                wmax: *wmax,
                excl: excl.clone(),
            };
            run_matcher(&matcher, &reps, elements, idx + 1, state, text, pos)
        }

        Element::DynRange { alph, lo_static, hi_static, lo_ref, hi_ref, excl, reps } => {
            let reps = resolve_reps(reps, state)?;
            let lower: Option<String> = match lo_ref {
                Some(r) => resolve_referent_desc(r, state, text),
                None => lo_static.clone(),
            };
            let upper: Option<String> = match hi_ref {
                Some(r) => resolve_referent_desc(r, state, text),
                None => hi_static.clone(),
            };
            if lo_ref.is_some() && lower.is_none() { return None; }
            if hi_ref.is_some() && upper.is_none() { return None; }

            let matcher = build_dyn_matcher(alph, lower.as_deref(), upper.as_deref(), excl.clone())?;
            run_matcher(&matcher, &reps, elements, idx + 1, state, text, pos)
        }

        Element::SeqGroup { children, reps } => {
            let reps = resolve_reps(reps, state)?;
            match_seq_group(children, &reps, elements, idx + 1, text, pos, state)
        }
    }
}

fn build_dyn_matcher(alph: &Alphabet, lower: Option<&str>, upper: Option<&str>, excl: Option<Exclusions>) -> Option<ValueMatcher> {
    let lo_val: Option<f64> = match lower {
        Some(s) => Some(alph.value(s)?),
        None => None,
    };
    let hi_val: Option<f64> = match upper {
        Some(s) => Some(alph.value(s)?),
        None => None,
    };
    let wmin;
    let wmax;
    match (lower, upper) {
        (Some(l), Some(u)) => {
            let llen = l.chars().count();
            let ulen = u.chars().count();
            wmin = llen.min(ulen);
            wmax = Some(llen.max(ulen));
        }
        (Some(l), None) => {
            wmin = l.chars().count();
            wmax = None;
        }
        (None, Some(u)) => {
            wmin = 1;
            wmax = Some(u.chars().count());
        }
        (None, None) => {
            wmin = 1;
            wmax = None;
        }
    }
    Some(ValueMatcher { alph: alph.clone(), lo_val, hi_val, wmin, wmax, excl })
}

fn try_zero(
    reps: &Reps,
    elements: &[Element],
    next_idx: usize,
    state: &mut State,
    text: &str,
    pos: usize,
) -> Option<usize> {
    if !reps.accepts(0) {
        return None;
    }
    let mark = state.captures.len();
    state.captures.push(Capture {
        text: String::new(),
        span: (pos, pos),
        reps: vec![],
        subs: vec![],
        count: 0,
    });
    let result = run_program(elements, next_idx, text, pos, state);
    if result.is_none() {
        state.captures.truncate(mark);
    }
    result
}

fn run_matcher(
    matcher: &dyn Matcher,
    reps: &Reps,
    elements: &[Element],
    next_idx: usize,
    state: &mut State,
    text: &str,
    pos: usize,
) -> Option<usize> {
    let first_end = match matcher.match_one(text, pos) {
        Some(e) if e > pos => e,
        _ => return try_zero(reps, elements, next_idx, state, text, pos),
    };

    // Collect valid char-boundary end-offsets between pos and first_end (longest first).
    let char_ends: Vec<usize> = {
        let mut ends = Vec::new();
        let mut cur = pos;
        for ch in text[pos..first_end].chars() {
            cur += ch.len_utf8();
            ends.push(cur);
        }
        ends.into_iter().rev().collect()
    };

    for end_at in char_ends {
        let first = &text[pos..end_at];
        if !matcher.accepts(first) {
            continue;
        }
        let mut rep_list: Vec<(usize, usize)> = vec![(pos, end_at)];
        let mut ends: Vec<usize> = vec![end_at];
        let mut current = end_at;

        loop {
            if let Some(max) = reps.max {
                if rep_list.len() >= max {
                    break;
                }
            }
            match matcher.equal_unit(text, current, first) {
                Some(nxt) if nxt > current => {
                    rep_list.push((current, nxt));
                    ends.push(nxt);
                    current = nxt;
                }
                _ => break,
            }
        }

        for k in counts(reps, rep_list.len()) {
            let end = if k == 0 { pos } else { ends[k - 1] };
            let reps_slice = rep_list[..k.min(rep_list.len())].to_vec();
            let mark = state.captures.len();
            state.captures.push(Capture {
                text: String::new(),
                span: (pos, end),
                reps: reps_slice,
                subs: vec![],
                count: k as i64,
            });
            let result = run_program(elements, next_idx, text, end, state);
            if result.is_some() {
                return result;
            }
            state.captures.truncate(mark);
        }
    }

    try_zero(reps, elements, next_idx, state, text, pos)
}

fn match_referent(
    referent: Option<&str>,
    reps: &Reps,
    elements: &[Element],
    next_idx: usize,
    text: &str,
    pos: usize,
    state: &mut State,
) -> Option<usize> {
    let ref_str = match referent {
        Some(r) => r,
        None => {
            // None means unresolvable -- fail
            return None;
        }
    };

    if ref_str.is_empty() {
        // Empty referent: always matches 0-width, reps.min times.
        let mark = state.captures.len();
        state.captures.push(Capture {
            text: String::new(),
            span: (pos, pos),
            reps: vec![(pos, pos); reps.min],
            subs: vec![],
            count: -1,
        });
        let result = run_program(elements, next_idx, text, pos, state);
        if result.is_none() {
            state.captures.truncate(mark);
        }
        return result;
    }

    // Collect how many times referent repeats at pos.
    let mut ends: Vec<usize> = vec![pos];
    let mut current = pos;
    loop {
        if let Some(max) = reps.max {
            if ends.len() - 1 >= max {
                break;
            }
        }
        if text[current..].starts_with(ref_str) {
            current += ref_str.len();
            ends.push(current);
        } else {
            break;
        }
    }

    for k in counts(reps, ends.len() - 1) {
        let end = ends[k];
        // Per-rep byte spans (ends[i-1]..ends[i]); only the count is consulted.
        let reps_vec: Vec<(usize, usize)> =
            (0..k).map(|i| (ends[i], ends[i + 1])).collect();
        let mark = state.captures.len();
        state.captures.push(Capture {
            text: text[pos..end].to_string(),
            span: (pos, end),
            reps: reps_vec,
            subs: vec![],
            count: -1,
        });
        let result = run_program(elements, next_idx, text, end, state);
        if result.is_some() {
            return result;
        }
        state.captures.truncate(mark);
    }
    None
}

fn match_seq_group(
    children: &[Element],
    reps: &Reps,
    elements: &[Element],
    next_idx: usize,
    text: &str,
    pos: usize,
    state: &mut State,
) -> Option<usize> {
    // Collect runs: each run is (end_pos, sub_captures)
    let mut runs: Vec<(usize, Vec<Capture>)> = Vec::new();
    let mut current = pos;

    // Mirror Python's _State.root: children see only captures that existed before
    // this SEQ_GROUP started. The outermost SEQ_GROUP sets the boundary; nested
    // ones leave it unchanged (their root_len stays at the outer boundary).
    let prev_root_len = state.root_len;
    let snap_len = state.captures.len();
    if state.root_len == usize::MAX {
        state.root_len = snap_len;
    }

    loop {
        if let Some(max) = reps.max {
            if runs.len() >= max {
                break;
            }
        }
        let snap_len = state.captures.len();
        let end = run_program(children, 0, text, current, state);
        match end {
            Some(e) if e > current => {
                let sub_caps: Vec<Capture> = state.captures.drain(snap_len..).collect();
                runs.push((e, sub_caps));
                current = e;
            }
            _ => {
                state.captures.truncate(snap_len);
                break;
            }
        }
    }

    // Restore root_len before trying continuations (elements after this SEQ_GROUP
    // are back in the outer scope and should see all parent captures again).
    state.root_len = prev_root_len;

    for k in counts(reps, runs.len()) {
        let end = if k == 0 { pos } else { runs[k - 1].0 };
        let rep_texts: Vec<(usize, usize)> = (0..k)
            .map(|i| {
                let start = if i == 0 { pos } else { runs[i - 1].0 };
                (start, runs[i].0)
            })
            .collect();
        let subs: Vec<Capture> = (0..k).flat_map(|i| runs[i].1.clone()).collect();
        let cap_text = text[pos..end].to_string();
        let mark = state.captures.len();
        state.captures.push(Capture {
            text: cap_text,
            span: (pos, end),
            reps: rep_texts,
            subs,
            count: -1,
        });
        let result = run_program(elements, next_idx, text, end, state);
        if result.is_some() {
            return result;
        }
        state.captures.truncate(mark);
    }
    None
}

// ── Finalize match ────────────────────────────────────────────────────────────

fn finalize_capture(cap: &mut Capture, text: &str, start: usize) {
    if cap.count >= 0 {
        let count = cap.count as usize;
        cap.reps.truncate(count);
    }
    cap.text = text[cap.span.0..cap.span.1].to_string();
    cap.span = (cap.span.0 - start, cap.span.1 - start);
    for sub in &mut cap.subs {
        finalize_capture(sub, text, start);
    }
}

fn finalize(text: &str, start: usize, end: usize, state: State) -> HMatch {
    let mut captures = state.captures;
    for cap in &mut captures {
        finalize_capture(cap, text, start);
    }
    HMatch {
        text: text[start..end].to_string(),
        start,
        end,
        captures,
    }
}

// ── Public find_matches ───────────────────────────────────────────────────────

pub fn find_matches(elements: &[Element], text: &str, stages: &[Rc<HMatch>]) -> Vec<HMatch> {
    let mut matches = Vec::new();
    let n = text.len();
    let mut pos = 0;
    while pos < n {
        // stages.to_vec() now clones only the Rc pointers (refcount bumps), not
        // the underlying ancestor text/capture trees -- O(stages), not O(payload).
        let mut state = State::new(stages.to_vec());
        match run_program(elements, 0, text, pos, &mut state) {
            Some(end) if end > pos => {
                let m = finalize(text, pos, end, state);
                pos = end;
                matches.push(m);
            }
            _ => {
                // advance by one UTF-8 character
                let ch = text[pos..].chars().next().unwrap();
                pos += ch.len_utf8();
            }
        }
    }
    matches
}
