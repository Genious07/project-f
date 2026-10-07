//! Owned body nodes decoded only from the local syntax frontend.
use crate::SourceSpan;
use serde::Deserialize;

#[derive(Deserialize)]
pub(crate) struct BodyProgram {
    pub decisions: Vec<Decision>,
}
#[derive(Deserialize)]
pub(crate) struct Decision {
    pub effects: Vec<(String, String)>,
    pub body: Vec<Statement>,
    pub span: SourceSpan,
}
#[derive(Deserialize)]
pub(crate) struct Statement {
    #[serde(flatten)]
    pub kind: StatementKind,
    pub span: SourceSpan,
}
#[derive(Deserialize)]
#[serde(tag = "kind", content = "data", rename_all = "snake_case")]
pub(crate) enum StatementKind {
    Let {
        name: String,
        annotation: Option<Annotation>,
        value: Expr,
    },
    Return {
        value: Expr,
    },
    Check {
        condition: Expr,
        message: String,
    },
    Measure {
        name: String,
        #[serde(rename = "type")]
        type_name: String,
        value: Expr,
    },
}
#[derive(Deserialize)]
pub(crate) struct Annotation {
    pub name: String,
    pub resource: Option<String>,
}
#[derive(Deserialize)]
pub(crate) struct Expr {
    #[serde(flatten)]
    pub kind: ExprKind,
    pub span: SourceSpan,
}
#[derive(Deserialize)]
#[serde(tag = "kind", content = "data", rename_all = "snake_case")]
pub(crate) enum ExprKind {
    String {
        value: String,
    },
    Int {
        value: serde_json::Number,
    },
    Var {
        name: String,
    },
    Snapshot {
        resource: String,
    },
    Propose {
        model: String,
        plan_type: String,
        args: Vec<Expr>,
    },
    Explore {
        item: String,
        plans: Box<Expr>,
        base: Box<Expr>,
        body: Vec<Statement>,
    },
    Simulate {
        resource: String,
        method: String,
        args: Vec<Expr>,
    },
    Call {
        target: String,
        method: String,
        args: Vec<Expr>,
    },
    Select {
        trials: Box<Expr>,
        metric: String,
    },
    Commit {
        selected: Box<Expr>,
        resource: String,
    },
}
impl ExprKind {
    pub fn name(&self) -> &'static str {
        match self {
            Self::String { .. } => "string",
            Self::Int { .. } => "int",
            Self::Var { .. } => "var",
            Self::Snapshot { .. } => "snapshot",
            Self::Propose { .. } => "propose",
            Self::Explore { .. } => "explore",
            Self::Simulate { .. } => "simulate",
            Self::Call { .. } => "call",
            Self::Select { .. } => "select",
            Self::Commit { .. } => "commit",
        }
    }
}
