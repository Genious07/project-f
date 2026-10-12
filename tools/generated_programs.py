"""Bounded, seeded grammar variations for compiler differential tests."""
import random


def generate(seed=20261012, count=64):
    rng = random.Random(seed)
    for index in range(count):
        r, m = f'catalog_{index}', f'planner_{index}'
        metric = f'score_{index}'
        prompt = rng.choice(['Repair derived prices', '价格 café 😀', r'quote \" and slash \\', r'line\nnext\tcolumn'])
        effects = [f'Snapshot({r})', f'Infer({m})', f'Explore({r})', f'Commit({r})']
        rng.shuffle(effects)
        if rng.randrange(2):
            effects.append(effects[0])
        annotation = f': Snapshot<{r}>' if rng.randrange(2) else ''
        aliases = rng.randrange(1, 5)
        selected = 'chosen'
        alias_lines = []
        for n in range(aliases):
            alias_lines.append(f'let alias{n} = {selected};')
            selected = f'alias{n}'
        extra_metric = f'measure extra: Int = {r}.unresolved_units(after);' if rng.randrange(2) else ''
        number = str(rng.randrange(10**30, 10**45))
        source = f'''resource {r}: Catalog;
model {m}: Planner;
decision repair_{index}() -> DecisionResult
! {{ {', '.join(effects)} }} {{
let literal = {number};
let base{annotation} = snapshot {r};
let snapshot_alias = base;
let plans = propose {m}<Patch>(snapshot_alias, "{prompt}", {rng.randrange(1, 5)});
let trials = explore plan in plans from base {{
let after = simulate {r}.apply(plan);
check {r}.valid_unit_arithmetic(after) else "bad units";
{extra_metric}
measure {metric}: Int = {r}.unresolved_units(after);
}};
let chosen = select trials minimize {metric};
{' '.join(alias_lines)}
return commit {selected} to {r};
}}
'''
        if rng.randrange(2):
            source = '// generated case\n' + source
        if rng.randrange(2):
            source = source.replace('\n', '\r\n')
        yield {'name': f'generated/{seed}/{index}/valid', 'source': source, 'expected_ok': True}
        # Cycle mutations so even a small fixed run covers distinct semantic phases.
        mode = index % 8
        before, after, code = [
            (f'return commit {selected}', f'let first = commit chosen to {r}; return commit {selected}', 'F3400'),
            (f'let after =', f'let extra_sim = simulate {r}.apply(plan); let after =', 'F3401'),
            (f'Commit({r})', f'Commit({m})', 'F3202'),
            ('from base', f'from snapshot {r}', 'F3301'),
            (f'minimize {metric}', 'minimize absent', 'F3106'),
            (f'let base{annotation} =', 'let base: Int =', 'F3300'),
            (f'{r}.valid_unit_arithmetic(after)', f'{r}.absent(after)', 'F3210'),
            (f'return commit {selected}', 'return commit missing', 'F3004'),
        ][mode]
        yield {'name': f'generated/{seed}/{index}/invalid-{code}', 'source': source.replace(before, after),
               'expected_ok': False, 'required_code': code}
