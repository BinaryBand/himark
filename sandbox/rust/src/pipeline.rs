use std::rc::Rc;

use serde_json::Value;

use crate::template::{render_template, template_from_json, Template};
use crate::types::HMatch;
use crate::vm::{find_matches, prepare_elements, Element};

// ── Step ──────────────────────────────────────────────────────────────────────

pub struct Program {
    pub elements: Vec<Element>,
    pub fixed_point: bool,
}

pub enum Step {
    Program(Program),
    Template(Template),
}

impl Step {
    pub fn fixed_point(&self) -> bool {
        match self {
            Step::Program(p) => p.fixed_point,
            Step::Template(t) => t.fixed_point,
        }
    }
}

pub fn step_from_json(d: &Value) -> Result<Step, String> {
    let kind = d.get("kind").and_then(|v| v.as_str()).unwrap_or("");
    match kind {
        "program" => {
            let elements = prepare_elements(d.get("elements").unwrap_or(&Value::Array(vec![])));
            let fixed_point = d.get("fixed_point").and_then(|v| v.as_bool()).unwrap_or(false);
            Ok(Step::Program(Program { elements, fixed_point }))
        }
        "template" => Ok(Step::Template(template_from_json(d))),
        _ => Err(format!("Unknown step kind: {:?}", kind)),
    }
}

// ── _transform ────────────────────────────────────────────────────────────────

fn transform(steps: &[Step], text: &str, ancestors: &[Rc<HMatch>], committed: bool) -> Option<String> {
    if steps.is_empty() {
        return Some(text.to_string());
    }
    let (head, rest) = (&steps[0], &steps[1..]);

    match head {
        Step::Template(tmpl) => {
            let (full, spans) = render_template(tmpl, text, ancestors).ok()?;
            match spans {
                None => {
                    // No moustache expressions -- treat the whole rendered text as the stage.
                    let stage = Rc::new(HMatch {
                        text: full.clone(),
                        start: 0,
                        end: full.len(),
                        captures: vec![],
                    });
                    let mut new_ancestors = ancestors.to_vec();
                    new_ancestors.push(stage);
                    transform(rest, &full, &new_ancestors, true)
                }
                Some(ref span_list) => {
                    if rest.is_empty() {
                        return Some(full);
                    }
                    let mut owned: Vec<String> = Vec::new();
                    let mut last = 0;
                    for &(start, end) in span_list {
                        let payload = &full[start..end];
                        let stage = Rc::new(HMatch {
                            text: payload.to_string(),
                            start: 0,
                            end: payload.len(),
                            captures: vec![],
                        });
                        let mut new_ancestors = ancestors.to_vec();
                        new_ancestors.push(stage);
                        let sub = transform(rest, payload, &new_ancestors, true)?;
                        // We need to own all these strings for the final join.
                        owned.push(full[last..start].to_string());
                        owned.push(sub);
                        last = end;
                    }
                    owned.push(full[last..].to_string());
                    Some(owned.join(""))
                }
            }
        }

        Step::Program(prog) => {
            let mut pieces: Vec<String> = Vec::new();
            let mut last = 0;
            let mut matched = false;
            for m in find_matches(&prog.elements, text, ancestors) {
                matched = true;
                let m = Rc::new(m);
                let mut new_ancestors = ancestors.to_vec();
                new_ancestors.push(Rc::clone(&m));
                let sub = transform(rest, &m.text, &new_ancestors, committed)?;
                pieces.push(text[last..m.start].to_string());
                pieces.push(sub);
                last = m.end;
            }
            if !matched {
                if committed {
                    return Some(text.to_string());
                } else {
                    return None;
                }
            }
            pieces.push(text[last..].to_string());
            Some(pieces.join(""))
        }
    }
}

// ── _deltas ───────────────────────────────────────────────────────────────────

fn deltas(steps: &[Step], target: &str) -> Vec<(usize, usize, String)> {
    if steps.is_empty() {
        return vec![];
    }
    match &steps[0] {
        Step::Template(_) => {
            match transform(steps, target, &[], false) {
                Some(result) => vec![(0, target.len(), result)],
                None => vec![],
            }
        }
        Step::Program(prog) => {
            let rest = &steps[1..];
            let mut out = Vec::new();
            for m in find_matches(&prog.elements, target, &[]) {
                let m = Rc::new(m);
                let ancestors = vec![Rc::clone(&m)];
                if let Some(result) = transform(rest, &m.text, &ancestors, false) {
                    out.push((m.start, m.end, result));
                }
            }
            out
        }
    }
}

// ── _splice ───────────────────────────────────────────────────────────────────

fn splice(steps: &[Step], target: &str) -> String {
    let mut out = String::new();
    let mut last = 0;
    for (start, end, text) in deltas(steps, target) {
        out.push_str(&target[last..start]);
        out.push_str(&text);
        last = end;
    }
    out.push_str(&target[last..]);
    out
}

// ── _splice_to_fixed_point ────────────────────────────────────────────────────

fn splice_to_fixed_point(steps: &[Step], target: &str) -> Result<String, String> {
    let mut text = target.to_string();
    let cap = 8 * target.len() + 1024;
    let size_limit = 64 * target.len() + 65536;
    for _ in 0..cap {
        let result = splice(steps, &text);
        if result == text {
            return Ok(text);
        }
        text = result;
        if text.len() > size_limit {
            break;
        }
    }
    Err(
        "A `<=` statement did not settle \u{2014} the rule is not contracting toward a \
         fixed point (it grows or oscillates). Use `=>` for a single pass."
            .to_string(),
    )
}

// ── run_pipeline ──────────────────────────────────────────────────────────────

pub fn run_pipeline(pipeline: &[Value], target: &str) -> Result<String, String> {
    let mut result = target.to_string();
    for stmt_json in pipeline {
        let stmt_arr = stmt_json
            .as_array()
            .ok_or("statement must be array")?;
        let steps: Vec<Step> = stmt_arr
            .iter()
            .map(step_from_json)
            .collect::<Result<_, _>>()?;
        if steps.is_empty() {
            continue;
        }
        if steps[0].fixed_point() {
            result = splice_to_fixed_point(&steps, &result)?;
        } else {
            result = splice(&steps, &result);
        }
    }
    Ok(result)
}
