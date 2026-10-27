#!/usr/bin/env python3
"""Scan the public package without printing matched private values."""
import argparse
import hashlib
import csv
import io
import json
from pathlib import Path
import re
import sys
import subprocess
import unicodedata

ALLOWED_SUFFIXES = {'.md', '.json', '.py', '.yaml', '.yml', '.csv',
                    '.html', '.js', '.bat', '.sh'}
ALLOWED_NAMES = {'LICENSE', '.gitignore', '.gitattributes'}
BLOCKED_DIRS = {'private', 'my-materials', 'node_modules', '__pycache__',
                '.venv', '.aws', '.codex', '.agents', 'research', 'backup'}
PATTERNS = {
    'email': r'(?i)(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+',
    'mainland_mobile': r'(?<![A-Za-z0-9])(?:\+?86[- ]?)?1[3-9]\d{9}(?![A-Za-z0-9])',
    'identity_number': r'(?<!\w)[1-9]\d{5}(?:19|20)\d{9}[\dXx](?!\w)',
    'personal_windows_path': r'(?i)[A-Z]:[/\\]+Users[/\\]+[^/\\\s`"<>]+',
    'personal_unix_path': r'/(?:Users|home)/[a-zA-Z0-9_.-]+/',
    'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'access_token': r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b',
    'authenticated_url': r'https?://[^/\s:@]+:[^/\s@]+@',
    'url_credential': r'(?i)[?&](?:access_token|auth_token|xsec_token|api_key|signature|session_id)=[^\s&`<>"\x27]+',
}


def safe_label(label, denied=()):
    normalized = unicodedata.normalize('NFKC', label)
    if (any(v and unicodedata.normalize('NFKC', v).casefold() in normalized.casefold() for v in denied)
            or any(re.search(pattern, normalized) for pattern in PATTERNS.values())):
        return '[redacted-filename:' + hashlib.sha256(label.encode('utf-8')).hexdigest()[:12] + ']'
    return label



def text_findings(label, text, denied=()):
    findings = []
    normalized = unicodedata.normalize("NFKC", text)
    if label.endswith('.json'):
        try:
            normalized += "\n" + json.dumps(json.loads(text), ensure_ascii=False)
        except ValueError:
            findings.append({'file': label, 'rule': 'invalid_json'})
    if '\x00' in text:
        findings.append({'file': label, 'rule': 'binary_null_byte'})
    for rule, pattern in PATTERNS.items():
        if re.search(pattern, normalized) or re.search(pattern, label):
            findings.append({'file': label, 'rule': rule})
    if any(v and unicodedata.normalize('NFKC', v).casefold() in (normalized + '\n' + label).casefold() for v in denied):
        findings.append({'file': label, 'rule': 'private_denylist'})
    for finding in findings:
        finding['file'] = safe_label(label, denied)
    return findings


def inspect_content(label, payload, denied=()):
    findings = []
    rel = Path(label)
    def flag(rule):
        findings.append({'file': safe_label(label, denied), 'rule': rule})
    if any(part in BLOCKED_DIRS or part.startswith('.venv') for part in rel.parts):
        flag('private_or_runtime_directory')
    if rel.suffix not in ALLOWED_SUFFIXES and rel.name not in ALLOWED_NAMES:
        flag('unexpected_file_type')
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeError:
        flag('binary_or_unreadable')
        return findings
    findings.extend(text_findings(label, text, denied))
    if rel.suffix == '.csv':
        rows = [row for row in csv.reader(io.StringIO(text)) if any(row)]
        if len(rows) != 1:
            flag('csv_must_be_header_only')
    if rel.name in {'candidate-data.example.json', 'candidate_profile.template.json'}:
        try:
            data = json.loads(text)
            def is_empty(value):
                if isinstance(value, dict):
                    return all(is_empty(v) for k, v in value.items() if k not in {'notes', 'schema_version'})
                if isinstance(value, list):
                    return len(value) == 0
                return value is None or value == ''
            # The older public template had explanatory defaults outside its
            # empty identity section. Do not classify those defaults as facts.
            values = (data.get('candidate', {}) if isinstance(data, dict)
                      and rel.name == 'candidate_profile.template.json'
                      and 'schema_version' not in data else data)
            if not isinstance(data, dict) or not is_empty(values):
                flag('candidate_example_contains_values')
        except ValueError:
            pass  # invalid_json was already reported without printing contents.
    return findings


def scan(root, denied=()):
    root = Path(root)
    findings, checked = [], 0
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if '.git' in rel.parts:
            continue
        if path.is_symlink():
            findings.append({'file': safe_label(rel.as_posix(), denied), 'rule': 'symlink'})
            continue
        if not path.is_file():
            continue
        checked += 1
        try:
            findings.extend(inspect_content(rel.as_posix(), path.read_bytes(), denied))
        except OSError:
            findings.append({'file': safe_label(rel.as_posix(), denied), 'rule': 'unreadable'})
    return {'files_checked': checked, 'passed': not findings, 'findings': findings}


def scan_history(root, ref='HEAD', denied=()):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_.-]*', ref):
        raise ValueError('invalid_revision')
    def git(*args, data=None):
        return subprocess.check_output(['git', '-C', str(root), *args], input=data, stderr=subprocess.DEVNULL)
    commits = git('rev-list', ref, '--').decode('ascii').splitlines()
    findings, blobs = [], {}
    for commit in commits:
        metadata = git('show', '-s', '--format=%an%n%ae%n%cn%n%ce%n%B', commit).decode('utf-8')
        lines = metadata.splitlines()
        for value in (lines[1], lines[3]):
            if not value.endswith(('@users.noreply.github.com', '@github.com')):
                findings.append({'commit': commit[:12], 'rule': 'non_private_commit_email'})
        identity_text = '\n'.join([lines[0], lines[2], *lines[4:]])
        if text_findings('commit-metadata.md', identity_text, denied):
            findings.append({'commit': commit[:12], 'rule': 'sensitive_commit_metadata'})
        tree = git('ls-tree', '-r', '-z', commit)
        for entry in tree.split(b'\0'):
            if not entry:
                continue
            head, path_bytes = entry.split(b'\t', 1)
            mode, kind, oid = head.decode('ascii').split()
            name = path_bytes.decode('utf-8')
            if mode not in {'100644', '100755'} or kind != 'blob':
                findings.append({'commit': commit[:12], 'file': safe_label(name, denied), 'rule': 'non_regular_git_entry'})
            blobs.setdefault(oid, set()).add(name)
    ids = list(blobs)
    if ids:
        batch = git('cat-file', '--batch', data=('\n'.join(ids) + '\n').encode('ascii'))
        offset = 0
        for oid in ids:
            end = batch.index(b'\n', offset)
            object_id, kind, size = batch[offset:end].decode('ascii').split()
            if object_id != oid or kind != 'blob':
                raise ValueError('unexpected_git_object')
            size = int(size)
            payload = batch[end + 1:end + 1 + size]
            offset = end + 1 + size + 1
            for name in blobs[oid]:
                for finding in inspect_content(name, payload, denied):
                    finding['object'] = oid[:12]
                    findings.append(finding)
    return {'commits_checked': len(commits), 'unique_blobs_checked': len(ids),
            'passed': not findings, 'findings': findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--denylist-json', type=Path,
                        help='Optional private JSON string array stored outside the package')
    parser.add_argument('--git-history', action='store_true', help='Also inspect reachable commit metadata and all historical blobs')
    parser.add_argument('--git-ref', default='HEAD')
    args = parser.parse_args()
    denied = []
    if args.denylist_json:
        denied = json.loads(args.denylist_json.read_text(encoding='utf-8-sig'))
        if not isinstance(denied, list) or not all(isinstance(v, str) for v in denied):
            parser.error('Denylist must be a JSON array of strings')
    result = scan(args.root.resolve(), denied)
    if args.git_history:
        try:
            result['history'] = scan_history(args.root.resolve(), args.git_ref, denied)
            result['passed'] = result['passed'] and result['history']['passed']
        except (OSError, ValueError, subprocess.CalledProcessError):
            result['passed'] = False
            result['history'] = {'passed': False, 'error': 'history_unavailable'}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
