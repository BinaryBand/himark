mod matchers;
mod pipeline;
mod template;
mod types;
mod vm;

use std::io::{self, Read};
use std::process;

use serde_json::{json, Value};

use pipeline::run_pipeline;

fn main() {
    let mut input = String::new();
    if io::stdin().read_to_string(&mut input).is_err() {
        println!("{}", json!({"error": "failed to read stdin"}));
        process::exit(1);
    }

    let payload: Value = match serde_json::from_str(&input) {
        Ok(v) => v,
        Err(e) => {
            let msg = format!("JSON parse error: {}", e);
            eprintln!("{}", msg);
            println!("{}", json!({"error": msg}));
            process::exit(1);
        }
    };

    let pipeline = match payload.get("pipeline").and_then(|v| v.as_array()) {
        Some(p) => p,
        None => {
            let msg = "missing 'pipeline' array";
            eprintln!("{}", msg);
            println!("{}", json!({"error": msg}));
            process::exit(1);
        }
    };

    let target = match payload.get("target").and_then(|v| v.as_str()) {
        Some(t) => t,
        None => {
            let msg = "missing 'target' string";
            eprintln!("{}", msg);
            println!("{}", json!({"error": msg}));
            process::exit(1);
        }
    };

    match run_pipeline(pipeline, target) {
        Ok(result) => {
            println!("{}", json!({"result": result}));
        }
        Err(e) => {
            eprintln!("{}", e);
            println!("{}", json!({"error": e}));
            process::exit(1);
        }
    }
}
