"""Explicit evidence commands; never print private keys or embedded reports."""
import json

from .bounded_replay import ReplayBudget
from .evidence_auth import MAX_POLICY
from .evidence_files import generate_key, load_key, public_metadata, read_bounded, write_new
from .evidence_format import MAX_ENVELOPE
from .evidence_workflow import sign_report, verify_report


COMMANDS = {'evidence-keygen', 'evidence-public-key', 'evidence-sign', 'evidence-verify'}


def add_commands(sub):
    keygen = sub.add_parser('evidence-keygen', help='create a new owner-only Ed25519 key file')
    keygen.add_argument('--output', required=True)
    public = sub.add_parser('evidence-public-key', help='display public metadata for an owned key')
    public.add_argument('--key', required=True)
    sign = sub.add_parser('evidence-sign', help='sign a report after Linux bounded replay')
    sign.add_argument('report')
    sign.add_argument('--key', required=True)
    sign.add_argument('--output', required=True)
    sign.add_argument('--issued-at', type=int, required=True)
    sign.add_argument('--expires-at', type=int, required=True)
    verify = sub.add_parser('evidence-verify', help='authenticate and replay an evidence envelope')
    verify.add_argument('envelope')
    verify.add_argument('--policy', required=True)
    verify.add_argument('--now', type=int, required=True, help='trusted verifier evaluation time in Unix seconds')
    verify.add_argument('--max-lifetime', type=int, required=True)
    for command in (sign, verify):
        command.add_argument('--issuer', required=True)
        command.add_argument('--audience', required=True)
        command.add_argument('--wall-seconds', type=float, default=10)
        command.add_argument('--cpu-seconds', type=int, default=3)
        command.add_argument('--memory-mib', type=int, default=512)
        command.add_argument('--max-report-bytes', type=int, default=8_000_000)


def run(args):
    if args.command == 'evidence-keygen':
        result = generate_key(args.output)
    elif args.command == 'evidence-public-key':
        result = public_metadata(load_key(args.key))
    else:
        budget = ReplayBudget(max_report_bytes=args.max_report_bytes, wall_seconds=args.wall_seconds,
                              cpu_seconds=args.cpu_seconds, memory_bytes=args.memory_mib * 1024**2)
        if args.command == 'evidence-sign':
            report = read_bounded(args.report, budget.max_report_bytes)
            key = load_key(args.key)
            envelope = sign_report(report, key, issuer=args.issuer, audience=args.audience,
                                   issued_at=args.issued_at, expires_at=args.expires_at, budget=budget)
            write_new(args.output, envelope)
            result = {'signed': True, 'output': args.output, 'keyid': public_metadata(key)['keyid'],
                      'decision_reproduced': True, 'target_effect_verified': False}
        else:
            result = verify_report(read_bounded(args.envelope, MAX_ENVELOPE),
                                   read_bounded(args.policy, MAX_POLICY), expected_issuer=args.issuer,
                                   expected_audience=args.audience, now=args.now,
                                   max_lifetime=args.max_lifetime, budget=budget)
            auth = result.authentication
            output = {'format_valid': auth.format_valid, 'signature_valid': auth.signature_valid,
                      'signer_trusted': auth.signer_trusted, 'checksum_valid': auth.checksum_valid,
                      'origin_authenticated': auth.origin_authenticated, 'keyid': auth.keyid,
                      'issuer': auth.issuer, 'audience': auth.audience, 'verified_at': auth.verified_at,
                      'decision_reproduced': result.decision_reproduced, 'replay_error': result.replay_error,
                      'requirements_satisfied': result.requirements_satisfied, 'target_effect_verified': False}
            print(json.dumps(output, sort_keys=True))
            return 0 if result.requirements_satisfied else 2
    print(json.dumps(result, sort_keys=True))
    return 0
