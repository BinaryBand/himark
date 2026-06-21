use crate::parser::nodes::CountSpec;

/// Parse a count modifier string (the content between `[` and `]`) into a
/// `CountSpec`. Mirrors himark/parser/_count.py.
pub fn parse_count(src: &str) -> Result<CountSpec, String> {
    let src = src.trim();

    // [#i] — count-reference: repeat exactly as many times as group i.
    if let Some(rest) = src.strip_prefix('#') {
        if !rest.is_empty() && rest.chars().all(|c| c.is_ascii_digit()) {
            let group: usize = rest
                .parse()
                .map_err(|_| format!("Invalid count expression: [{src}]"))?;
            return Ok(CountSpec::Ref { group });
        }
    }

    // [a,b,c] — explicit union of exact counts.
    if src.contains(',') {
        let mut values: Vec<usize> = src
            .split(',')
            .map(|p| {
                p.trim()
                    .parse::<usize>()
                    .map_err(|_| format!("Invalid count expression: [{src}]"))
            })
            .collect::<Result<Vec<_>, _>>()?;
        values.sort_unstable();
        values.dedup();
        return Ok(CountSpec::Set { values, group: None });
    }

    // [n] or [x..y] (x and y each optional).
    if src.contains("..") {
        let idx = src.find("..").unwrap();
        let lo_str = &src[..idx];
        let hi_str = &src[idx + 2..];
        let min: usize = if lo_str.is_empty() {
            0
        } else {
            lo_str
                .parse()
                .map_err(|_| format!("Invalid count expression: [{src}]"))?
        };
        let max: Option<usize> = if hi_str.is_empty() {
            None
        } else {
            Some(
                hi_str
                    .parse()
                    .map_err(|_| format!("Invalid count expression: [{src}]"))?,
            )
        };
        return Ok(CountSpec::Range { min, max, group: None });
    }

    // [n] — exact count.
    if src.chars().all(|c| c.is_ascii_digit()) && !src.is_empty() {
        let n: usize = src
            .parse()
            .map_err(|_| format!("Invalid count expression: [{src}]"))?;
        return Ok(CountSpec::Range { min: n, max: Some(n), group: None });
    }

    Err(format!("Invalid count expression: [{src}]"))
}
