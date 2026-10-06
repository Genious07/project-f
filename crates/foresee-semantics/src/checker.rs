use crate::ast::{BodyProgram, Expr, ExprKind, Statement, StatementKind};
use crate::types::{ExpressionType, InferredType, ResourceRef, TypeAnalysis, TypeKind};
use crate::{error, DeclarationFailure, DeclarationSymbols, SourceSpan, SymbolId};
use foresee_syntax::Diagnostic;
use std::collections::BTreeMap;
use TypeKind::*;

type Env = BTreeMap<std::string::String, InferredType>;
struct Checker<'a> {
    symbols: &'a DeclarationSymbols,
    errors: Vec<Diagnostic>,
    expressions: Vec<ExpressionType>,
    snapshot_count: usize,
    node_count: usize,
    branch_base: Option<InferredType>,
}

pub(crate) fn check(
    program: BodyProgram,
    symbols: &DeclarationSymbols,
) -> Result<TypeAnalysis, DeclarationFailure> {
    let mut checker = Checker {
        symbols,
        errors: vec![],
        expressions: vec![],
        snapshot_count: 0,
        node_count: 0,
        branch_base: None,
    };
    for decision in program.decisions {
        let returns: Vec<_> = decision
            .body
            .iter()
            .enumerate()
            .filter_map(|(i, s)| matches!(s.kind, StatementKind::Return { .. }).then_some(i))
            .collect();
        if decision.body.is_empty() || returns != vec![decision.body.len() - 1] {
            checker.error(
                "F3203",
                "decision must end with exactly one return",
                &decision.span,
            );
        }
        let mut env = Env::new();
        for statement in &decision.body {
            checker.statement(statement, &mut env);
        }
    }
    if checker.errors.is_empty() {
        checker.expressions.sort_by_key(|e| e.node_id);
        Ok(TypeAnalysis {
            expressions: checker.expressions,
        })
    } else {
        Err(DeclarationFailure::Diagnostics(checker.errors))
    }
}
impl Checker<'_> {
    fn error(&mut self, code: &str, message: &str, span: &SourceSpan) {
        self.errors.push(error(code, message, span.clone().into()));
    }
    fn resource(&self, name: &str) -> ResourceRef {
        ResourceRef::resolve(name, self.symbols)
    }
    fn reserved(&self, name: &str) -> bool {
        name.starts_with("__")
            || matches!(
                self.symbols.lookup(name).map(|s| s.id()),
                Some(SymbolId::Resource(_) | SymbolId::Model(_))
            )
    }
    fn statement(&mut self, statement: &Statement, env: &mut Env) {
        match &statement.kind {
            StatementKind::Let {
                name,
                annotation,
                value,
            } => {
                if self.reserved(name) {
                    self.error("F3204", "reserved binding name", &statement.span);
                }
                if env.contains_key(name) {
                    self.error("F3003", "binding already exists", &statement.span);
                }
                let ty = self.expr(value, env);
                if let Some(annotation) = annotation {
                    let expected = TypeKind::annotation(&annotation.name);
                    let resource = if matches!(expected, Some(Int | String | Bool | Outcome)) {
                        None
                    } else {
                        ty.resource.as_ref().map(|r| r.name(self.symbols))
                    };
                    if expected != Some(ty.kind) || annotation.resource != resource {
                        self.error(
                            "F3300",
                            "annotation does not match inferred type and resource",
                            &statement.span,
                        );
                    }
                }
                env.insert(name.clone(), ty);
            }
            StatementKind::Return { value } => {
                let ty = self.expr(value, env);
                if self.branch_base.is_some() || ty.kind != Outcome {
                    self.error(
                        "F3203",
                        "return requires a decision outcome outside exploration",
                        &statement.span,
                    );
                }
            }
            StatementKind::Check { condition, message } => {
                let _ = message;
                if self.branch_base.is_none() {
                    self.error(
                        "F3100",
                        "check is only valid inside explore",
                        &statement.span,
                    );
                }
                if self.expr(condition, env).kind != Bool {
                    self.error("F3205", "check requires bool", &statement.span);
                }
            }
            StatementKind::Measure {
                type_name, value, ..
            } => {
                if self.branch_base.is_none() {
                    self.error(
                        "F3100",
                        "measure is only valid inside explore",
                        &statement.span,
                    );
                }
                if self.expr(value, env).kind != Int || type_name != "Int" {
                    self.error("F3205", "measure requires int", &statement.span);
                }
            }
        }
    }
    fn arguments(
        &mut self,
        args: &[Expr],
        expected: &[&[TypeKind]],
        env: &Env,
        span: &SourceSpan,
    ) -> Vec<InferredType> {
        let types: Vec<_> = args.iter().map(|a| self.expr(a, env)).collect();
        if types.len() != expected.len()
            || types
                .iter()
                .zip(expected)
                .any(|(ty, kinds)| !kinds.contains(&ty.kind))
        {
            self.error(
                "F3206",
                "argument count or type does not match signature",
                span,
            );
        }
        types
    }
    fn expr(&mut self, expr: &Expr, env: &Env) -> InferredType {
        let node_id = self.node_count;
        self.node_count += 1;
        let ty = self.infer(expr, env);
        self.expressions.push(ExpressionType {
            node_id,
            op: expr.kind.name(),
            span: expr.span.clone().into(),
            inferred_type: ty.report(self.symbols),
        });
        ty
    }
    fn infer(&mut self, expr: &Expr, env: &Env) -> InferredType {
        match &expr.kind {
            ExprKind::String { value } => {
                let _ = value;
                InferredType::scalar(String)
            }
            ExprKind::Int { .. } => InferredType::scalar(Int),
            ExprKind::Var { name } => env.get(name).cloned().unwrap_or_else(|| {
                self.error("F3004", "unknown binding", &expr.span);
                InferredType::scalar(Error)
            }),
            ExprKind::Snapshot { resource } => {
                let reference = self.resource(resource);
                if matches!(reference, ResourceRef::Unresolved(_)) {
                    self.error("F3005", "unknown resource", &expr.span);
                }
                self.snapshot_count += 1;
                InferredType {
                    kind: Snapshot,
                    resource: Some(reference),
                    metric_names: vec![],
                    lineage: Some(self.snapshot_count),
                }
            }
            ExprKind::Propose {
                model,
                plan_type,
                args,
            } => {
                if !matches!(
                    self.symbols.lookup(model).map(|s| s.id()),
                    Some(SymbolId::Model(_))
                ) {
                    self.error("F3006", "unknown model", &expr.span);
                }
                let types =
                    self.arguments(args, &[&[Snapshot], &[String], &[Int]], env, &expr.span);
                if plan_type != "Patch" {
                    self.error("F3208", "only Patch proposals are supported", &expr.span);
                }
                if args.len() == 3
                    && !matches!(&args[2].kind, ExprKind::Int { value } if value.as_u64().is_some_and(|n| (1..=4).contains(&n)))
                {
                    self.error(
                        "F3208",
                        "fixture proposal count must be a literal from 1 to 4",
                        &expr.span,
                    );
                }
                InferredType::derived(Plans, types.first().unwrap_or(&InferredType::scalar(Error)))
            }
            ExprKind::Explore {
                item,
                plans,
                base,
                body,
            } => {
                let plans = self.expr(plans, env);
                let base = self.expr(base, env);
                let resource =
                    if plans.kind != Plans || base.kind != Snapshot || base.resource.is_none() {
                        self.error(
                            "F3101",
                            "explore requires a plan set and a snapshot",
                            &expr.span,
                        );
                        ResourceRef::Unresolved("<error>".into())
                    } else {
                        base.resource.clone().expect("checked above")
                    };
                let mut local = env.clone();
                if local.contains_key(item) || self.reserved(item) {
                    self.error(
                        "F3204",
                        "exploration binding shadows an existing or reserved name",
                        &expr.span,
                    );
                }
                local.insert(
                    item.clone(),
                    InferredType {
                        kind: Plan,
                        resource: Some(resource.clone()),
                        metric_names: vec![],
                        lineage: base.lineage,
                    },
                );
                let previous = self.branch_base.replace(base.clone());
                let mut metrics = Vec::new();
                for statement in body {
                    self.statement(statement, &mut local);
                    if let StatementKind::Measure { name, .. } = &statement.kind {
                        if metrics.contains(name) {
                            self.error("F3209", "duplicate metric name", &statement.span);
                        }
                        metrics.push(name.clone());
                    }
                }
                self.branch_base = previous;
                InferredType {
                    kind: Trials,
                    resource: Some(resource),
                    metric_names: metrics,
                    lineage: base.lineage,
                }
            }
            ExprKind::Simulate {
                resource,
                method,
                args,
            } => {
                if self.branch_base.is_none() {
                    self.error("F3103", "simulate is only valid inside explore", &expr.span);
                }
                let resource = self.resource(resource);
                if method != "apply" || matches!(resource, ResourceRef::Unresolved(_)) {
                    self.error(
                        "F3210",
                        "simulate supports only a declared resource's apply method",
                        &expr.span,
                    );
                }
                self.arguments(args, &[&[Plan]], env, &expr.span);
                InferredType {
                    kind: Simulated,
                    resource: Some(resource),
                    metric_names: vec![],
                    lineage: self.branch_base.as_ref().and_then(|b| b.lineage),
                }
            }
            ExprKind::Call {
                target,
                method,
                args,
            } => {
                let (expected, result): (&[&[TypeKind]], TypeKind) = match method.as_str() {
                    "source_fields_unchanged" => {
                        (&[&[Snapshot, Simulated], &[Snapshot, Simulated]], Bool)
                    }
                    "valid_unit_arithmetic" => (&[&[Snapshot, Simulated]], Bool),
                    "unresolved_units" => (&[&[Snapshot, Simulated]], Int),
                    _ => {
                        self.error("F3210", "unknown resource method", &expr.span);
                        return InferredType::scalar(Error);
                    }
                };
                if matches!(self.resource(target), ResourceRef::Unresolved(_)) {
                    self.error("F3210", "unknown resource method", &expr.span);
                    return InferredType::scalar(Error);
                }
                self.arguments(args, expected, env, &expr.span);
                InferredType::scalar(result)
            }
            ExprKind::Select { trials, metric } => {
                let trials = self.expr(trials, env);
                if trials.kind != Trials {
                    self.error("F3105", "select requires exploration trials", &expr.span);
                } else if !trials.metric_names.contains(metric) {
                    self.error(
                        "F3106",
                        "metric is not measured by these trials",
                        &expr.span,
                    );
                }
                InferredType::derived(Selected, &trials)
            }
            ExprKind::Commit { selected, resource } => {
                let selected = self.expr(selected, env);
                let resource = self.resource(resource);
                if selected.kind != Selected || selected.resource.as_ref() != Some(&resource) {
                    self.error(
                        "F3107",
                        "commit requires Selected data for the same resource",
                        &expr.span,
                    );
                }
                InferredType {
                    kind: Outcome,
                    resource: Some(resource),
                    metric_names: vec![],
                    lineage: selected.lineage,
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use crate::types::TypeKind;
    use crate::{check_types, DeclarationFailure};
    const SOURCE: &str = include_str!("../../../examples/repair.fore");

    #[test]
    fn all_expression_forms_have_types_and_contiguous_ids() {
        let analysis = check_types(SOURCE).unwrap();
        for (id, expression) in analysis.expressions().iter().enumerate() {
            assert_eq!(expression.node_id, id);
            assert_ne!(expression.inferred_type.kind, TypeKind::Error);
        }
        for op in [
            "snapshot", "propose", "explore", "simulate", "call", "select", "commit", "string",
            "int", "var",
        ] {
            assert!(analysis.expressions().iter().any(|e| e.op == op), "{op}");
        }
    }
    #[test]
    fn snapshot_aliases_preserve_origin_and_new_snapshots_do_not() {
        let source = SOURCE.replace(
            "let plans =",
            "let alias = base; let second = snapshot catalog; let plans =",
        );
        let analysis = check_types(&source).unwrap();
        let snapshots: Vec<_> = analysis
            .expressions()
            .iter()
            .filter(|e| e.op == "snapshot")
            .collect();
        assert_eq!(
            snapshots[0].inferred_type.lineage.as_deref(),
            Some("snapshot:1")
        );
        assert_eq!(
            snapshots[1].inferred_type.lineage.as_deref(),
            Some("snapshot:2")
        );
        assert!(analysis
            .expressions()
            .iter()
            .filter(|e| e.op == "var" && e.inferred_type.kind == TypeKind::Snapshot)
            .all(|e| e.inferred_type.lineage.as_deref() == Some("snapshot:1")));
    }
    #[test]
    fn invalid_method_suppresses_argument_cascade_like_reference() {
        let source = SOURCE.replace("valid_unit_arithmetic(after)", "close(missing)");
        let Err(DeclarationFailure::Diagnostics(errors)) = check_types(&source) else {
            panic!("expected failure");
        };
        let codes: Vec<_> = errors.iter().map(|e| e.code.as_str()).collect();
        assert_eq!(codes, vec!["F3210", "F3205"]);
    }
    #[test]
    fn large_integer_is_not_narrowed_and_invalid_annotations_fail() {
        let source = SOURCE.replace("let base =", "let large: Int = 123456789012345678901234567890123456789012345678901234567890; let base =");
        assert!(check_types(&source).is_ok());
        let Err(DeclarationFailure::Diagnostics(errors)) =
            check_types(&source.replace("large: Int", "large: String"))
        else {
            panic!("expected failure");
        };
        assert_eq!(errors[0].code, "F3300");
    }
    #[test]
    fn type_analysis_does_not_claim_effect_or_ownership_checks() {
        let source = SOURCE.replace("Snapshot(catalog),", "").replace(
            "return commit chosen to catalog;",
            "let first = commit chosen to catalog; return commit chosen to catalog;",
        );
        assert!(check_types(&source).is_ok());
    }
}
