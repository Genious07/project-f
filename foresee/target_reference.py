"""Credential-free references stored in journals; endpoints stay in local config."""
import re


def postgres_reference(name, schema):
    if type(name) is not str or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', name):
        raise ValueError('PostgreSQL journaling requires a local target name')
    if type(schema) is not str or not re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', schema) or schema.startswith('pg_') or schema == 'information_schema':
        raise ValueError('invalid PostgreSQL schema reference')
    return {'version': 1, 'adapter': 'postgres', 'name': name, 'schema': schema}


def validate_reference(reference):
    if type(reference) is not dict or set(reference) != {'version', 'adapter', 'name', 'schema'} or type(reference['version']) is not int or reference['version'] != 1 or reference['adapter'] != 'postgres':
        raise ValueError('unsupported journal target reference')
    return postgres_reference(reference['name'], reference['schema'])
