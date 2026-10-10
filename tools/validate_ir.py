"""Structural validator for the digest-free typed IR 0.0.3 body.

This test utility validates the wire contract, not semantic authority or hostile
runtime inputs. Program identity and runtime execution are separate contracts.
"""

KINDS = {'int', 'string', 'bool', 'snapshot', 'plan', 'plans', 'simulated', 'trials', 'selected', 'outcome'}
OPERANDS = {
    'string': {'value': 'str'}, 'int': {'value': 'int'}, 'var': {'name': 'str'},
    'snapshot': {'resource': 'str'},
    'propose': {'model': 'str', 'plan_type': 'str', 'args': 'exprs'},
    'explore': {'item': 'str', 'plans': 'expr', 'base': 'expr', 'body': 'body'},
    'simulate': {'resource': 'str', 'method': 'str', 'args': 'exprs'},
    'call': {'target': 'str', 'method': 'str', 'args': 'exprs'},
    'select': {'trials': 'expr', 'metric': 'str'},
    'commit': {'selected': 'expr', 'resource': 'str'},
}
STATEMENTS = {
    'let': {'name': 'str', 'value': 'expr'}, 'return': {'value': 'expr'},
    'check': {'condition': 'expr', 'message': 'str'},
    'measure': {'name': 'str', 'type': 'str', 'value': 'expr'},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, names):
    require(type(value) is dict and set(value) == set(names), f'wrong fields: expected {names}')


def sequence(value, check):
    require(type(value) is list, 'expected array')
    for item in value:
        check(item)


def operand(value, kind):
    if kind == 'str':
        require(type(value) is str, 'expected string')
    elif kind == 'int':
        require(type(value) is int and value >= 0, 'expected nonnegative integer')
    elif kind == 'expr':
        expression(value)
    elif kind == 'exprs':
        sequence(value, expression)
    elif kind == 'body':
        sequence(value, statement)


def expression(value):
    require(type(value) is dict and value.get('op') in OPERANDS, 'unknown expression')
    spec = OPERANDS[value['op']]
    fields(value, {'op', 'inferred_type'} | spec.keys())
    ty = value['inferred_type']
    fields(ty, {'kind', 'resource', 'metric_names', 'lineage'})
    require(ty['kind'] in KINDS, 'invalid inferred kind')
    require(ty['resource'] is None or type(ty['resource']) is str, 'invalid resource')
    lineage = ty['lineage']
    require(lineage is None or (type(lineage) is str and lineage.startswith('snapshot:')
            and lineage[9:].isascii() and lineage[9:].isdigit() and int(lineage[9:]) > 0), 'invalid lineage')
    sequence(ty['metric_names'], lambda x: operand(x, 'str'))
    for name, kind in spec.items():
        operand(value[name], kind)


def statement(value):
    require(type(value) is dict and value.get('statement') in STATEMENTS, 'unknown statement')
    spec = STATEMENTS[value['statement']]
    fields(value, {'statement'} | spec.keys())
    for name, kind in spec.items():
        operand(value[name], kind)
    if value['statement'] == 'measure':
        require(value['type'] == 'Int', 'invalid metric annotation')


def validate_ir_body(value):
    fields(value, {'schema_version', 'resources', 'models', 'decisions'})
    require(value['schema_version'] == '0.0.3', 'unsupported IR version')
    for group in ('resources', 'models'):
        def declaration(item):
            fields(item, {'name', 'type_name'})
            operand(item['name'], 'str')
            require(item['type_name'] == ('Catalog' if group == 'resources' else 'Planner'), 'invalid declaration type')
        sequence(value[group], declaration)
        require(len(value[group]) == 1, 'unsupported declaration cardinality')
    def decision(item):
        fields(item, {'name', 'effects', 'body'})
        operand(item['name'], 'str')
        def effect(e):
            fields(e, {'kind', 'target'})
            require(e['kind'] in {'Snapshot', 'Infer', 'Explore', 'Commit'}, 'invalid effect')
            operand(e['target'], 'str')
        sequence(item['effects'], effect)
        pairs = [(e['kind'], e['target']) for e in item['effects']]
        require(pairs == sorted(set(pairs)), 'effects must be sorted and unique')
        sequence(item['body'], statement)
    sequence(value['decisions'], decision)
    require(len(value['decisions']) == 1, 'unsupported decision cardinality')
