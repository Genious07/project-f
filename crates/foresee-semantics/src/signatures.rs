//! Closed operation registry for the supported Catalog/Planner subset.
use crate::types::TypeKind::*;
use crate::{types::TypeKind, SymbolId};

pub(crate) fn effect_target_matches(kind: &str, symbol: Option<SymbolId>) -> bool {
    matches!(
        (kind, symbol),
        (
            "Snapshot" | "Explore" | "Commit",
            Some(SymbolId::Resource(_))
        ) | ("Infer", Some(SymbolId::Model(_)))
    )
}
pub(crate) fn forbidden_in_branch(op: &str) -> bool {
    matches!(op, "snapshot" | "propose" | "explore" | "select" | "commit")
}
pub(crate) fn method(name: &str) -> Option<(&'static [&'static [TypeKind]], TypeKind)> {
    match name {
        "source_fields_unchanged" => {
            Some((&[&[Snapshot, Simulated], &[Snapshot, Simulated]], Bool))
        }
        "valid_unit_arithmetic" => Some((&[&[Snapshot, Simulated]], Bool)),
        "unresolved_units" => Some((&[&[Snapshot, Simulated]], Int)),
        _ => None,
    }
}
