#!/usr/bin/env python3
"""Scan the public package without printing matched private values."""
import argparse
import csv
import io
import json
from pathlib import Path
import re
import sys

ALLOWED_SUFFIXES = {'.md', '.json', '.py', '.yaml', '.yml', '.csv',
                    '.html', '.js', '.bat', '.sh'}
ALLOWED_NAMES = {'LICENSE', '.gitignore', '.gitattributes'}
BLOCKED_DIRS = {'private', 'my-materials', 'node_modules', '__pycache__',
                '.venv', '.aws', '.codex', '.agents', 'research', 'backup'}
PATTERNS = {
    'email': r'(?i)(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+',
    'mainland_mobile': r'(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)',
    'identity_number': r'(?<!\w)[1-9]\d{5}(?:19|20)\d{9}[\dXx](?!\w)',
    'personal_windows_path': r'(?i)[A-Z]:[/\\]Users[/\\][^/\\\s`"<>]+',
    'personal_unix_path': r'/(?:Users|home)/[a-zA-Z0-9_.-]+/',
    'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'access_token': r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b',
    'authenticated_url': r'https?://[^/\s:@]+:[^/\s@]+@',
    'url_credential': r'(?i)[?&](?:access_token|auth_token|xsec_token|api_key|signature|session_id)=[^\s&`<>"\x27]+',
}


def scan(root, denied=()):
    findings = []
    checked = 0
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if '.git' in rel.parts:
            continue  # Git internals are not release contents; audit history separately.
        if path.is_symlink():
            findings.append({'file': rel.as_posix(), 'rule': 'symlink'})
            continue
        if not path.is_file():
            continue
        checked += 1
        label = rel.as_posix()
        def flag(rule):
            findings.append({'file': label, 'rule': rule})
        if any(part in BLOCKED_DIRS or part.startswith('.venv') for part in rel.parts):
            flag('private_or_runtime_directory')
        if path.suffix not in ALLOWED_SUFFIXES and path.name not in ALLOWED_NAMES:
            flag('unexpected_file_type')
        try:
            text = path.read_text(encoding='utf-8-sig')
        except (UnicodeError, OSError):
            flag('binary_or_unreadable')
            continue
        if '\x00' in text:
            flag('binary_null_byte')
        for rule, pattern in PATTERNS.items():
            if re.search(pattern, text) or re.search(pattern, label):
                flag(rule)
        for value in denied:
            if value and (value.casefold() in text.casefold() or value.casefold() in label.casefold()):
                flag('private_denylist')
                break
        if path.suffix == '.csv':
            rows = [row for row in csv.reader(io.StringIO(text)) if any(row)]
            if len(rows) != 1:
                flag('csv_must_be_header_only')
        if path.suffix == '.json':
            try:
                json.loads(text)
            except ValueError:
                flag('invalid_json')
        if path.name == 'candidate-data.example.json':
            data = json.loads(text)
            def is_empty(value):
                if isinstance(value, dict):
                    return all(is_empty(v) for k, v in value.items() if k != 'notes')
                if isinstance(value, list):
                    return len(value) == 0
                return value is None or value == ''
            if not is_empty(data):
                flag('candidate_example_contains_values')
    return {'files_checked': checked, 'passed': not findings, 'findings': findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--denylist-json', type=Path,
                        help='Optional private JSON string array stored outside the package')
    args = parser.parse_args()
    denied = []
    if args.denylist_json:
        denied = json.loads(args.denylist_json.read_text(encoding='utf-8-sig'))
        if not isinstance(denied, list) or not all(isinstance(v, str) for v in denied):
            parser.error('Denylist must be a JSON array of strings')
    result = scan(args.root.resolve(), denied)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
