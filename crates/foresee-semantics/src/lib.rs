//! Staged declaration and type analysis. Success does not authorize execution.
mod ast;
pub mod canonical;
mod checker;
pub mod ir;
mod signatures;
pub mod types;
use foresee_syntax::{Diagnostic, Span};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct ResourceId(usize);
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct ModelId(usize);
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct DecisionId(usize);

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", content = "id", rename_all = "snake_case")]
pub enum SymbolId {
    Resource(ResourceId),
    Model(ModelId),
    Decision(DecisionId),
}

#[derive(Debug, Serialize)]
pub struct Symbol {
    id: SymbolId,
    name: String,
    span: Span,
}
impl Symbol {
    pub fn id(&self) -> SymbolId {
        self.id
    }
    pub fn name(&self) -> &str {
        &self.name
    }
    pub fn span(&self) -> &Span {
        &self.span
    }
}

/// Constructible only after declaration checking. Not a CheckedProgram or executable IR.
#[derive(Debug, Serialize)]
pub struct DeclarationSymbols {
    symbols: Vec<Symbol>,
    #[serde(skip)]
    by_name: BTreeMap<String, usize>,
}
impl DeclarationSymbols {
    pub fn symbols(&self) -> &[Symbol] {
        &self.symbols
    }
    pub fn lookup(&self, name: &str) -> Option<&Symbol> {
        self.by_name.get(name).map(|index| &self.symbols[*index])
    }
}

// Private conversion boundary for trusted, locally generated syntax version 1.
// Bodies and effects are deliberately not interpreted in this declaration milestone.
#[derive(Deserialize)]
struct Program {
    resources: Vec<TypedDeclaration>,
    models: Vec<TypedDeclaration>,
    decisions: Vec<DecisionDeclaration>,
}
#[derive(Deserialize)]
struct TypedDeclaration {
    name: String,
    type_name: String,
    span: SourceSpan,
}
#[derive(Deserialize)]
struct DecisionDeclaration {
    name: String,
    span: SourceSpan,
}
#[derive(Clone, Deserialize)]
struct SourceSpan {
    start: usize,
    end: usize,
    line: usize,
    column: usize,
}
impl From<SourceSpan> for Span {
    fn from(s: SourceSpan) -> Self {
        Self {
            start: s.start,
            end: s.end,
            line: s.line,
            column: s.column,
        }
    }
}

#[derive(Debug)]
pub enum DeclarationFailure {
    Diagnostics(Vec<Diagnostic>),
    /// A frontend/backend schema mismatch, distinct from a user's source error.
    FrontendContract(String),
}
fn error(code: &str, message: &str, span: Span) -> Diagnostic {
    Diagnostic {
        code: code.into(),
        message: message.into(),
        span,
    }
}
fn synthetic_span() -> Span {
    Span {
        start: 0,
        end: 0,
        line: 1,
        column: 1,
    }
}

/// Parse source and check cardinality, supported declaration types, and unique names.
/// Effects, statements, types, lineage, ownership, and IR generation are not checked here.
pub fn check_declarations(source: &str) -> Result<DeclarationSymbols, DeclarationFailure> {
    let syntax = foresee_syntax::parse(source).map_err(DeclarationFailure::Diagnostics)?;
    let program: Program = serde_json::from_value(syntax)
        .map_err(|e| DeclarationFailure::FrontendContract(e.to_string()))?;
    let mut diagnostics = Vec::new();
    if program.resources.len() != 1 || program.models.len() != 1 || program.decisions.len() != 1 {
        diagnostics.push(error(
            "F3200",
            "bootstrap requires exactly one resource, model, and decision",
            synthetic_span(),
        ));
    }
    let mut symbols = Vec::new();
    for (index, item) in program.resources.into_iter().enumerate() {
        let span: Span = item.span.into();
        if item.type_name != "Catalog" {
            diagnostics.push(error("F3201", "unsupported resource type", span.clone()));
        }
        symbols.push(Symbol {
            id: SymbolId::Resource(ResourceId(index)),
            name: item.name,
            span,
        });
    }
    for (index, item) in program.models.into_iter().enumerate() {
        let span: Span = item.span.into();
        if item.type_name != "Planner" {
            diagnostics.push(error("F3201", "unsupported model type", span.clone()));
        }
        symbols.push(Symbol {
            id: SymbolId::Model(ModelId(index)),
            name: item.name,
            span,
        });
    }
    for (index, item) in program.decisions.into_iter().enumerate() {
        symbols.push(Symbol {
            id: SymbolId::Decision(DecisionId(index)),
            name: item.name,
            span: item.span.into(),
        });
    }
    let mut by_name = BTreeMap::new();
    let mut duplicate = false;
    for (index, symbol) in symbols.iter().enumerate() {
        if by_name.insert(symbol.name.clone(), index).is_some() {
            duplicate = true;
        }
    }
    if duplicate {
        diagnostics.push(error(
            "F3000",
            "top-level names must be unique",
            synthetic_span(),
        ));
    }
    if diagnostics.is_empty() {
        Ok(DeclarationSymbols { symbols, by_name })
    } else {
        Err(DeclarationFailure::Diagnostics(diagnostics))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const SOURCE: &str = include_str!("../../../examples/repair.fore");
    #[test]
    fn symbols_resolve_in_separate_namespaces() {
        let table = check_declarations(SOURCE).unwrap();
        assert!(matches!(
            table.lookup("catalog").unwrap().id(),
            SymbolId::Resource(_)
        ));
        assert!(matches!(
            table.lookup("planner").unwrap().id(),
            SymbolId::Model(_)
        ));
        assert!(matches!(
            table.lookup("repair_catalog").unwrap().id(),
            SymbolId::Decision(_)
        ));
        assert!(table.lookup("base").is_none());
        assert!(table.lookup("missing").is_none());
        assert_eq!(table.symbols().len(), 3);
    }
    #[test]
    fn failure_cannot_expose_a_symbol_table() {
        let source = SOURCE.replace("model planner:", "model catalog:");
        let Err(DeclarationFailure::Diagnostics(errors)) = check_declarations(&source) else {
            panic!("expected diagnostics");
        };
        assert_eq!(errors.len(), 1);
        assert_eq!(errors[0].code, "F3000");
    }
    #[test]
    fn declaration_success_does_not_claim_body_validity() {
        let source = "resource a: Catalog; model b: Planner; decision c() ! {} { return missing; }";
        assert!(check_declarations(source).is_ok());
    }
    #[test]
    fn repeated_checks_have_stable_symbols_and_spans() {
        let first = serde_json::to_value(check_declarations(SOURCE).unwrap()).unwrap();
        let second = serde_json::to_value(check_declarations(SOURCE).unwrap()).unwrap();
        assert_eq!(first, second);
    }
}

/// Infer expression types after declarations pass. Effects, origin validation, and
/// affine ownership are deferred. The returned analysis is not executable IR.
pub fn check_types(source: &str) -> Result<types::TypeAnalysis, DeclarationFailure> {
    let symbols = check_declarations(source)?;
    let syntax = foresee_syntax::parse(source).map_err(DeclarationFailure::Diagnostics)?;
    let program: ast::BodyProgram = serde_json::from_value(syntax)
        .map_err(|e| DeclarationFailure::FrontendContract(e.to_string()))?;
    checker::check(&program, &symbols, checker::Stage::Types)
}

/// Validate declared effects and branch restrictions in addition to types.
/// Origin validation and affine ownership remain pending. No executable IR is emitted.
pub fn check_effects(source: &str) -> Result<types::TypeAnalysis, DeclarationFailure> {
    let symbols = check_declarations(source)?;
    let syntax = foresee_syntax::parse(source).map_err(DeclarationFailure::Diagnostics)?;
    let program: ast::BodyProgram = serde_json::from_value(syntax)
        .map_err(|e| DeclarationFailure::FrontendContract(e.to_string()))?;
    checker::check(&program, &symbols, checker::Stage::Effects)
}

/// Check resource and snapshot origins after declarations, types, and effects.
/// Selection ownership and executable IR generation remain pending.
pub fn check_lineage(source: &str) -> Result<types::TypeAnalysis, DeclarationFailure> {
    let symbols = check_declarations(source)?;
    let syntax = foresee_syntax::parse(source).map_err(DeclarationFailure::Diagnostics)?;
    let program: ast::BodyProgram = serde_json::from_value(syntax)
        .map_err(|e| DeclarationFailure::FrontendContract(e.to_string()))?;
    checker::check(&program, &symbols, checker::Stage::Lineage)
}

/// Check single-use selection capabilities and exactly one simulation per branch.
/// Includes earlier stages; the returned analysis is not executable IR.
pub fn check_ownership(source: &str) -> Result<types::TypeAnalysis, DeclarationFailure> {
    let symbols = check_declarations(source)?;
    let syntax = foresee_syntax::parse(source).map_err(DeclarationFailure::Diagnostics)?;
    let program: ast::BodyProgram = serde_json::from_value(syntax)
        .map_err(|e| DeclarationFailure::FrontendContract(e.to_string()))?;
    checker::check(&program, &symbols, checker::Stage::Ownership)
}
