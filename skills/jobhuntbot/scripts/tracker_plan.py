#!/usr/bin/env python3
"""Preview evidence-backed ledger changes; never write the ledger or submit jobs."""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import unicodedata

DEFAULT_FIELDS = {"company": "company", "title": "role", "job_id": "jobId",
                  "department": "department", "cohort": "cohort", "record_id": "id",
                  "updated_at": "updatedAt", "status": "status", "outcome": "outcome"}
PROGRESS = {"pending": 0, "submitted": 1, "assessment": 2, "interview": 3,
            "offer": 4, "rejected": 4, "terminated": 4,
            "待投递": 0, "已投递": 1, "测评": 2, "面试": 3, "录用": 4, "流程终止": 4}
SUBMISSION_KINDS = {"submission_confirmation", "official_application_record", "user_confirmed_submission"}


def norm(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split()).casefold()


def parsed_time(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone_required")
    return dt


def records_from(path):
    payload = Path(path).read_bytes()
    if Path(path).suffix.lower() == ".csv":
        import io
        records = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    else:
        data = json.loads(payload.decode("utf-8-sig"))
        records = data.get("records") if isinstance(data, dict) else data
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise ValueError("records_array_required")
    return records, hashlib.sha256(payload).hexdigest()


def identity(record, fields):
    return {key: norm(record.get(fields[key])) for key in
            ("company", "title", "job_id", "department", "cohort", "record_id")}


def matches(a, b):
    if not a["company"] or a["company"] != b["company"]:
        return False
    # Department and recruitment cohort are part of an application entity.
    if a["department"] != b["department"] or a["cohort"] != b["cohort"]:
        return False
    if a["job_id"] or b["job_id"]:
        return bool(a["job_id"] and b["job_id"] and a["job_id"] == b["job_id"])
    return bool(a["title"] and a["title"] == b["title"])


def plan_updates(records, events, fields=None, status_order=None):
    fields = dict(DEFAULT_FIELDS, **(fields or {}))
    order = dict(PROGRESS, **(status_order or {}))
    working = [dict(r) for r in records]
    actions, conflicts, seen = [], [], {}
    for index, event in enumerate(events):
        def reject(reason):
            conflicts.append({"event_index": index, "reason": reason})
        event_id = event.get("event_id")
        encoded = json.dumps(event, sort_keys=True, ensure_ascii=True)
        if not event_id:
            reject("event_id_required")
            continue
        if event_id in seen:
            if seen[event_id] != encoded:
                reject("event_id_reused_with_different_payload")
            continue
        seen[event_id] = encoded
        try:
            observed_at = parsed_time(event["observed_at"])
        except (ValueError, TypeError, KeyError, AttributeError):
            reject("event_timestamp_with_timezone_required")
            continue
        evidence = event.get("evidence", {})
        if not evidence.get("kind") or not evidence.get("ref"):
            reject("evidence_required")
            continue
        raw = event.get("identity", {})
        target = {k: norm(raw.get(k)) for k in
                  ("company", "title", "job_id", "department", "cohort", "record_id")}
        if not target["company"] or not (target["job_id"] or target["title"]):
            reject("specific_job_identity_required")
            continue
        candidates = []
        for i, row in enumerate(working):
            current = identity(row, fields)
            if target["record_id"]:
                if target["record_id"] != current["record_id"]:
                    continue
                if current["company"] != target["company"] or any(
                        current[k] and target[k] and current[k] != target[k]
                        for k in ("job_id", "department", "cohort")):
                    reject("record_id_identity_conflict")
                    candidates = None
                    break
                candidates.append(i)
            elif matches(current, target):
                candidates.append(i)
        if candidates is None:
            continue
        if len(candidates) > 1:
            reject("ambiguous_existing_entity")
            continue
        # Missing cohort/department/ID in legacy records is not proof of a new job.
        def ambiguous_legacy(row):
            current = identity(row, fields)
            if current["company"] != target["company"]:
                return False
            if any(current[k] and target[k] and current[k] != target[k]
                   for k in ("job_id", "department", "cohort")):
                return False
            return bool((target["title"] and current["title"] == target["title"])
                        or (target["job_id"] and current["job_id"] == target["job_id"]))
        if not candidates and any(ambiguous_legacy(r) for r in working):
            reject("legacy_identity_needs_explicit_record_or_distinct_scope")
            continue
        patch = event.get("patch", {})
        if not isinstance(patch, dict) or not patch:
            reject("nonempty_patch_required")
            continue
        identity_columns = {fields[k] for k in ("company", "title", "job_id", "department", "cohort", "record_id")}
        if identity_columns.intersection(patch):
            reject("identity_changes_require_manual_resolution")
            continue
        status = patch.get(fields["status"])
        if norm(status) in {"submitted", "已投递"} and evidence["kind"] not in SUBMISSION_KINDS:
            reject("saved_form_is_not_submission_evidence")
            continue
        row_index = candidates[0] if candidates else None
        current = working[row_index] if row_index is not None else {}
        if candidates and all(current.get(k) == v for k, v in patch.items()):
            actions.append({"event_index": index, "action": "unchanged", "record_index": row_index})
            continue
        previous_time = current.get(fields["updated_at"])
        if previous_time:
            try:
                old_time = parsed_time(previous_time)
            except (ValueError, TypeError, AttributeError):
                reject("existing_timestamp_requires_mapping_or_review")
                continue
            if observed_at <= old_time:
                reject("stale_or_concurrent_evidence")
                continue
        old_status = norm(current.get(fields["status"]))
        new_status = norm(status)
        correction = event.get("correction") is True and evidence["kind"] in {
            "official_application_record", "user_confirmed_correction"}
        outcome_field = fields["outcome"]
        if (norm(current.get(outcome_field)) in {"offer", "rejected", "terminated", "录用", "流程终止"}
                and outcome_field in patch and patch[outcome_field] != current.get(outcome_field)
                and not correction):
            reject("terminal_outcome_change_requires_explicit_correction")
            continue
        if status is not None and old_status in order and new_status in order and order[new_status] < order[old_status]:
            if not correction:
                reject("progress_regression_requires_explicit_correction")
                continue
        if candidates:
            changed = dict(current, **patch)
            changed[fields["updated_at"]] = event["observed_at"]
            working[row_index] = changed
            actions.append({"event_index": index, "action": "update", "record_index": row_index,
                            "changed_fields": sorted(k for k, v in patch.items() if current.get(k) != v)})
        else:
            if target["record_id"]:
                reject("explicit_record_id_not_found")
                continue
            added = {fields[k]: raw[k] for k in ("company", "title", "job_id", "department", "cohort") if raw.get(k)}
            added.update(patch)
            added[fields["updated_at"]] = event["observed_at"]
            working.append(added)
            actions.append({"event_index": index, "action": "insert", "record_index": len(working) - 1,
                            "changed_fields": sorted(added)})
    return {"safe_to_apply": not conflicts, "actions": actions, "conflicts": conflicts,
            "proposed_records": working,
            "limits": "Preview only. Use the existing authorized writer and recheck the source hash before applying."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--mapping", help="Optional field-name and status-order mapping JSON")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        records, sha = records_from(args.ledger)
        events = json.loads(Path(args.events).read_text(encoding="utf-8-sig"))
        if not isinstance(events, list):
            raise ValueError()
        mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8-sig")) if args.mapping else {}
        result = plan_updates(records, events, mapping.get("fields"), mapping.get("status_order"))
        result["source_sha256"] = sha
        output = Path(args.output).resolve()
        if output in {Path(args.ledger).resolve(), Path(args.events).resolve()}:
            raise ValueError()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(json.dumps({"safe_to_apply": result["safe_to_apply"],
                          "actions": len(result["actions"]), "conflicts": len(result["conflicts"]),
                          "ledger_modified": False}))
        return 0 if result["safe_to_apply"] else 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print('{"error":"invalid_input_or_output","ledger_modified":false}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
