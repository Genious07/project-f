//! Native compiler budgets, enforced for library callers as well as CLI input.
pub const MAX_SOURCE_BYTES: usize = 1_000_000;
pub const MAX_TOKENS: usize = 8192; // Excludes EOF.
pub const MAX_IDENTIFIER_BYTES: usize = 128;
pub const MAX_INTEGER_DIGITS: usize = 4096;
pub const MAX_STRING_BYTES: usize = 65_536; // Decoded UTF-8.
pub const MAX_COLLECTION_ITEMS: usize = 128;
pub const MAX_EXPRESSION_DEPTH: usize = 16;
pub const MAX_DIAGNOSTICS: usize = 64;
pub const MAX_JSON_DEPTH: usize = 128;
