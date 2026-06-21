//! `himark_rs` — the native (Rust) matching backend for the `himark/engine` seam.
//!
//! A deliberately tiny FFI surface (JSON in, JSON out) keeps this robust across
//! PyO3 versions and lets the Python side ([rust.py](../../himark/engine/backend/rust.py))
//! own all object construction:
//!
//!   * `compile(program_json) -> Program`   parses the translated element list
//!   * `Program.run(text) -> matches_json`   runs the backtracking match loop
//!
//! The structural subset only (see `program.rs` / `_translate.py`); the Python
//! backend handles everything else by fallback.

// The match loop is a continuation-passing port; its recursive helpers thread the
// pattern, position, and capture state by hand, so a few run wide.
#![allow(clippy::too_many_arguments)]

use pyo3::prelude::*;

mod matcher;
mod program;
pub mod parser;

use program::Element;

/// A compiled pattern (the parsed element list), reused across many `run` calls.
#[pyclass]
struct Program {
    elements: Vec<Element>,
}

#[pymethods]
impl Program {
    /// Run the pattern over `text`, returning matches as a JSON string:
    /// `[{"s":start,"e":end,"caps":[{"s":rel_start,"e":rel_end,"reps":[..]}]}]`.
    fn run(&self, text: &str) -> PyResult<String> {
        let chars: Vec<char> = text.chars().collect();
        let matches = matcher::find_matches(&self.elements, &chars);
        serde_json::to_string(&matches)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("himark_rs encode: {e}")))
    }
}

/// Parse a translated program (JSON from `_translate.to_json`) into a `Program`.
#[pyfunction]
fn compile(program_json: &str) -> PyResult<Program> {
    let elements: Vec<Element> = serde_json::from_str(program_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("himark_rs program: {e}")))?;
    Ok(Program { elements })
}

/// Parse a raw HMK statement, returning `[RootNode, ...]` as a JSON string.
#[pyfunction]
fn parse(source: &str) -> PyResult<String> {
    parser::parse(source).map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

#[pymodule]
fn himark_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compile, m)?)?;
    m.add_function(wrap_pyfunction!(parse, m)?)?;
    m.add_class::<Program>()?;
    Ok(())
}
