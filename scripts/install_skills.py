#!/usr/bin/env python3
"""Preview installation; copy explicitly selected skills only with --apply.

Never replaces an existing target. Each installed skill is a complete folder.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys

SKILLS = ("jobhuntbot", "company-job-screening", "resume-application")


def install(source, destination, names, apply=False):
    source, destination = Path(source).resolve(), Path(destination).expanduser().absolute()
    if not names or len(names) != len(set(names)) or any(n not in SKILLS for n in names):
        raise ValueError("invalid_selection")
    for parent in [destination, *destination.parents]:
        if parent.is_symlink():
            raise ValueError("symlink_destination_not_supported")
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("source_and_destination_overlap")
    targets = [destination / name for name in names]
    conflicts = [names[i] for i, p in enumerate(targets) if p.exists() or p.is_symlink()]
    if conflicts:
        return {"applied": False, "conflicts": conflicts, "planned_skills": names}
    for name in names:
        folder = source / name
        if not (folder / "SKILL.md").is_file():
            raise ValueError("source_skill_missing")
        if any(p.is_symlink() for p in folder.rglob("*")):
            raise ValueError("symlink_source_not_supported")
    if apply:
        destination.mkdir(parents=True, exist_ok=True)
        for name, target in zip(names, targets):
            shutil.copytree(source / name, target,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "private", "my-materials"))
    return {"applied": apply, "conflicts": [], "planned_skills": names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", required=True, help="Explicit Agent skill directory")
    parser.add_argument("--skill", action="append", choices=SKILLS)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = install(Path(__file__).resolve().parents[1] / "skills",
                         args.dest, args.skill or list(SKILLS), args.apply)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 1 if result["conflicts"] else 0
    except (OSError, ValueError):
        print('{"error":"installation_not_completed","hint":"Check explicit destination and permissions; existing skills are never replaced."}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
