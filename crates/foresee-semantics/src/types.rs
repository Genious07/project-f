use crate::{DeclarationSymbols, ResourceId, SymbolId};
use foresee_syntax::Span;
use serde::Serialize;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TypeKind {
    Int,
    String,
    Bool,
    Snapshot,
    Plan,
    Plans,
    Simulated,
    Trials,
    Selected,
    Outcome,
    Error,
}
impl TypeKind {
    pub(crate) fn annotation(name: &str) -> Option<Self> {
        Some(match name {
            "Int" => Self::Int,
            "String" => Self::String,
            "Bool" => Self::Bool,
            "Snapshot" => Self::Snapshot,
            "Plan" => Self::Plan,
            "Plans" => Self::Plans,
            "Simulated" => Self::Simulated,
            "Trials" => Self::Trials,
            "Selected" => Self::Selected,
            "DecisionResult" => Self::Outcome,
            _ => return None,
        })
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum ResourceRef {
    Known(ResourceId),
    Unresolved(String),
}
impl ResourceRef {
    pub fn resolve(name: &str, symbols: &DeclarationSymbols) -> Self {
        match symbols.lookup(name).map(|s| s.id()) {
            Some(SymbolId::Resource(id)) => Self::Known(id),
            _ => Self::Unresolved(name.into()),
        }
    }
    pub fn name(&self, symbols: &DeclarationSymbols) -> String {
        match self {
            Self::Known(id) => symbols
                .symbols()
                .iter()
                .find(|s| s.id() == SymbolId::Resource(*id))
                .expect("resource ID belongs to this checker")
                .name()
                .into(),
            Self::Unresolved(name) => name.clone(),
        }
    }
}
#[derive(Clone, Debug)]
pub(crate) struct InferredType {
    pub kind: TypeKind,
    pub resource: Option<ResourceRef>,
    pub metric_names: Vec<String>,
    pub lineage: Option<usize>,
}
impl InferredType {
    pub fn scalar(kind: TypeKind) -> Self {
        Self {
            kind,
            resource: None,
            metric_names: vec![],
            lineage: None,
        }
    }
    pub fn derived(kind: TypeKind, origin: &Self) -> Self {
        Self {
            kind,
            resource: origin.resource.clone(),
            metric_names: vec![],
            lineage: origin.lineage,
        }
    }
    pub fn report(&self, symbols: &DeclarationSymbols) -> TypeDescription {
        TypeDescription {
            kind: self.kind,
            resource: self.resource.as_ref().map(|r| r.name(symbols)),
            metric_names: self.metric_names.clone(),
            lineage: self.lineage.map(|id| format!("snapshot:{id}")),
        }
    }
}
/// Inspection output only. This is not typed IR or an execution capability.
#[derive(Debug, Serialize)]
pub struct TypeDescription {
    pub kind: TypeKind,
    pub resource: Option<String>,
    pub metric_names: Vec<String>,
    pub lineage: Option<String>,
}
#[derive(Debug, Serialize)]
pub struct ExpressionType {
    pub node_id: usize,
    pub op: &'static str,
    pub span: Span,
    pub inferred_type: TypeDescription,
}
#[derive(Debug, Serialize)]
pub struct TypeAnalysis {
    pub(crate) expressions: Vec<ExpressionType>,
}
impl TypeAnalysis {
    pub fn expressions(&self) -> &[ExpressionType] {
        &self.expressions
    }
}
