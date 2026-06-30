use std::rc::Rc;
use serde_json::Value;
use crate::types::HMatch;

// ── Template ──────────────────────────────────────────────────────────────────

pub enum Part {
    Lit(String),
    Expr(Value),
}

pub struct Template {
    pub parts: Vec<Part>,
    pub fixed_point: bool,
}

// ── Expression evaluation ─────────────────────────────────────────────────────

pub fn eval_expr(d: &Value, current: &str, stages: &[Rc<HMatch>]) -> Result<String, String> {
    if let Some(lit) = d.get("lit") {
        return Ok(lit.as_str().unwrap_or("").to_string());
    }
    if d.get("cur").is_some() {
        return Ok(current.to_string());
    }
    if let Some(ref_val) = d.get("ref") {
        let arr = ref_val.as_array().ok_or("ref must be array")?;
        let stage_idx_opt = arr[0].as_u64();
        let is_count = arr[1].as_bool().unwrap_or(false);
        let path_opt = arr[2].as_array();

        let pipe_idx = stage_idx_opt
            .map(|n| n as usize)
            .unwrap_or_else(|| stages.len().saturating_sub(1));

        if pipe_idx >= stages.len() {
            return Err(format!("Moustache stage {} out of range", pipe_idx));
        }
        let stage_match = &stages[pipe_idx];

        if arr[2].is_null() {
            return Ok(stage_match.text.clone());
        }

        let path: Vec<usize> = path_opt
            .map(|p| p.iter().filter_map(|x| x.as_u64().map(|n| n as usize)).collect())
            .unwrap_or_default();

        let cap = stage_match
            .capture_at(&path)
            .ok_or_else(|| format!("Moustache capture {:?} out of range", path))?;

        if is_count {
            return Ok(cap.reps.len().to_string());
        }
        return Ok(cap.text.clone());
    }
    if let Some(parts) = d.get("cat") {
        let arr = parts.as_array().ok_or("cat must be array")?;
        let mut out = String::new();
        for p in arr {
            out.push_str(&eval_expr(p, current, stages)?);
        }
        return Ok(out);
    }
    if let Some(filter_name) = d.get("filter") {
        let name = filter_name.as_str().unwrap_or("");
        let src = d.get("src").ok_or("filter missing src")?;
        let value = eval_expr(src, current, stages)?;
        return match name {
            "trim" => Ok(value.trim().to_string()),
            "indent" => Ok(indent(&value)),
            _ => Err(format!("Unknown template filter: '{}'", name)),
        };
    }
    Err(format!("Unknown expression: {:?}", d))
}

fn indent(s: &str) -> String {
    if s.is_empty() {
        return String::new();
    }
    format!("\t{}", s.replace('\n', "\n\t"))
}

// ── Render ────────────────────────────────────────────────────────────────────

/// Returns (rendered_string, Some(moustache_spans)) or (rendered_string, None) if no exprs.
pub fn render_template(
    template: &Template,
    current: &str,
    stages: &[Rc<HMatch>],
) -> Result<(String, Option<Vec<(usize, usize)>>), String> {
    let mut out = String::new();
    let mut spans: Vec<(usize, usize)> = Vec::new();

    for part in &template.parts {
        match part {
            Part::Lit(s) => {
                out.push_str(s);
            }
            Part::Expr(d) => {
                let value = eval_expr(d, current, stages)?;
                let start = out.len();
                out.push_str(&value);
                spans.push((start, out.len()));
            }
        }
    }

    let spans_opt = if spans.is_empty() { None } else { Some(spans) };
    Ok((out, spans_opt))
}

// ── JSON deserialization ──────────────────────────────────────────────────────

pub fn template_from_json(d: &Value) -> Template {
    let fixed_point = d.get("fixed_point").and_then(|v| v.as_bool()).unwrap_or(false);
    let mut parts = Vec::new();
    if let Some(arr) = d.get("template").and_then(|v| v.as_array()) {
        for item in arr {
            if let Some(s) = item.as_str() {
                parts.push(Part::Lit(s.to_string()));
            } else if let Some(m) = item.get("m") {
                parts.push(Part::Expr(m.clone()));
            }
        }
    }
    Template { parts, fixed_point }
}
