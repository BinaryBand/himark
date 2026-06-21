pub mod count;
pub mod nodes;
pub mod phase0;
pub mod phase1;
pub mod phase2;
pub mod phase3;
pub mod shape;
pub mod text;

use nodes::RootNode;

/// Parse a raw HMK statement into one resolved `RootNode` per `=>` step.
/// Returns a JSON string `[RootNode, ...]` on success, or an error message.
pub fn parse(source: &str) -> Result<String, String> {
    let steps = phase0::split_statement(source);
    let mut roots: Vec<RootNode> = Vec::with_capacity(steps.len());
    for (i, step) in steps.iter().enumerate() {
        let preprocessed = phase1::preprocess(step, i == 0)?;
        let raw = phase2::tokenize(&preprocessed)?;
        let root = phase3::resolve(raw)?;
        roots.push(root);
    }
    serde_json::to_string(&roots).map_err(|e| format!("himark_rs encode: {e}"))
}
