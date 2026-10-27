#!/usr/bin/env python3
"""Read a user-configured screening workspace; never modify its files."""
import argparse
from collections import Counter
import json
import hashlib
from pathlib import Path
import sys


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_path(workspace, value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else workspace / path


def inspect(workspace, config_path, company=None):
    config = read_json(resolve_path(workspace, config_path))
    data_path = resolve_path(workspace, config["screening_data"])
    data = read_json(data_path)
    companies, jobs = data["companies"], data["jobs"]
    coverage = dict(Counter(c.get("status", "未检索") for c in companies))
    counts = Counter((j["company"], str(j["jobId"]), j.get("department", ""), j.get("cohort", "")) for j in jobs)
    duplicates = [{"company": c, "jobId": i, "department": dep, "cohort": cohort, "count": n}
                  for (c, i, dep, cohort), n in counts.items() if n > 1]
    names = {c["name"] for c in companies}
    configured = {key: resolve_path(workspace, config[key]) for key in (
        "document_pointer", "local_backup", "resume_checkpoint", "application_ledger")
        if config.get(key)}
    result = {
        "companies": len(companies), "job_records": len(jobs),
        "record_count_is_not_available_job_count": True,
        "coverage": coverage,
        "stored_coverage_matches": data.get("coverage") == coverage,
        "duplicate_entities": duplicates,
        "duplicate_company_names": [name for name, count in Counter(c["name"] for c in companies).items() if count > 1],
        "jobs_outside_company_pool": sorted({j["company"] for j in jobs} - names),
        "pending": [c["name"] for c in companies if c.get("status") == "未检索"],
        "in_progress": [c["name"] for c in companies if c.get("status") == "查阅中"],
        "files_exist": {k: p.exists() for k, p in configured.items()},
        "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "jd_not_read_count": sum(j.get("jdRead") is not True for j in jobs),
        "scope_overclaims": [c["name"] for c in companies
                             if c.get("coverage", {}).get("complete") is True
                             and c.get("coverage", {}).get("loaded_titles", 0)
                             < c.get("coverage", {}).get("total_titles", 0)],
    }
    checkpoint_path = configured.get("resume_checkpoint")
    if checkpoint_path and checkpoint_path.exists() and checkpoint_path.suffix.lower() == ".json":
        checkpoint = read_json(checkpoint_path)
        result["checkpoint_matches_current_data"] = checkpoint.get("data_sha256") == result["data_sha256"]
        result["pending_sync_count"] = len(checkpoint.get("pending_sync", []))
        result["checkpoint_has_next_step"] = bool(checkpoint.get("next_step"))
    elif checkpoint_path and checkpoint_path.exists():
        result["checkpoint_needs_manual_review"] = True
    ledger_path = configured.get("application_ledger")
    if ledger_path and ledger_path.exists():
        ledger = read_json(ledger_path)
        records = ledger["records"]
        if not isinstance(records, list):
            raise ValueError("Ledger records must be a list")
        result["ledger_record_count"] = len(records)
    if company:
        selected = next((c for c in companies if c["name"] == company), None)
        if selected is None:
            raise ValueError("Requested company is not in the pool")
        result["selected_company"] = selected
        result["selected_jobs"] = [j for j in jobs if j["company"] == company]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--config", default="private/workspace.json")
    parser.add_argument("--company")
    args = parser.parse_args()
    try:
        result = inspect(Path(args.workspace).resolve(), args.config, args.company)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return int(bool(result["duplicate_entities"] or
            result["duplicate_company_names"] or result["scope_overclaims"] or
            result["jobs_outside_company_pool"] or
            not result["stored_coverage_matches"] or
            result.get("checkpoint_matches_current_data") is False or
            any(not value for value in result["files_exist"].values())))
    except (KeyError, ValueError, TypeError, OSError) as error:
        # Do not print raw exceptions that could contain private input values.
        print(json.dumps({"error": type(error).__name__,
                          "hint": "Check config paths and documented JSON schemas."}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
