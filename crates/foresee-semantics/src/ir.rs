//! Checked IR body for schema 0.0.3. See `canonical` for complete program identity.
use crate::ast::{BodyProgram, Expr, ExprKind, Statement, StatementKind};
use crate::types::{ExpressionType, TypeAnalysis, TypeKind};
use crate::{checker, DeclarationFailure};
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::BTreeSet;

/// Only native successful checking can construct this artifact. It has no digest
/// yet and is not an execution capability. No external AST/IR ingestion is exposed.
#[derive(Debug, Serialize)]
#[serde(transparent)]
pub struct IrBody(pub(crate) Value);

struct CheckedProgram {
    program: BodyProgram,
    analysis: TypeAnalysis,
}
impl CheckedProgram {
    fn from_source(source: &str) -> Result<Self, DeclarationFailure> {
        let symbols = crate::check_declarations(source)?;
        let syntax = foresee_syntax::parse(source).map_err(DeclarationFailure::Diagnostics)?;
        let program = serde_json::from_value(syntax)
            .map_err(|e| DeclarationFailure::FrontendContract(e.to_string()))?;
        let analysis = checker::check(&program, &symbols, checker::Stage::Ownership)?;
        Ok(Self { program, analysis })
    }
}

pub fn lower_source(source: &str) -> Result<IrBody, DeclarationFailure> {
    let checked = CheckedProgram::from_source(source)?;
    let mut lowerer = Lowerer {
        types: checked.analysis.expressions().iter(),
        next_id: 0,
    };
    let declarations = |items: &[crate::TypedDeclaration]| -> Vec<Value> {
        items
            .iter()
            .map(|d| json!({"name":d.name,"type_name":d.type_name}))
            .collect()
    };
    let mut decisions = vec![];
    for decision in &checked.program.decisions {
        let effects: Vec<_> = decision
            .effects
            .iter()
            .collect::<BTreeSet<_>>()
            .into_iter()
            .map(|(kind, target)| json!({"kind":kind,"target":target}))
            .collect();
        decisions.push(json!({"name":decision.name,"effects":effects,"body":lowerer.statements(&decision.body)?}));
    }
    if lowerer.types.next().is_some() {
        return Err(contract("unconsumed expression types"));
    }
    Ok(IrBody(
        json!({"schema_version":"0.0.3","resources":declarations(&checked.program.resources),"models":declarations(&checked.program.models),"decisions":decisions}),
    ))
}
fn contract(message: &str) -> DeclarationFailure {
    DeclarationFailure::FrontendContract(message.into())
}
struct Lowerer<'a> {
    types: std::slice::Iter<'a, ExpressionType>,
    next_id: usize,
}
impl Lowerer<'_> {
    fn statements(&mut self, body: &[Statement]) -> Result<Vec<Value>, DeclarationFailure> {
        body.iter().map(|s| self.statement(s)).collect()
    }
    fn statement(&mut self, statement: &Statement) -> Result<Value, DeclarationFailure> {
        Ok(match &statement.kind {
            StatementKind::Let { name, value, .. } => {
                json!({"statement":"let","name":name,"value":self.expr(value)?})
            }
            StatementKind::Return { value } => {
                json!({"statement":"return","value":self.expr(value)?})
            }
            StatementKind::Check { condition, message } => {
                json!({"statement":"check","condition":self.expr(condition)?,"message":message})
            }
            StatementKind::Measure {
                name,
                type_name,
                value,
            } => {
                json!({"statement":"measure","name":name,"type":type_name,"value":self.expr(value)?})
            }
        })
    }
    fn args(&mut self, args: &[Expr]) -> Result<Vec<Value>, DeclarationFailure> {
        args.iter().map(|e| self.expr(e)).collect()
    }
    fn expr(&mut self, expr: &Expr) -> Result<Value, DeclarationFailure> {
        let ty = self
            .types
            .next()
            .ok_or_else(|| contract("missing expression type"))?;
        if ty.node_id != self.next_id
            || ty.op != expr.kind.name()
            || ty.span != expr.span.clone().into()
            || ty.inferred_type.kind == TypeKind::Error
        {
            return Err(contract("expression/type traversal mismatch"));
        }
        self.next_id += 1;
        // Evaluate children explicitly in checker order, independent of JSON map ordering.
        let mut value = match &expr.kind {
            ExprKind::String { value } => json!({"value":value}),
            ExprKind::Int { value } => json!({"value":value}),
            ExprKind::Var { name } => json!({"name":name}),
            ExprKind::Snapshot { resource } => json!({"resource":resource}),
            ExprKind::Propose {
                model,
                plan_type,
                args,
            } => json!({"model":model,"plan_type":plan_type,"args":self.args(args)?}),
            ExprKind::Explore {
                item,
                plans,
                base,
                body,
            } => {
                let plans = self.expr(plans)?;
                let base = self.expr(base)?;
                let body = self.statements(body)?;
                json!({"item":item,"plans":plans,"base":base,"body":body})
            }
            ExprKind::Simulate {
                resource,
                method,
                args,
            } => json!({"resource":resource,"method":method,"args":self.args(args)?}),
            ExprKind::Call {
                target,
                method,
                args,
            } => json!({"target":target,"method":method,"args":self.args(args)?}),
            ExprKind::Select { trials, metric } => {
                json!({"trials":self.expr(trials)?,"metric":metric})
            }
            ExprKind::Commit { selected, resource } => {
                json!({"selected":self.expr(selected)?,"resource":resource})
            }
        };
        value["op"] = json!(ty.op);
        value["inferred_type"] = json!(ty.inferred_type);
        Ok(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const SOURCE: &str = include_str!("../../../examples/repair.fore");
    #[test]
    fn source_metadata_and_effect_order_do_not_change_body() {
        let source = SOURCE
            .replace("let base =", "let base: Snapshot<catalog> =")
            .replace(
                "Snapshot(catalog),",
                "Commit(catalog), Snapshot(catalog), Snapshot(catalog),",
            );
        let first = serde_json::to_value(lower_source(SOURCE).unwrap()).unwrap();
        let second =
            serde_json::to_value(lower_source(&format!("// extra\n{source}")).unwrap()).unwrap();
        assert_eq!(first, second);
        assert!(first.get("program_digest").is_none());
    }
    #[test]
    fn errors_in_each_phase_prevent_lowering() {
        for source in [
            SOURCE.replace("model planner: Planner;", ""),
            SOURCE.replace("let base =", "let base: Int ="),
            SOURCE.replace("Commit(catalog)", "Commit(planner)"),
            SOURCE.replace("from base", "from snapshot catalog"),
            SOURCE.replace(
                "return commit chosen",
                "let done = commit chosen to catalog; return commit chosen",
            ),
        ] {
            assert!(matches!(
                lower_source(&source),
                Err(DeclarationFailure::Diagnostics(_))
            ));
        }
    }
    #[test]
    fn missing_type_table_is_a_contract_error_not_a_panic() {
        let syntax = foresee_syntax::parse(SOURCE).unwrap();
        let program: BodyProgram = serde_json::from_value(syntax).unwrap();
        let mut lowerer = Lowerer {
            types: [].iter(),
            next_id: 0,
        };
        assert!(matches!(
            lowerer.statements(&program.decisions[0].body),
            Err(DeclarationFailure::FrontendContract(_))
        ));
    }
    #[test]
    fn mismatched_type_table_is_rejected() {
        let mut checked = CheckedProgram::from_source(SOURCE).unwrap();
        checked.analysis.expressions.swap(0, 1);
        let mut lowerer = Lowerer {
            types: checked.analysis.expressions().iter(),
            next_id: 0,
        };
        assert!(matches!(
            lowerer.statements(&checked.program.decisions[0].body),
            Err(DeclarationFailure::FrontendContract(_))
        ));
    }
}
