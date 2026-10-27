#!/usr/bin/env python3
"""Evaluate sourced deterministic eligibility rules, not semantic job fit."""
import argparse
import calendar
from datetime import date
import json
from pathlib import Path
import re
import sys


def interval(value, precision):
    if precision == "day" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        d = date.fromisoformat(value)
        return d, d
    if precision == "month" and re.fullmatch(r"\d{4}-\d{2}", value):
        year, month = map(int, value.split("-"))
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    if precision == "year" and re.fullmatch(r"\d{4}", value):
        year = int(value)
        return date(year, 1, 1), date(year, 12, 31)
    raise ValueError("date_precision_required")


def evaluate(payload):
    facts, target = payload.get("facts", {}), payload.get("target", {})
    results = []
    for rule in payload.get("rules", []):
        result = {"rule_id": rule["id"], "status": "unknown", "reason": "source_or_fact_missing",
                  "required": rule.get("required", True)}
        source = rule.get("source", {})
        if not source.get("ref") or not source.get("checked_at"):
            results.append(result)
            continue
        date.fromisoformat(source["checked_at"])
        scope = rule.get("scope", {})
        if any(target.get(k) != v for k, v in scope.items()):
            result.update(status="not_applicable", reason="different_recruitment_scope")
            results.append(result)
            continue
        try:
            kind = rule["kind"]
            if kind == "graduation_window":
                fact = facts.get(rule.get("field", "graduation_date"), {})
                if fact.get("confirmed") is not True or not fact.get("source_ref"):
                    results.append(result)
                    continue
                low, high = interval(fact["value"], fact["precision"])
                start, end = date.fromisoformat(rule["start"]), date.fromisoformat(rule["end"])
                if start > end:
                    raise ValueError()
                if start <= low and high <= end:
                    result.update(status="pass", reason="whole_confirmed_interval_within_window")
                elif high < start or low > end:
                    result.update(status="fail", reason="outside_window")
                else:
                    result.update(reason="date_precision_overlaps_boundary")
            elif kind == "requirement":
                fact = facts.get(rule["field"], {})
                if fact.get("confirmed") is True and fact.get("source_ref") and "value" in fact:
                    matched = type(fact["value"]) is type(rule["expected"]) and fact["value"] == rule["expected"]
                    result.update(status="pass" if matched else "fail", reason="confirmed_value_comparison")
            elif kind == "quota":
                used, maximum = rule.get("used"), rule.get("maximum")
                if type(used) is int and type(maximum) is int and used >= 0 and maximum > 0 and rule.get("ledger_evidence_ref"):
                    result.update(status="pass" if used < maximum else "fail", reason="verified_application_quota")
            else:
                result["reason"] = "unsupported_rule_requires_agent_review"
        except (ValueError, TypeError, KeyError):
            result.update(status="unknown", reason="invalid_or_incomplete_rule")
        if not result["required"] and result["status"] == "fail":
            result.update(status="preference_gap", reason="preferred_not_required")
        results.append(result)
    hard = [r for r in results if r["required"] and r["status"] != "not_applicable"]
    status = ("ineligible" if any(r["status"] == "fail" for r in hard)
              else "unknown" if not hard or any(r["status"] == "unknown" for r in hard)
              else "eligible_for_checked_rules")
    return {"status": status, "rules": results,
            "limits": "Covers only supplied sourced rules. No live verification, semantic fit score or hiring probability."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = evaluate(json.loads(Path(args.input).read_text(encoding="utf-8-sig")))
        output = Path(args.output)
        if output.resolve() == Path(args.input).resolve():
            raise ValueError()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(json.dumps({"status": result["status"], "rule_count": len(result["rules"])}))
        return 0 if result["status"] == "eligible_for_checked_rules" else 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print('{"error":"invalid_input_or_output"}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
