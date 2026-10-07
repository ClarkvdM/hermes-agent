"""Command-line boundary for explicit, metadata-only Jev skill selection."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys


def add_arguments(parser):
    parser.add_argument('task', nargs='?', help='Task text, or - to read stdin')
    parser.add_argument('--prompt', '-p', help='Task text (alternative to positional task), or -')
    parser.add_argument('--context-file', type=Path, help='UTF-8 recent context to upload with the task')
    parser.add_argument('--skills-dir', type=Path, help='Skill root (default: active profile skills directory)')
    parser.add_argument('--minimum-score', type=float, default=6, help='Inclusive score floor (default: 6)')
    parser.add_argument('--target-score', type=float, default=18, help='Cumulative stopping score, not quota (default: 18)')
    parser.add_argument('--token-budget', type=int, default=6000, help='Hard selected-context token ceiling (default: 6000)')
    parser.add_argument('--max-skills', type=int, help='Positive selected-skill cap, independent of target (default: unlimited)')
    parser.add_argument('--format', choices=['json', 'context'], default='json')
    parser.add_argument('--allow-upload', action='store_true', help='Consent to send task/context and skill names/descriptions to TypeSafe')
    parser.add_argument('--dry-run', action='store_true', help='Preview exact request payloads offline; no key required')
    parser.add_argument('--skip-invalid', action='store_true', help='Omit invalid frontmatter or untraversable directories and report paths/reasons (default: fail)')


def _inputs(args):
    if (args.task is None) == (args.prompt is None):
        raise ValueError('Provide exactly one positional task or --prompt/-p.')
    task = args.task if args.task is not None else args.prompt
    if task == '-':
        task = sys.stdin.read()
    if not task.strip():
        raise ValueError('Task cannot be empty.')
    if not math.isfinite(args.minimum_score) or not 0 <= args.minimum_score <= 9:
        raise ValueError('--minimum-score must be finite and between 0 and 9.')
    if not math.isfinite(args.target_score) or args.target_score <= 0:
        raise ValueError('--target-score must be finite and positive.')
    if args.token_budget < 0:
        raise ValueError('--token-budget must be nonnegative.')
    if args.max_skills is not None and args.max_skills <= 0:
        raise ValueError('--max-skills must be positive.')
    if args.dry_run and args.format != 'json':
        raise ValueError('--dry-run requires --format json (there are no scores or selected instructions).')
    context = args.context_file.read_text(encoding='utf-8-sig') if args.context_file else ''
    return task, context


def run(args) -> int:
    from hermes_constants import get_hermes_home
    from hermes_cli.skills_select import discover_skills, select_skills, context_tokenizer
    from hermes_cli.skills_select_provider import build_payloads, score_payloads, MODEL, ENDPOINT

    try:
        task, context = _inputs(args)
        if not args.dry_run and not args.allow_upload:
            raise ValueError('Upload disabled: use --dry-run to inspect, or --allow-upload to consent.')
        skills, skipped = discover_skills(args.skills_dir or get_hermes_home() / 'skills',
                                          skip_invalid=args.skip_invalid)
        payloads = build_payloads(skills, task, context)
        if args.dry_run:
            result = {'dry_run': True, 'endpoint': ENDPOINT, 'model': MODEL,
                      'payloads': payloads, 'candidate_count': len(skills), 'batch_count': len(payloads),
                      'skipped': skipped}
        else:
            key = os.environ.get('TYPESAFE_API_KEY', '').strip()
            if not key:
                raise ValueError('Set TYPESAFE_API_KEY in the process environment. No key files are read.')
            # Fail locally before spending provider tokens if the optional tokenizer is missing.
            context_tokenizer()
            scores, usage = score_payloads(payloads, key)
            result = select_skills(skills, scores, minimum=args.minimum_score,
                                   target=args.target_score, token_budget=args.token_budget,
                                   max_skills=args.max_skills)
            result['skipped'] += skipped
            result.update(model=MODEL, usage=usage, batch_count=len(payloads))
        if args.format == 'context':
            for omission in skipped:
                print('hermes skills select: omitted ' + json.dumps(omission, ensure_ascii=True), file=sys.stderr)
            sys.stdout.write(result['context'])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError) as exc:
        print(f'hermes skills select: {exc}', file=sys.stderr)
        return 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='hermes skills select', description=__doc__)
    add_arguments(parser)
    return run(parser.parse_args(argv))
