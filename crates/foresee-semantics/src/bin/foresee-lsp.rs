#[path = "../lsp.rs"]
mod lsp;
fn main() {
    let code = match lsp::serve(std::io::stdin().lock(), std::io::stdout().lock()) {
        Ok(code) => code,
        Err(error) => {
            eprintln!("language server transport error: {error}");
            2
        }
    };
    std::process::exit(code);
}
