use crate::ast::{BodyProgram, Expr, ExprKind, Statement, StatementKind};
use crate::signatures;
use crate::types::{
    ExpressionType, InferredType, ResourceRef, SelectionId, TypeAnalysis, TypeKind,
};
use crate::{error, DeclarationFailure, DeclarationSymbols, SourceSpan, SymbolId};
use foresee_syntax::Diagnostic;
use std::collections::{BTreeMap, BTreeSet};
use TypeKind::*;

type Env = BTreeMap<std::string::String, InferredType>;
#[derive(Clone, Copy, PartialEq, Eq)]
pub(crate) enum Stage {
    Types,
    Effects,
    Lineage,
    Ownership,
}

struct Checker<'a> {
    symbols: &'a DeclarationSymbols,
    effects_enabled: bool,
    lineage_enabled: bool,
    ownership_enabled: bool,
    selection_count: usize,
    consumed: BTreeSet<SelectionId>,
    branch_resource: Option<ResourceRef>,
    used: BTreeSet<(std::string::String, std::string::String)>,
    errors: Vec<Diagnostic>,
    expressions: Vec<ExpressionType>,
    snapshot_count: usize,
    node_count: usize,
    branch_base: Option<InferredType>,
}

pub(crate) fn check(
    program: BodyProgram,
    symbols: &DeclarationSymbols,
    stage: Stage,
) -> Result<TypeAnalysis, DeclarationFailure> {
    let effects_enabled = stage != Stage::Types;
    let mut checker = Checker {
        symbols,
        effects_enabled,
        lineage_enabled: matches!(stage, Stage::Lineage | Stage::Ownership),
        ownership_enabled: stage == Stage::Ownership,
        selection_count: 0,
        consumed: BTreeSet::new(),
        branch_resource: None,
        used: BTreeSet::new(),
        errors: vec![],
        expressions: vec![],
        snapshot_count: 0,
        node_count: 0,
        branch_base: None,
    };
    for decision in program.decisions {
        checker.used.clear();
        let declared: BTreeSet<_> = decision.effects.iter().cloned().collect();
        if effects_enabled {
            for (kind, target) in &declared {
                if !signatures::effect_target_matches(kind, symbols.lookup(target).map(|s| s.id()))
                {
                    checker.error(
                        "F3202",
                        &format!("invalid effect {kind}({target})"),
                        &decision.span,
                    );
                }
            }
        }
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
        if effects_enabled {
            let missing: Vec<_> = checker.used.difference(&declared).cloned().collect();
            for (kind, target) in missing {
                checker.error(
                    "F3001",
                    &format!("effect {kind}({target}) is used but not declared"),
                    &decision.span,
                );
            }
            let unknown: BTreeSet<_> = declared
                .iter()
                .filter_map(|(_, target)| {
                    (!matches!(
                        symbols.lookup(target).map(|s| s.id()),
                        Some(SymbolId::Resource(_) | SymbolId::Model(_))
                    ))
                    .then_some(target)
                })
                .collect();
            for target in unknown {
                checker.error(
                    "F3002",
                    &format!("unknown effect target {target:?}"),
                    &decision.span,
                );
            }
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
    fn use_effect(&mut self, kind: &str, target: &str) {
        if self.effects_enabled {
            self.used.insert((kind.into(), target.into()));
        }
    }
    fn same_origin(&mut self, left: &InferredType, right: &InferredType, span: &SourceSpan) {
        if self.lineage_enabled
            && (left.resource != right.resource || left.lineage != right.lineage)
        {
            self.error(
                "F3301",
                "values must belong to the same resource and snapshot",
                span,
            );
        }
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
        if self.effects_enabled
            && self.branch_base.is_some()
            && signatures::forbidden_in_branch(expr.kind.name())
        {
            self.error(
                if matches!(expr.kind, ExprKind::Commit { .. }) {
                    "F3102"
                } else {
                    "F3207"
                },
                &format!("{} is forbidden inside explore", expr.kind.name()),
                &expr.span,
            );
        }
        match &expr.kind {
            ExprKind::String { value } => {
                let _ = value;
                InferredType::scalar(String)
            }
            ExprKind::Int { .. } => InferredType::scalar(Int),
            ExprKind::Var { name } => {
                let ty = env.get(name).cloned().unwrap_or_else(|| {
                    self.error("F3004", "unknown binding", &expr.span);
                    InferredType::scalar(Error)
                });
                if self.ownership_enabled
                    && ty.selection.is_some_and(|id| self.consumed.contains(&id))
                {
                    self.error("F3400", "selection has already been consumed", &expr.span);
                }
                ty
            }
            ExprKind::Snapshot { resource } => {
                let reference = self.resource(resource);
                if matches!(reference, ResourceRef::Unresolved(_)) {
                    self.error("F3005", "unknown resource", &expr.span);
                }
                self.use_effect("Snapshot", resource);
                self.snapshot_count += 1;
                InferredType {
                    kind: Snapshot,
                    resource: Some(reference),
                    metric_names: vec![],
                    lineage: Some(self.snapshot_count),
                    selection: None,
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
                self.use_effect("Infer", model);
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
                if self.ownership_enabled
                    && body.iter().map(simulations_in_statement).sum::<usize>() != 1
                {
                    self.error(
                        "F3401",
                        "explore requires exactly one simulation per branch",
                        &expr.span,
                    );
                }
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
                self.use_effect("Explore", &resource.name(self.symbols));
                self.same_origin(&plans, &base, &expr.span);
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
                        selection: None,
                    },
                );
                let previous_resource = self.branch_resource.replace(resource.clone());
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
                self.branch_resource = previous_resource;
                InferredType {
                    kind: Trials,
                    resource: Some(resource),
                    metric_names: metrics,
                    lineage: base.lineage,
                    selection: None,
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
                if self.lineage_enabled
                    && self
                        .branch_resource
                        .as_ref()
                        .is_some_and(|r| r != &resource)
                {
                    self.error(
                        "F3104",
                        "simulation resource must match the explore snapshot",
                        &expr.span,
                    );
                }
                if method != "apply" || matches!(resource, ResourceRef::Unresolved(_)) {
                    self.error(
                        "F3210",
                        "simulate supports only a declared resource's apply method",
                        &expr.span,
                    );
                }
                let types = self.arguments(args, &[&[Plan]], env, &expr.span);
                if let (Some(plan), Some(base)) = (types.first(), self.branch_base.clone()) {
                    self.same_origin(plan, &base, &expr.span);
                }
                InferredType {
                    kind: Simulated,
                    resource: Some(resource),
                    metric_names: vec![],
                    lineage: self.branch_base.as_ref().and_then(|b| b.lineage),
                    selection: None,
                }
            }
            ExprKind::Call {
                target,
                method,
                args,
            } => {
                let Some((expected, result)) = signatures::method(method) else {
                    self.error("F3210", "unknown resource method", &expr.span);
                    return InferredType::scalar(Error);
                };
                if matches!(self.resource(target), ResourceRef::Unresolved(_)) {
                    self.error("F3210", "unknown resource method", &expr.span);
                    return InferredType::scalar(Error);
                }
                let types = self.arguments(args, expected, env, &expr.span);
                for arg in &types {
                    if self.lineage_enabled && arg.resource.as_ref() != Some(&self.resource(target))
                    {
                        self.error(
                            "F3301",
                            "method argument belongs to a different resource",
                            &expr.span,
                        );
                    }
                    self.same_origin(arg, &types[0], &expr.span);
                    if let Some(base) = self.branch_base.clone() {
                        self.same_origin(arg, &base, &expr.span);
                    }
                }
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
                self.selection_count += 1;
                let mut selected = InferredType::derived(Selected, &trials);
                selected.selection = Some(SelectionId(self.selection_count));
                selected
            }
            ExprKind::Commit { selected, resource } => {
                if self.effects_enabled && self.branch_base.is_some() {
                    self.error(
                        "F3102",
                        "live commit is forbidden inside explore",
                        &expr.span,
                    );
                }
                let selected = self.expr(selected, env);
                if self.ownership_enabled {
                    if let Some(id) = selected.selection {
                        self.consumed.insert(id);
                    }
                }
                let resource = self.resource(resource);
                if selected.kind != Selected || selected.resource.as_ref() != Some(&resource) {
                    self.error(
                        "F3107",
                        "commit requires Selected data for the same resource",
                        &expr.span,
                    );
                }
                self.use_effect("Commit", &resource.name(self.symbols));
                InferredType {
                    kind: Outcome,
                    resource: Some(resource),
                    metric_names: vec![],
                    lineage: selected.lineage,
                    selection: None,
                }
            }
        }
    }
}

// Count syntax, including arguments whose type checking may stop at an invalid
// receiver. This mirrors the branch contract independently of error recovery.
fn simulations_in_statement(statement: &Statement) -> usize {
    let expr = match &statement.kind {
        StatementKind::Let { value, .. }
        | StatementKind::Return { value }
        | StatementKind::Measure { value, .. } => value,
        StatementKind::Check { condition, .. } => condition,
    };
    simulations_in_expr(expr)
}
fn simulations_in_expr(expr: &Expr) -> usize {
    match &expr.kind {
        ExprKind::Simulate { args, .. } => 1 + args.iter().map(simulations_in_expr).sum::<usize>(),
        ExprKind::Call { args, .. } | ExprKind::Propose { args, .. } => {
            args.iter().map(simulations_in_expr).sum()
        }
        ExprKind::Explore {
            plans, base, body, ..
        } => {
            simulations_in_expr(plans)
                + simulations_in_expr(base)
                + body.iter().map(simulations_in_statement).sum::<usize>()
        }
        ExprKind::Select { trials, .. } => simulations_in_expr(trials),
        ExprKind::Commit { selected, .. } => simulations_in_expr(selected),
        ExprKind::String { .. }
        | ExprKind::Int { .. }
        | ExprKind::Var { .. }
        | ExprKind::Snapshot { .. } => 0,
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

#[cfg(test)]
mod effect_tests {
    use crate::{check_effects, DeclarationFailure};
    const SOURCE: &str = include_str!("../../../examples/repair.fore");
    fn errors(source: &str) -> Vec<foresee_syntax::Diagnostic> {
        match check_effects(source) {
            Err(DeclarationFailure::Diagnostics(errors)) => errors,
            other => panic!("expected diagnostics: {other:?}"),
        }
    }
    #[test]
    fn missing_permissions_identify_each_operation() {
        for permission in [
            "Snapshot(catalog)",
            "Infer(planner)",
            "Explore(catalog)",
            "Commit(catalog)",
        ] {
            let source = SOURCE
                .replace(&format!("{permission}, "), "")
                .replace(&format!(", {permission}"), "");
            let diagnostics = errors(&source);
            assert_eq!(diagnostics.len(), 1);
            assert_eq!(diagnostics[0].code, "F3001");
            assert!(diagnostics[0].message.contains(permission));
        }
    }
    #[test]
    fn invalid_effect_targets_are_not_authority() {
        let diagnostics = errors(&SOURCE.replace("Infer(planner)", "Infer(catalog)"));
        assert_eq!(
            diagnostics
                .iter()
                .map(|d| d.code.as_str())
                .collect::<Vec<_>>(),
            vec!["F3202", "F3001"]
        );
    }
    #[test]
    fn branch_commit_preserves_reference_diagnostic_multiplicity() {
        let diagnostics = errors(&SOURCE.replace(
            "let after =",
            "let bad = commit base to catalog; let after =",
        ));
        assert_eq!(diagnostics.iter().filter(|d| d.code == "F3102").count(), 2);
        assert!(diagnostics.iter().any(|d| d.code == "F3107"));
    }
    #[test]
    fn redundant_effects_do_not_change_type_analysis() {
        let first = serde_json::to_value(check_effects(SOURCE).unwrap()).unwrap();
        let reordered = SOURCE.replace("Snapshot(catalog), Infer(planner), Explore(catalog), Commit(catalog)",
            "Commit(catalog), Infer(planner), Snapshot(catalog), Explore(catalog), Snapshot(catalog)");
        let second = serde_json::to_value(check_effects(&reordered).unwrap()).unwrap();
        // Declaration text lengths change source locations but not inferred types.
        let types = |v: &serde_json::Value| {
            v["expressions"]
                .as_array()
                .unwrap()
                .iter()
                .map(|e| e["inferred_type"].clone())
                .collect::<Vec<_>>()
        };
        assert_eq!(types(&first), types(&second));
    }
}

#[cfg(test)]
mod lineage_tests {
    use crate::{check_lineage, DeclarationFailure};
    const SOURCE: &str = include_str!("../../../examples/repair.fore");
    #[test]
    fn every_resource_bearing_type_retains_origin_through_aliases() {
        let source = SOURCE
            .replace("let plans =", "let alias = base; let plans =")
            .replace("from base", "from alias")
            .replace(
                "return commit chosen to catalog;",
                "let copied = chosen; let result = commit copied to catalog; return result;",
            );
        let result = check_lineage(&source).unwrap();
        for expression in result.expressions() {
            let ty = &expression.inferred_type;
            if ty.resource.is_some() {
                assert_eq!(ty.resource.as_deref(), Some("catalog"));
                assert_eq!(ty.lineage.as_deref(), Some("snapshot:1"));
            }
        }
    }
    #[test]
    fn independent_snapshot_cannot_replace_proposal_origin() {
        let source = SOURCE
            .replace("let plans =", "let other = snapshot catalog; let plans =")
            .replace("from base", "from other");
        let Err(DeclarationFailure::Diagnostics(errors)) = check_lineage(&source) else {
            panic!("expected rejection");
        };
        assert!(errors.iter().any(|e| e.code == "F3301"));
    }
    #[test]
    fn unrelated_metric_rejected_even_when_type_is_correct() {
        let source = SOURCE
            .replace("let plans =", "let other = snapshot catalog; let plans =")
            .replace("unresolved_units(after)", "unresolved_units(other)");
        let Err(DeclarationFailure::Diagnostics(errors)) = check_lineage(&source) else {
            panic!("expected rejection");
        };
        assert_eq!(errors.len(), 1);
        assert_eq!(errors[0].code, "F3301");
    }
    #[test]
    fn resource_identity_is_distinct_from_snapshot_identity() {
        use super::*;
        let symbols = crate::check_declarations(SOURCE).unwrap();
        let mut checker = Checker {
            symbols: &symbols,
            effects_enabled: true,
            lineage_enabled: true,
            ownership_enabled: false,
            selection_count: 0,
            consumed: BTreeSet::new(),
            branch_resource: None,
            errors: vec![],
            expressions: vec![],
            snapshot_count: 0,
            node_count: 0,
            branch_base: None,
            used: BTreeSet::new(),
        };
        let left = InferredType {
            kind: Snapshot,
            resource: Some(ResourceRef::Known(crate::ResourceId(0))),
            metric_names: vec![],
            lineage: Some(1),
            selection: None,
        };
        // Synthetic internal identities exercise nominal comparison independently
        // of the public single-resource declaration gate.
        let right = InferredType {
            resource: Some(ResourceRef::Known(crate::ResourceId(1))),
            ..left.clone()
        };
        checker.same_origin(
            &left,
            &right,
            &SourceSpan {
                start: 0,
                end: 0,
                line: 1,
                column: 1,
            },
        );
        assert_eq!(checker.errors.len(), 1);
        assert_eq!(checker.errors[0].code, "F3301");
    }
}

#[cfg(test)]
mod ownership_tests {
    use crate::{check_lineage, check_ownership, DeclarationFailure};
    const SOURCE: &str = include_str!("../../../examples/repair.fore");
    fn codes(source: &str) -> Vec<String> {
        let Err(DeclarationFailure::Diagnostics(errors)) = check_ownership(source) else {
            panic!("expected rejection")
        };
        errors.into_iter().map(|e| e.code).collect()
    }
    #[test]
    fn aliases_share_consumption_but_lineage_stage_stays_unchanged() {
        let source = SOURCE.replace(
            "return commit chosen",
            "let alias = chosen; let first = commit alias to catalog; return commit chosen",
        );
        assert_eq!(codes(&source), ["F3400"]);
        assert!(check_lineage(&source).is_ok());
    }
    #[test]
    fn independent_selections_and_outcome_aliases_are_allowed() {
        let source = SOURCE.replace("return commit chosen to catalog;", "let second = select trials minimize unresolved; let first = commit chosen to catalog; let result = commit second to catalog; let alias = result; return alias;");
        assert!(check_ownership(&source).is_ok());
    }
    #[test]
    fn simulation_count_is_syntactic_even_for_unknown_calls() {
        let source = SOURCE.replace(
            "catalog.valid_unit_arithmetic(after)",
            "catalog.unknown(simulate catalog.apply(plan))",
        );
        assert_eq!(codes(&source), ["F3401", "F3210", "F3205"]);
    }
    #[test]
    fn zero_simulations_is_rejected() {
        let source = SOURCE.replace("simulate catalog.apply(plan)", "base");
        assert!(codes(&source).contains(&"F3401".into()));
    }
}
