/// Phase 3: semantic resolution — convert phase-2 raw nodes into typed AST.
/// Mirrors himark/parser/phase3.py.

use crate::parser::count::parse_count;
use crate::parser::nodes::{ChildNode, RootNode, SemanticNode};
use crate::parser::phase2::{tokenize, RawBrace, RawNode};
use crate::parser::shape::is_sequence_brace;
use crate::parser::text::{
    brace_end, inner_of, split_top, strict_split, strip_unescaped, unescape,
};

pub fn resolve(raw: Vec<RawNode>) -> Result<RootNode, String> {
    let children = raw
        .into_iter()
        .map(|n| match n {
            RawNode::Leaf(s) => Ok(ChildNode::Leaf { content: s }),
            RawNode::Brace(b) => resolve_brace_node(b),
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(RootNode::new(children))
}

fn resolve_brace_node(b: RawBrace) -> Result<ChildNode, String> {
    let semantic = if is_sequence_brace(&b.content) {
        resolve_sequence_brace(&b.content)?
    } else {
        resolve_brace(&b.content)?
    };
    let count = match b.count_src {
        Some(ref cs) => Some(parse_count(cs)?),
        None => None,
    };
    Ok(ChildNode::BraceGroup {
        content: b.content,
        semantic,
        count,
    })
}

// ── Grouping brace ────────────────────────────────────────────────────────────

fn resolve_sequence_brace(content: &str) -> Result<SemanticNode, String> {
    let raw = tokenize(content)?;
    let inner_root = resolve(raw)?;
    Ok(SemanticNode::Sequence {
        children: inner_root.children,
    })
}

// ── Alphabet brace ────────────────────────────────────────────────────────────

fn ambient_alpha() -> SemanticNode {
    SemanticNode::CharRange {
        start: "\x00".to_string(),
        end: "\u{10ffff}".to_string(),
        exclusions: vec![],
    }
}

fn resolve_universe(expr: &str) -> Result<SemanticNode, String> {
    let expr = strip_unescaped(expr);
    let expr = if expr.starts_with('{') && brace_end(&expr) == Some(expr.len()) {
        inner_of(&expr).to_string()
    } else {
        expr
    };
    resolve_brace(&expr)
}

fn resolve_bounds(parts: &[String]) -> Result<SemanticNode, String> {
    let floor_s = strip_unescaped(&parts[0]);
    let alpha_s = strip_unescaped(&parts[1]);
    let ceil_s = strip_unescaped(&parts[2]);

    let alpha = if alpha_s.is_empty() {
        ambient_alpha()
    } else {
        resolve_universe(&alpha_s)?
    };

    let (lower, lower_ref) = bound_endpoint(&floor_s)?;
    let (upper, upper_ref) = bound_endpoint(&ceil_s)?;

    if lower.is_none() && upper.is_none() && lower_ref.is_none() && upper_ref.is_none() {
        return Err("A bound needs a floor or a ceiling: got '{:U:}'".to_string());
    }

    Ok(SemanticNode::ValueRange {
        alpha: Box::new(alpha),
        lower,
        upper,
        lower_ref: lower_ref.map(Box::new),
        upper_ref: upper_ref.map(Box::new),
        exclusions: vec![],
    })
}

fn bound_endpoint(s: &str) -> Result<(Option<String>, Option<SemanticNode>), String> {
    if s.is_empty() {
        return Ok((None, None));
    }
    if let Some(r) = resolve_reference(s) {
        return Ok((None, Some(r)));
    }
    Ok((Some(member_value(s)), None))
}

fn resolve_reference(content: &str) -> Option<SemanticNode> {
    let s = strip_unescaped(content);

    // $digits — back-ref
    if let Some(rest) = s.strip_prefix('$') {
        if !rest.is_empty() && rest.chars().all(|c| c.is_ascii_digit()) {
            if let Ok(group) = rest.parse::<usize>() {
                return Some(SemanticNode::BackRef { group });
            }
        }
    }

    // #digits — count-ref
    if let Some(rest) = s.strip_prefix('#') {
        if !rest.is_empty() && rest.chars().all(|c| c.is_ascii_digit()) {
            if let Ok(group) = rest.parse::<usize>() {
                return Some(SemanticNode::CountRef { group });
            }
        }
    }

    // digits$path — stage-ref
    try_stage_ref(&s)
}

fn try_stage_ref(s: &str) -> Option<SemanticNode> {
    let dollar = s.find('$')?;
    let stage_str = &s[..dollar];
    if stage_str.is_empty() || !stage_str.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let stage: usize = stage_str.parse().ok()?;
    let path_str = &s[dollar + 1..];
    if path_str.is_empty() {
        return Some(SemanticNode::StageRef { stage, path: vec![] });
    }
    let parts: Vec<&str> = path_str.split('.').collect();
    if parts.iter().any(|p| p.is_empty() || !p.chars().all(|c| c.is_ascii_digit())) {
        return None;
    }
    let path: Vec<usize> = parts.iter().filter_map(|p| p.parse().ok()).collect();
    if path.len() == parts.len() {
        Some(SemanticNode::StageRef { stage, path })
    } else {
        None
    }
}

fn resolve_brace(content: &str) -> Result<SemanticNode, String> {
    let sa = strip_unescaped(content);

    // Anchors
    match sa.as_str() {
        "@^" => return Ok(SemanticNode::Anchor { at: "line_start".to_string() }),
        "@$" => return Ok(SemanticNode::Anchor { at: "line_end".to_string() }),
        "@^^" => return Ok(SemanticNode::Anchor { at: "scope_start".to_string() }),
        "@$$" => return Ok(SemanticNode::Anchor { at: "scope_end".to_string() }),
        _ => {}
    }

    if let Some(r) = resolve_reference(content) {
        return Ok(r);
    }

    // Value bound: three top-level colons
    let colon_parts = split_top(":", content);
    if colon_parts.len() == 3 {
        return resolve_bounds(&colon_parts);
    }

    // Object nesting {{X}}: whole content is a single nested brace
    let stripped = strip_unescaped(content);
    if stripped.starts_with('{') && brace_end(&stripped) == Some(stripped.len()) {
        let inner = resolve_brace(inner_of(&stripped))?;
        if let Some(grps) = arm_group(&inner) {
            return Ok(SemanticNode::GroupClass { groups: grps });
        }
        return Ok(SemanticNode::Heterogeneous {
            inner: Box::new(inner),
        });
    }

    // Complement prefix {!expr}
    let is_complement = content.starts_with('!');
    let content_work = if is_complement { &content[1..] } else { content };

    // Split on top-level commas
    let raw_arms = split_top(",", content_work);
    let mut arms: Vec<String> = Vec::with_capacity(raw_arms.len());
    for a in &raw_arms {
        let stripped_a = strip_unescaped(a);
        if !stripped_a.is_empty() && stripped_a != *a {
            if raw_arms.len() == 1 {
                let arm = if stripped_a.starts_with('{') {
                    stripped_a
                } else {
                    a.clone()
                };
                arms.push(arm);
            } else {
                return Err(format!(
                    "Unexpected whitespace in '{{{content}}}': remove spaces around ','"
                ));
            }
        } else {
            arms.push(a.clone());
        }
    }

    // Separate exclusion arms
    let mut exclusions: Vec<String> = Vec::new();
    for a in &arms {
        if !a.starts_with('!') {
            continue;
        }
        let operand = a[1..].trim();
        if operand.starts_with('{') && brace_end(operand) == Some(operand.len()) {
            for m in split_top(",", inner_of(operand)) {
                exclusions.push(m.trim().to_string());
            }
        } else {
            exclusions.push(operand.to_string());
        }
    }
    let include_arms: Vec<String> = arms.into_iter().filter(|a| !a.starts_with('!')).collect();
    if include_arms.is_empty() {
        return Err(format!("Empty brace group: {{{content}}}"));
    }

    let mut node = classify_arms(&include_arms, &exclusions)?;
    if is_complement {
        node = SemanticNode::Complement { inner: Box::new(node) };
    }
    Ok(node)
}

fn member_value(arm: &str) -> String {
    match singleton_value(arm) {
        Some(v) => v,
        None => unescape(arm),
    }
}

fn apply_member_exclusions(members: Vec<String>, exclusions: &[String]) -> Vec<String> {
    if exclusions.is_empty() {
        return members;
    }
    let singles: std::collections::HashSet<&str> =
        exclusions.iter().filter(|e| !e.contains("..")).map(|s| s.as_str()).collect();
    let ranges: Vec<(&str, &str)> = exclusions
        .iter()
        .filter(|e| e.contains(".."))
        .filter_map(|e| {
            let idx = e.find("..")?;
            Some((&e[..idx], &e[idx + 2..]))
        })
        .collect();
    members
        .into_iter()
        .filter(|m| {
            !singles.contains(m.as_str())
                && !ranges.iter().any(|(lo, hi)| lo <= &m.as_str() && m.as_str() <= *hi)
        })
        .collect()
}

fn arm_group(node: &SemanticNode) -> Option<Vec<Vec<String>>> {
    match node {
        SemanticNode::Literal { content } => Some(vec![vec![content.clone()]]),
        SemanticNode::GroupClass { groups } => {
            if groups.iter().all(|g| g.len() == 1) {
                // Flat primitives → fold into one group
                Some(vec![groups.iter().flat_map(|g| g.iter().cloned()).collect()])
            } else {
                // Ordered alphabet of objects → keep as-is
                Some(groups.clone())
            }
        }
        _ => None,
    }
}

fn attach_exclusions(node: SemanticNode, exclusions: Vec<String>) -> SemanticNode {
    if exclusions.is_empty() {
        return node;
    }
    match node {
        SemanticNode::CharRange { start, end, .. } => {
            SemanticNode::CharRange { start, end, exclusions }
        }
        SemanticNode::ValueRange { alpha, lower, upper, lower_ref, upper_ref, .. } => {
            SemanticNode::ValueRange { alpha, lower, upper, lower_ref, upper_ref, exclusions }
        }
        SemanticNode::Union { options, .. } => SemanticNode::Union { options, exclusions },
        other => other,
    }
}

fn classify_arms(arms: &[String], exclusions: &[String]) -> Result<SemanticNode, String> {
    if arms.len() == 1 {
        let node = resolve_arm(&arms[0])?;
        return Ok(attach_exclusions(node, exclusions.to_vec()));
    }
    let resolved: Vec<SemanticNode> = arms
        .iter()
        .map(|a| resolve_arm(a))
        .collect::<Result<Vec<_>, _>>()?;
    let per_arm: Vec<Option<Vec<Vec<String>>>> =
        resolved.iter().map(arm_group).collect();

    if per_arm.iter().all(|g| g.is_some()) {
        let mut groups: Vec<Vec<String>> = Vec::new();
        for arm_groups in per_arm.into_iter().flatten() {
            for grp in arm_groups {
                let kept = apply_member_exclusions(grp, exclusions);
                if !kept.is_empty() {
                    groups.push(kept);
                }
            }
        }
        return Ok(SemanticNode::GroupClass { groups });
    }

    Ok(attach_exclusions(
        SemanticNode::Union { options: resolved, exclusions: vec![] },
        exclusions.to_vec(),
    ))
}

fn singleton_value(expr: &str) -> Option<String> {
    let expr = strip_unescaped(expr);
    if expr.is_empty() {
        return None;
    }
    if expr.starts_with('!') && expr.len() > 1 {
        return None;
    }
    if expr.starts_with('{') {
        let end = brace_end(&expr)?;
        let inner_val = singleton_value(&expr[1..end - 1])?;
        let rest = &expr[end..];
        if rest.is_empty() {
            return Some(inner_val);
        }
        // [N] exact count?
        if rest.starts_with('[') && rest.ends_with(']') {
            let count_src = &rest[1..rest.len() - 1];
            if count_src.chars().all(|c| c.is_ascii_digit()) {
                let n: usize = count_src.parse().ok()?;
                return Some(inner_val.repeat(n));
            }
        }
        return None;
    }
    if split_top(",", &expr).len() > 1 || split_top("..", &expr).len() > 1 {
        return None;
    }
    Some(unescape(&expr))
}

fn resolve_arm(arm: &str) -> Result<SemanticNode, String> {
    let parts = strict_split("..", arm, arm)?;
    let svals: Vec<Option<String>> = parts.iter().map(|p| singleton_value(p)).collect();

    if parts.len() == 1 {
        let part = &parts[0];
        let sval = &svals[0];
        if part.starts_with('{') {
            if let Some(v) = sval {
                return Ok(SemanticNode::Literal { content: v.clone() });
            }
            return resolve_universe(part);
        }
        return Ok(SemanticNode::Literal { content: unescape(part) });
    }

    if parts.len() == 2 {
        match (&svals[0], &svals[1]) {
            (Some(av), Some(bv)) => {
                if av.chars().count() == 1 && bv.chars().count() == 1 {
                    return Ok(SemanticNode::CharRange {
                        start: av.clone(),
                        end: bv.clone(),
                        exclusions: vec![],
                    });
                }
                return Ok(SemanticNode::ValueRange {
                    alpha: Box::new(ambient_alpha()),
                    lower: Some(av.clone()),
                    upper: Some(bv.clone()),
                    lower_ref: None,
                    upper_ref: None,
                    exclusions: vec![],
                });
            }
            _ => {
                return Err(format!(
                    "A value bound is written '{{floor:alphabet:ceiling}}' with ':', \
                     not '..': got {arm:?}"
                ))
            }
        }
    }

    Err(format!(
        "Too many '..' separators (a value bound uses ':', as in \
         '{{floor:alphabet:ceiling}}'): got {arm:?}"
    ))
}
