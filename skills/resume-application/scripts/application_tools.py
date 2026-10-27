#!/usr/bin/env python3
"""Build a private application packet and compare supplied saved-value evidence.

Standard library only. Never operates a browser, submits an application, or
changes the candidate's master profile. JSON outputs belong in a private folder.
"""
import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata


class InputError(ValueError):
    pass


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def timestamp(value):
    if not isinstance(value, str):
        raise InputError("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed
    except ValueError:
        raise InputError("invalid_timestamp") from None


def valid_precision(value, precision):
    if precision is None:
        return True
    if precision == "text":
        return isinstance(value, str)
    if precision == "number":
        return type(value) in (int, float)
    if precision == "boolean":
        return type(value) is bool
    if not isinstance(value, str):
        return False
    try:
        if precision == "day":
            return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and bool(date.fromisoformat(value))
        if precision == "month":
            return bool(re.fullmatch(r"\d{4}-\d{2}", value)) and bool(date.fromisoformat(value + "-01"))
        if precision == "year":
            return bool(re.fullmatch(r"\d{4}", value)) and 1 <= int(value) <= 9999
    except ValueError:
        return False
    return False


def validate_profile(profile):
    if profile.get("schema_version") != 2 or not isinstance(profile.get("facts"), list):
        raise InputError("profile_schema_v2_required")
    ids = [f.get("id") for f in profile["facts"]]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise InputError("duplicate_or_missing_fact_id")
    id_set = set(ids)
    edges = {}
    for fact in profile["facts"]:
        if not isinstance(fact.get("field"), str) or not fact["field"]:
            raise InputError("missing_fact_field")
        if fact.get("status") not in {"confirmed", "unconfirmed", "superseded"}:
            raise InputError("invalid_fact_status")
        usage = fact.get("usage", "fact")
        if usage not in {"fact", "form_answer"}:
            raise InputError("invalid_fact_usage")
        scope = fact.get("scope", {})
        if not isinstance(scope, dict) or any(not v for v in scope.values()):
            raise InputError("invalid_scope")
        if usage == "form_answer" and not (scope.get("job_id") or scope.get("application_id")):
            raise InputError("form_answer_requires_application_scope")
        if usage == "form_answer" and not scope.get("company"):
            raise InputError("form_answer_requires_company")
        source = fact.get("source", {})
        if fact["status"] == "confirmed":
            if source.get("kind") not in {"document", "user_confirmed", "user_entered_saved"} or not source.get("ref"):
                raise InputError("confirmed_fact_requires_source")
            timestamp(fact.get("confirmed_at"))
            if fact.get("value") is None or not valid_precision(fact["value"], fact.get("precision")):
                raise InputError("invalid_confirmed_value")
        supersedes = fact.get("supersedes", [])
        if not isinstance(supersedes, list) or not set(supersedes) <= id_set or fact["id"] in supersedes:
            raise InputError("invalid_supersedes")
        for old in supersedes:
            prior = next(f for f in profile["facts"] if f["id"] == old)
            if (prior["field"], prior.get("usage", "fact"), prior.get("scope", {})) != (
                    fact["field"], usage, scope):
                raise InputError("supersedes_scope_or_field_mismatch")
        edges[fact["id"]] = supersedes
    def visit(node, active, done):
        if node in active:
            raise InputError("supersedes_cycle")
        if node in done:
            return
        for child in edges[node]:
            visit(child, active | {node}, done)
        done.add(node)
    done = set()
    for node in edges:
        visit(node, set(), done)


def resolve_fact(profile, field, target, precision=None, purpose="fact"):
    validate_profile(profile)
    if purpose not in {"fact", "form_answer"}:
        raise InputError("invalid_purpose")
    candidates = [f for f in profile["facts"] if f["field"] == field
                  and f["status"] == "confirmed"
                  and all(target.get(k) == v for k, v in f.get("scope", {}).items())
                  and (purpose == "form_answer" or f.get("usage", "fact") == "fact")]
    if purpose == "form_answer":
        answers = [f for f in candidates if f.get("usage") == "form_answer"]
        candidates = answers or [f for f in candidates if f.get("usage", "fact") == "fact"]
    by_id = {f["id"]: f for f in profile["facts"]}
    replaced = set()
    def replace_ancestors(fact):
        for old_id in fact.get("supersedes", []):
            if old_id not in replaced:
                replaced.add(old_id)
                replace_ancestors(by_id[old_id])
    for fact in candidates:
        replace_ancestors(fact)
    candidates = [f for f in candidates if f["id"] not in replaced]
    if not candidates:
        return {"status": "unknown", "reason": "no_confirmed_applicable_fact"}
    # A newer timestamp alone never resolves different factual claims.
    if len({digest(f["value"]) for f in candidates}) > 1:
        return {"status": "conflict", "reason": "conflicting_confirmed_sources",
                "fact_ids": [f["id"] for f in candidates]}
    if precision:
        candidates = [f for f in candidates if f.get("precision") == precision
                      and valid_precision(f["value"], precision)]
        if not candidates:
            return {"status": "unknown", "reason": "precision_not_confirmed"}
    chosen = max(candidates, key=lambda f: timestamp(f["confirmed_at"]))
    return {"status": "resolved", "fact_id": chosen["id"], "value": chosen["value"],
            "source": chosen["source"], "confirmed_at": chosen["confirmed_at"],
            "precision": chosen.get("precision"), "scope": chosen.get("scope", {}),
            "usage": chosen.get("usage", "fact")}


def material_path(workspace, value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(workspace) / path


def build_packet(profile, request, workspace):
    validate_profile(profile)
    target = request.get("target", {})
    if not target.get("company") or not (target.get("job_id") or target.get("application_id")):
        raise InputError("specific_application_target_required")
    authorization = request.get("authorization", {})
    if any(type(authorization.get(k, False)) is not bool for k in ("fill", "save", "submit")):
        raise InputError("authorization_must_be_boolean")
    fields = request.get("fields", [])
    names = [f["field"] for f in fields]
    if len(names) != len(set(names)):
        raise InputError("duplicate_requested_field")
    results, blockers = {}, []
    for spec in fields:
        name = spec["field"]
        results[name] = resolve_fact(profile, name, target, spec.get("precision"),
                                     spec.get("purpose", "fact"))
        results[name]["required"] = spec.get("required", True)
        if results[name]["status"] != "resolved" and spec.get("required", True):
            blockers.append({"field": name, "reason": results[name]["reason"]})
    resume_id = request.get("resume_id")
    resumes = [r for r in profile.get("resumes", []) if r.get("id") == resume_id]
    if not resume_id or len(resumes) != 1:
        raise InputError("unique_selected_resume_required")
    resume = resumes[0]
    path = material_path(workspace, resume["path"])
    if path.is_symlink() or not path.is_file():
        raise InputError("resume_missing_or_symlink")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if resume.get("sha256") and resume["sha256"] != sha:
        raise InputError("resume_version_hash_changed")
    modules = request.get("modules", [])
    module_ids = [m["id"] for m in modules]
    if not modules or len(module_ids) != len(set(module_ids)):
        raise InputError("unique_expected_modules_required")
    for module in modules:
        if not set(module.get("fields", [])) <= set(names):
            raise InputError("module_contains_unrequested_field")
        entries = module.get("entry_ids", [])
        if len(entries) != len(set(entries)):
            raise InputError("duplicate_expected_entry")
    covered = {f for m in modules for f in m.get("fields", [])}
    if any(f["field"] not in covered for f in fields if f.get("required", True)):
        raise InputError("required_fields_not_covered_by_modules")
    packet = {"schema_version": 2, "target": target,
              "profile_sha256": digest(profile), "fields": results,
              "resume": {"id": resume_id, "path": resume["path"],
                         "version": resume.get("version"), "sha256": sha},
              "modules": modules, "blockers": blockers,
              "authorization": {k: authorization.get(k, False) for k in ("fill", "save", "submit")}}
    packet["packet_id"] = digest(packet)
    return packet


def normalized(value):
    if isinstance(value, str):
        return " ".join(unicodedata.normalize("NFKC", value).split())
    return value


def equal_values(a, b):
    return type(a) is type(b) and normalized(a) == normalized(b)


def evidence_valid(evidence, kinds):
    if not isinstance(evidence, dict) or evidence.get("kind") not in kinds or not evidence.get("ref"):
        return False
    try:
        timestamp(evidence.get("observed_at"))
        return True
    except InputError:
        return False


def review_packet(packet, observed, profile, workspace):
    integrity = dict(packet)
    packet_id = integrity.pop("packet_id", None)
    issues = []
    if packet_id != digest(integrity) or observed.get("packet_id") != packet_id:
        issues.append("packet_id_mismatch")
    if packet["profile_sha256"] != digest(profile):
        issues.append("profile_changed_rebuild_packet")
    path = material_path(workspace, packet["resume"]["path"])
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != packet["resume"]["sha256"]:
        issues.append("resume_changed_rebuild_packet")
    if packet.get("blockers"):
        issues.append("unresolved_required_fields")
    modules = observed.get("modules", [])
    ids = [m.get("id") for m in modules]
    if len(ids) != len(set(ids)):
        issues.append("duplicate_observed_module")
    results = []
    for expected in packet["modules"]:
        current = next((m for m in modules if m.get("id") == expected["id"]), {})
        errors = []
        if current.get("status") != "saved":
            errors.append("not_saved")
        if not evidence_valid(current.get("readback"), {"reopened", "refresh", "saved_record"}):
            errors.append("persisted_readback_missing")
        actual_entries = current.get("entry_ids", [])
        expected_entries = expected.get("entry_ids", [])
        if len(actual_entries) != len(set(actual_entries)) or set(actual_entries) != set(expected_entries):
            errors.append("entry_ids_or_count_mismatch")
        for name in expected.get("fields", []):
            fact = packet["fields"][name]
            if fact["status"] != "resolved":
                if fact.get("required", True):
                    errors.append("unresolved_field:" + name)
                elif current.get("fields", {}).get(name) not in (None, ""):
                    errors.append("unconfirmed_optional_value:" + name)
                continue
            actual = current.get("fields", {})
            if name not in actual or not equal_values(fact["value"], actual[name]):
                errors.append("saved_value_mismatch:" + name)
            limit = current.get("field_limits", {}).get(name)
            if limit is not None and isinstance(fact["value"], str):
                if not isinstance(limit, int) or limit < 0:
                    errors.append("invalid_field_limit:" + name)
                elif len(fact["value"].encode("utf-16-le")) // 2 > limit:
                    errors.append("field_limit_exceeded:" + name)
        if current.get("validation_errors"):
            errors.append("website_validation_errors")
        attachments = current.get("attachments", [])
        for attachment_id in expected.get("attachment_ids", []):
            found = [a for a in attachments if a.get("id") == attachment_id]
            if len(found) != 1 or found[0].get("verified") is not True:
                errors.append("attachment_unverified:" + attachment_id)
            elif attachment_id == "resume" and found[0].get("sha256") != packet["resume"]["sha256"]:
                errors.append("resume_attachment_version_mismatch")
        results.append({"module": expected["id"], "verified": not errors, "issues": errors})
    submission = observed.get("submission", {"state": "not_submitted"})
    state = submission.get("state")
    if state not in {"not_submitted", "unknown", "submitted"}:
        issues.append("invalid_submission_state")
    if state == "submitted":
        if not packet["authorization"]["submit"]:
            issues.append("submission_not_authorized")
        if submission.get("target") != packet["target"]:
            issues.append("submission_target_mismatch")
        if not evidence_valid(submission.get("evidence"), {
                "confirmation_page", "application_number", "official_application_record"}):
            issues.append("submission_success_unconfirmed")
    verified = bool(results) and all(m["verified"] for m in results) and not issues
    return {"packet_id": packet_id, "verified": verified,
            "modules": results, "issues": issues, "submission_state": state,
            "can_report_submitted": state == "submitted" and verified,
            "limits": "Checks supplied evidence, not the current website or user authorization itself."}


def write_private(workspace, output, value):
    root = Path(workspace).resolve()
    path = material_path(root, output).resolve()
    if not path.is_relative_to(root) or path == root:
        raise InputError("output_must_be_inside_workspace")
    if path.exists():
        raise InputError("output_exists_choose_new_version")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create also prevents a race from overwriting an existing packet.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "review"])
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--request")
    parser.add_argument("--packet")
    parser.add_argument("--observed")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        workspace = Path(args.workspace).resolve()
        profile = read_json(material_path(workspace, args.profile))
        if args.command == "build":
            if not args.request:
                raise InputError("request_required")
            result = build_packet(profile, read_json(material_path(workspace, args.request)), workspace)
            ok = not result["blockers"]
        else:
            if not args.packet or not args.observed:
                raise InputError("packet_and_observed_required")
            result = review_packet(read_json(material_path(workspace, args.packet)),
                                   read_json(material_path(workspace, args.observed)), profile, workspace)
            ok = result["verified"]
        write_private(workspace, args.output, result)
        print(json.dumps({"ok": ok, "saved": True, "private_values_printed": False}))
        return 0 if ok else 1
    except (InputError, OSError, ValueError, KeyError, TypeError, AttributeError):
        print(json.dumps({"ok": False, "error": "invalid_input_or_output",
                          "hint": "Check the local schema and choose a new private output path."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
