// plugin-hash — dev tool to compute the SHA-256 of a plugin according to ADR-0014.
//
// Usage: `cargo run --bin plugin-hash -- <plugin_dir>`
// Example: `cargo run --bin plugin-hash -- ../plugins-dev/rag`
//
// Output: 64-char hex string (sha256 of the plugin). Copy it to the
// plugin's `manifest.toml` under `[integrity].sha256`.

use std::path::PathBuf;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 2 {
        eprintln!("Usage: plugin-hash <plugin_dir>");
        return ExitCode::from(2);
    }
    let plugin_dir = PathBuf::from(&args[1]);
    if !plugin_dir.is_dir() {
        eprintln!("error: not a directory: {}", plugin_dir.display());
        return ExitCode::from(2);
    }
    match nexe_app_lib::compute_plugin_hash(&plugin_dir) {
        Ok(hash) => {
            println!("{}", hash);
            ExitCode::SUCCESS
        }
        Err(status) => {
            eprintln!("error computing hash (status {})", status);
            ExitCode::FAILURE
        }
    }
}
