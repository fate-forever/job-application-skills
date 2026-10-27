"""Synthetic regression cases: no real candidates, employers, or applications."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = os.environ.get("JOB_SKILLS_TEST_TMPDIR")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


app = load("application_tools", "skills/resume-application/scripts/application_tools.py")
tracker = load("tracker_plan", "skills/jobhuntbot/scripts/tracker_plan.py")
eligibility = load("eligibility", "skills/jobhuntbot/scripts/check_eligibility.py")
installer = load("installer", "scripts/install_skills.py")
inspector = load("inspector", "skills/company-job-screening/scripts/inspect_state.py")
privacy = load("privacy", "scripts/check_public_package.py")


def fact(fid="f1", field="education.end", value="2034-06", **extra):
    base = {"id": fid, "field": field, "value": value, "precision": "month",
            "status": "confirmed", "source": {"kind": "user_confirmed", "ref": "local-confirmation-1"},
            "confirmed_at": "2034-03-04T10:00:00+00:00", "scope": {}, "usage": "fact"}
    base.update(extra)
    return base


def profile(facts=None):
    return {"schema_version": 2, "facts": [fact()] if facts is None else facts,
            "resumes": [{"id": "r1", "path": "resume.txt", "version": "v1"}],
            "preferences": {}, "application_contexts": {}}


TARGET = {"company": "Example Labs", "job_id": "SYN-J1", "cohort": "SYN-C1"}


def request():
    return {"target": dict(TARGET), "resume_id": "r1",
            "authorization": {"fill": True, "save": True, "submit": False},
            "fields": [{"field": "education.end", "precision": "month"}],
            "modules": [{"id": "education", "fields": ["education.end"],
                         "entry_ids": ["education-1"], "attachment_ids": ["resume"]}]}


def observation(packet):
    return {"packet_id": packet["packet_id"], "modules": [{
        "id": "education", "status": "saved", "entry_ids": ["education-1"],
        "fields": {"education.end": "2034-06"}, "validation_errors": [],
        "readback": {"kind": "reopened", "ref": "saved-record-1", "observed_at": "2034-03-04T11:00:00+00:00"},
        "attachments": [{"id": "resume", "verified": True, "sha256": packet["resume"]["sha256"]}]
    }], "submission": {"state": "not_submitted"}}


class FactTests(unittest.TestCase):
    def test_scoped_form_answer_never_becomes_global_fact(self):
        f = fact("answer", value="2034-06-15", precision="day", usage="form_answer", scope=dict(TARGET))
        p = profile([fact(), f])
        self.assertEqual(app.resolve_fact(p, "education.end", TARGET, "day", "form_answer")["value"], "2034-06-15")
        self.assertEqual(app.resolve_fact(p, "education.end", TARGET)["value"], "2034-06")
        other = dict(TARGET, job_id="SYN-J2")
        self.assertEqual(app.resolve_fact(p, "education.end", other, "day", "form_answer")["status"], "unknown")

    def test_month_is_not_invented_as_day(self):
        result = app.resolve_fact(profile(), "education.end", TARGET, "day")
        self.assertEqual(result["reason"], "precision_not_confirmed")

    def test_newer_conflicting_source_does_not_win_by_timestamp(self):
        p = profile([fact(), fact("f2", value="2034-07", confirmed_at="2034-03-05T10:00:00+00:00")])
        self.assertEqual(app.resolve_fact(p, "education.end", TARGET)["status"], "conflict")

    def test_explicit_correction_preserves_old_evidence(self):
        p = profile([fact(), fact("f2", value="2034-07", supersedes=["f1"])])
        self.assertEqual(app.resolve_fact(p, "education.end", TARGET)["value"], "2034-07")
        self.assertEqual(len(p["facts"]), 2)

    def test_transitive_correction(self):
        p = profile([fact(), fact("f2", value="2034-07", status="superseded", supersedes=["f1"]),
                     fact("f3", value="2034-08", supersedes=["f2"])])
        self.assertEqual(app.resolve_fact(p, "education.end", TARGET)["value"], "2034-08")

    def test_scope_cannot_supersede_another_application(self):
        p = profile([fact(), fact("f2", scope=dict(TARGET), supersedes=["f1"])])
        with self.assertRaises(app.InputError):
            app.validate_profile(p)

    def test_unknown_fact_is_not_reused(self):
        p = profile([fact(status="unconfirmed")])
        self.assertEqual(app.resolve_fact(p, "education.end", TARGET)["status"], "unknown")

    def test_saved_user_value_is_not_promoted_to_document(self):
        p = profile([fact(source={"kind": "user_entered_saved", "ref": "saved-form"})])
        self.assertEqual(app.resolve_fact(p, "education.end", TARGET)["source"]["kind"], "user_entered_saved")

    def test_duplicate_fact_and_cycle_are_rejected(self):
        with self.assertRaises(app.InputError):
            app.validate_profile(profile([fact(), fact()]))
        with self.assertRaises(app.InputError):
            app.validate_profile(profile([fact(supersedes=["f2"]), fact("f2", supersedes=["f1"])]))

    def test_fact_type_is_not_silently_coerced(self):
        with self.assertRaises(app.InputError):
            app.validate_profile(profile([fact(value=True, precision="number")]))


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEST_TMP)
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        (self.workspace / "resume.txt").write_text("Synthetic resume version one", encoding="utf-8")
        self.profile = profile()
        self.packet = app.build_packet(self.profile, request(), self.workspace)

    def audit(self, observed):
        return app.review_packet(self.packet, observed, self.profile, self.workspace)

    def test_verified_readback_and_no_submission(self):
        report = self.audit(observation(self.packet))
        self.assertTrue(report["verified"])
        self.assertFalse(report["can_report_submitted"])

    def test_packet_build_is_repeatable(self):
        other = app.build_packet(self.profile, request(), self.workspace)
        self.assertEqual(other["packet_id"], self.packet["packet_id"])

    def test_enabled_save_button_is_not_persistence(self):
        observed = observation(self.packet)
        observed["modules"][0]["readback"]["kind"] = "save_button_enabled"
        self.assertFalse(self.audit(observed)["verified"])

    def test_wrong_saved_dropdown_value_is_found(self):
        observed = observation(self.packet)
        observed["modules"][0]["fields"]["education.end"] = "2034-07"
        self.assertFalse(self.audit(observed)["verified"])

    def test_missing_date_control_is_found_even_with_entry(self):
        observed = observation(self.packet)
        observed["modules"][0]["fields"] = {}
        self.assertFalse(self.audit(observed)["verified"])

    def test_merged_or_duplicate_entries_are_found(self):
        observed = observation(self.packet)
        observed["modules"][0]["entry_ids"] = ["education-1", "education-1"]
        self.assertFalse(self.audit(observed)["verified"])

    def test_silent_text_length_failure(self):
        observed = observation(self.packet)
        observed["modules"][0]["field_limits"] = {"education.end": 3}
        self.assertFalse(self.audit(observed)["verified"])

    def test_wrong_attachment_or_missing_primary_resume(self):
        observed = observation(self.packet)
        observed["modules"][0]["attachments"][0]["sha256"] = "0" * 64
        self.assertFalse(self.audit(observed)["verified"])
        observed["modules"][0]["attachments"] = []
        self.assertFalse(self.audit(observed)["verified"])

    def test_changed_resume_invalidates_prior_review(self):
        (self.workspace / "resume.txt").write_text("Changed version", encoding="utf-8")
        self.assertIn("resume_changed_rebuild_packet", self.audit(observation(self.packet))["issues"])

    def test_changed_master_profile_invalidates_review(self):
        self.profile["facts"][0]["value"] = "2034-07"
        self.assertIn("profile_changed_rebuild_packet", self.audit(observation(self.packet))["issues"])

    def test_packet_tampering_is_detected(self):
        self.packet["authorization"]["submit"] = True
        self.assertIn("packet_id_mismatch", self.audit(observation(self.packet))["issues"])

    def test_unauthorized_submission_is_not_reported_as_success(self):
        observed = observation(self.packet)
        observed["submission"] = {"state": "submitted", "target": TARGET,
            "evidence": {"kind": "confirmation_page", "ref": "synthetic-confirmation",
                         "observed_at": "2034-03-04T11:00:00+00:00"}}
        self.assertIn("submission_not_authorized", self.audit(observed)["issues"])
        self.assertFalse(self.audit(observed)["can_report_submitted"])

    def test_authorized_submission_requires_target_specific_evidence(self):
        req = request()
        req["authorization"]["submit"] = True
        self.packet = app.build_packet(self.profile, req, self.workspace)
        observed = observation(self.packet)
        observed["submission"] = {"state": "submitted", "target": TARGET,
            "evidence": {"kind": "application_number", "ref": "SYN-CONFIRM-1",
                         "observed_at": "2034-03-04T11:00:00+00:00"}}
        self.assertTrue(self.audit(observed)["can_report_submitted"])
        observed["submission"]["target"] = dict(TARGET, job_id="SYN-J2")
        self.assertFalse(self.audit(observed)["can_report_submitted"])

    def test_required_field_cannot_be_hidden_from_modules(self):
        req = request()
        req["modules"][0]["fields"] = []
        with self.assertRaises(app.InputError):
            app.build_packet(self.profile, req, self.workspace)

    def test_unconfirmed_optional_value_cannot_be_claimed_as_verified(self):
        req = request()
        req["fields"].append({"field": "optional.claim", "required": False})
        req["modules"][0]["fields"].append("optional.claim")
        self.packet = app.build_packet(self.profile, req, self.workspace)
        observed = observation(self.packet)
        observed["modules"][0]["fields"]["optional.claim"] = "Unsupported synthetic claim"
        self.assertFalse(self.audit(observed)["verified"])

    def test_missing_required_fact_is_a_blocker_not_a_guess(self):
        p = profile([])
        packet = app.build_packet(p, request(), self.workspace)
        self.assertEqual(len(packet["blockers"]), 1)
        self.assertNotIn("value", packet["fields"]["education.end"])

    def test_private_output_is_exclusive_and_workspace_scoped(self):
        app.write_private(self.workspace, "private/report.json", {"ok": True})
        with self.assertRaises(app.InputError):
            app.write_private(self.workspace, "private/report.json", {"ok": False})
        with self.assertRaises(app.InputError):
            app.write_private(self.workspace, "../outside.json", {})

    def test_cli_build_and_review_keep_private_values_out_of_console(self):
        for name, value in (("profile.json", self.profile), ("request.json", request())):
            (self.workspace / name).write_text(json.dumps(value), encoding="utf-8")
        script = ROOT / "skills/resume-application/scripts/application_tools.py"
        base = [sys.executable, "-B", str(script)]
        build = subprocess.run(base + ["build", "--workspace", str(self.workspace), "--profile", "profile.json",
            "--request", "request.json", "--output", "private/packet.json"], capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, build.stderr)
        self.assertNotIn("2034-06", build.stdout)
        built = json.loads((self.workspace / "private/packet.json").read_text(encoding="utf-8"))
        (self.workspace / "saved.json").write_text(json.dumps(observation(built)), encoding="utf-8")
        review = subprocess.run(base + ["review", "--workspace", str(self.workspace), "--profile", "profile.json",
            "--packet", "private/packet.json", "--observed", "saved.json", "--output", "private/review.json"], capture_output=True)
        self.assertEqual(review.returncode, 0)
        self.assertTrue(json.loads((self.workspace / "private/review.json").read_text(encoding="utf-8"))["verified"])


def event(**extra):
    value = {"event_id": "SYN-E1", "identity": {"company": "Example Labs", "title": "Developer", "job_id": "SYN-J1"},
             "observed_at": "2034-03-05T10:00:00+00:00",
             "evidence": {"kind": "official_application_record", "ref": "record-proof"},
             "patch": {"status": "interview"}}
    value.update(extra)
    return value


def record(**extra):
    value = {"id": "SYN-R1", "company": "Example Labs", "role": "Developer", "jobId": "SYN-J1",
             "status": "submitted", "updatedAt": "2034-03-04T10:00:00+00:00", "custom_note": "preserve"}
    value.update(extra)
    return value


class TrackerTests(unittest.TestCase):
    def test_preview_does_not_mutate_source_and_preserves_unknown_fields(self):
        original = [record()]
        before = deepcopy(original)
        result = tracker.plan_updates(original, [event()])
        self.assertTrue(result["safe_to_apply"])
        self.assertEqual(original, before)
        self.assertEqual(result["proposed_records"][0]["custom_note"], "preserve")

    def test_repeated_event_is_idempotent(self):
        result = tracker.plan_updates([record()], [event(), event()])
        self.assertEqual(len(result["actions"]), 1)
        replay = tracker.plan_updates(result["proposed_records"], [event()])
        self.assertEqual(replay["actions"][0]["action"], "unchanged")

    def test_reused_event_id_with_changed_payload_is_rejected(self):
        result = tracker.plan_updates([record()], [event(), event(patch={"status": "offer"})])
        self.assertFalse(result["safe_to_apply"])

    def test_different_job_id_is_not_excluded_by_company(self):
        new = event(identity={"company": "Example Labs", "title": "Developer", "job_id": "SYN-J2"})
        result = tracker.plan_updates([record()], [new])
        self.assertTrue(result["safe_to_apply"])
        self.assertEqual(len(result["proposed_records"]), 2)

    def test_distinct_cohort_is_a_different_entity(self):
        old = record(cohort="SYN-C1")
        new = event(identity={"company": "Example Labs", "title": "Developer", "job_id": "SYN-J1", "cohort": "SYN-C2"})
        result = tracker.plan_updates([old], [new])
        self.assertTrue(result["safe_to_apply"])
        self.assertEqual(len(result["proposed_records"]), 2)

    def test_legacy_missing_job_id_is_not_merged_or_duplicated(self):
        result = tracker.plan_updates([record(jobId="")], [event()])
        self.assertFalse(result["safe_to_apply"])
        self.assertEqual(len(result["proposed_records"]), 1)

    def test_explicit_record_id_resolves_legacy_after_agent_verification(self):
        incoming = event(identity={"company": "Example Labs", "title": "Developer", "job_id": "SYN-J1", "record_id": "SYN-R1"})
        self.assertTrue(tracker.plan_updates([record(jobId="")], [incoming])["safe_to_apply"])

    def test_old_screenshot_cannot_override_new_stage(self):
        result = tracker.plan_updates([record(updatedAt="2034-03-06T10:00:00+00:00")], [event()])
        self.assertFalse(result["safe_to_apply"])

    def test_state_regression_requires_new_explicit_correction(self):
        incoming = event(patch={"status": "submitted"})
        self.assertFalse(tracker.plan_updates([record(status="interview")], [incoming])["safe_to_apply"])
        incoming["correction"] = True
        self.assertTrue(tracker.plan_updates([record(status="interview")], [incoming])["safe_to_apply"])

    def test_saved_form_is_not_submission(self):
        incoming = event(patch={"status": "submitted"}, evidence={"kind": "saved_record", "ref": "saved-form"})
        self.assertFalse(tracker.plan_updates([record(status="pending")], [incoming])["safe_to_apply"])

    def test_existing_duplicate_is_not_arbitrarily_chosen(self):
        self.assertFalse(tracker.plan_updates([record(), record(id="SYN-R2")], [event()])["safe_to_apply"])

    def test_custom_csv_mapping(self):
        rows = [{"employer": "Example Labs", "job_title": "Developer", "code": "SYN-J1", "phase": "pending"}]
        ev = event(patch={"phase": "submitted"})
        result = tracker.plan_updates(rows, [ev], {"company": "employer", "title": "job_title", "job_id": "code", "status": "phase"})
        self.assertTrue(result["safe_to_apply"])
        self.assertEqual(result["proposed_records"][0]["phase"], "submitted")

    def test_terminal_outcome_is_not_erased_by_a_newer_generic_event(self):
        current = record(outcome="rejected")
        result = tracker.plan_updates([current], [event(patch={"outcome": "pending"})])
        self.assertFalse(result["safe_to_apply"])

    def test_record_id_cannot_move_to_another_department(self):
        current = record(department="Department A")
        incoming = event(identity={"record_id": "SYN-R1", "company": "Example Labs", "title": "Developer", "department": "Department B"})
        self.assertFalse(tracker.plan_updates([current], [incoming])["safe_to_apply"])


class EligibilityTests(unittest.TestCase):
    def payload(self):
        return {"target": dict(TARGET), "facts": {"graduation_date": {
            "value": "2034-06", "precision": "month", "confirmed": True, "source_ref": "local-proof"}},
            "rules": [{"id": "window", "kind": "graduation_window", "required": True,
                       "start": "2034-01-01", "end": "2034-12-31",
                       "source": {"ref": "official-notice", "checked_at": "2034-03-01"}}]}

    def test_confirmed_graduation_window(self):
        self.assertEqual(eligibility.evaluate(self.payload())["status"], "eligible_for_checked_rules")

    def test_month_precision_at_midmonth_boundary_remains_unknown(self):
        p = self.payload()
        p["rules"][0]["end"] = "2034-06-15"
        self.assertEqual(eligibility.evaluate(p)["status"], "unknown")

    def test_outside_window_is_ineligible(self):
        p = self.payload()
        p["facts"]["graduation_date"]["value"] = "2035-06"
        self.assertEqual(eligibility.evaluate(p)["status"], "ineligible")

    def test_preferred_paper_is_not_a_hard_requirement(self):
        p = self.payload()
        p["facts"]["paper"] = {"value": False, "confirmed": True, "source_ref": "local-proof"}
        p["rules"].append({"id": "paper", "kind": "requirement", "field": "paper", "expected": True,
                            "required": False, "source": {"ref": "official-jd", "checked_at": "2034-03-01"}})
        result = eligibility.evaluate(p)
        self.assertEqual(result["status"], "eligible_for_checked_rules")
        self.assertEqual(result["rules"][1]["status"], "preference_gap")

    def test_unknown_or_unsourced_fact_does_not_pass(self):
        p = self.payload()
        del p["facts"]["graduation_date"]["source_ref"]
        self.assertEqual(eligibility.evaluate(p)["status"], "unknown")

    def test_full_quota_blocks_another_application(self):
        p = self.payload()
        p["rules"].append({"id": "quota", "kind": "quota", "used": 1, "maximum": 1,
                            "ledger_evidence_ref": "current-ledger", "required": True,
                            "source": {"ref": "official-rule", "checked_at": "2034-03-01"}})
        self.assertEqual(eligibility.evaluate(p)["status"], "ineligible")

    def test_other_cohort_rule_is_not_reused(self):
        p = self.payload()
        p["rules"][0]["scope"] = {"cohort": "SYN-OTHER"}
        self.assertEqual(eligibility.evaluate(p)["status"], "unknown")


class InstallationAndResumeTests(unittest.TestCase):
    def test_all_skills_install_with_valid_local_links_and_templates(self):
        import re
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temp:
            dest = Path(temp) / "installed"
            installer.install(ROOT / "skills", dest, list(installer.SKILLS), True)
            for path in dest.rglob('*.md'):
                for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                    if link.startswith(('https://', 'http://', '#', 'mailto:')):
                        continue
                    self.assertTrue((path.parent / link.split('#')[0]).exists(), str(path.relative_to(dest)))

    def test_dry_run_and_existing_skill_protection(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temp:
            dest = Path(temp) / "installed"
            report = installer.install(ROOT / "skills", dest, ["resume-application"])
            self.assertFalse(dest.exists())
            self.assertFalse(report["applied"])
            installer.install(ROOT / "skills", dest, ["resume-application"], True)
            marker = dest / "resume-application" / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            report = installer.install(ROOT / "skills", dest, ["jobhuntbot", "resume-application"], True)
            self.assertFalse(report["applied"])
            self.assertFalse((dest / "jobhuntbot").exists())
            self.assertEqual(marker.read_text(), "keep")
            self.assertTrue((dest / "resume-application/scripts/application_tools.py").exists())
            self.assertTrue((dest / "resume-application/templates/candidate-data.example.json").exists())

    def test_installed_single_skill_cli_is_independent(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temp:
            dest = Path(temp) / "installed"
            installer.install(ROOT / "skills", dest, ["resume-application"], True)
            run = subprocess.run([sys.executable, "-B", str(dest / "resume-application/scripts/application_tools.py"), "--help"], capture_output=True)
            self.assertEqual(run.returncode, 0)

    def test_checkpoint_staleness_scope_overclaim_and_scoped_duplicates(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temp:
            w = Path(temp)
            data = {"companies": [{"name": "Example Labs", "status": "已检查", "coverage": {
                        "complete": True, "loaded_titles": 10, "total_titles": 20}}],
                    "jobs": [{"company": "Example Labs", "jobId": "SYN-J1", "cohort": "SYN-C1", "jdRead": True},
                             {"company": "Example Labs", "jobId": "SYN-J1", "cohort": "SYN-C2", "jdRead": False}],
                    "coverage": {"已检查": 1}}
            (w / "screening.json").write_text(json.dumps(data), encoding="utf-8")
            (w / "checkpoint.json").write_text(json.dumps({"data_sha256": "old", "next_step": "verify remaining titles", "pending_sync": ["SYN-J1"]}), encoding="utf-8")
            (w / "config.json").write_text(json.dumps({"screening_data": "screening.json", "resume_checkpoint": "checkpoint.json"}), encoding="utf-8")
            result = inspector.inspect(w, "config.json")
            self.assertFalse(result["checkpoint_matches_current_data"])
            self.assertEqual(result["duplicate_entities"], [])
            self.assertEqual(result["scope_overclaims"], ["Example Labs"])
            self.assertEqual(result["jd_not_read_count"], 1)
            (w / "checkpoint.md").write_text("Continue the next company", encoding="utf-8")
            (w / "config.json").write_text(json.dumps({"screening_data": "screening.json", "resume_checkpoint": "checkpoint.md"}), encoding="utf-8")
            self.assertTrue(inspector.inspect(w, "config.json")["checkpoint_needs_manual_review"])


class PrivacyTests(unittest.TestCase):
    def test_contacts_are_detected_without_echoing_values(self):
        contact = 'synthetic' + '@' + 'example.invalid'
        findings = privacy.inspect_content('sample.md', contact.encode())
        self.assertTrue(any(f['rule'] == 'email' for f in findings))
        self.assertNotIn(contact, json.dumps(findings))

    def test_unicode_and_json_escapes_do_not_hide_private_identifiers(self):
        content = json.dumps({'name': 'Candidate Alpha'}, ensure_ascii=True).encode()
        self.assertTrue(any(f['rule'] == 'private_denylist' for f in privacy.inspect_content('sample.json', content, ['Candidate Alpha'])))
        fullwidth = 'Ｃａｎｄｉｄａｔｅ Ａｌｐｈａ'.encode()
        self.assertTrue(any(f['rule'] == 'private_denylist' for f in privacy.inspect_content('sample.md', fullwidth, ['Candidate Alpha'])))

    def test_populated_candidate_and_csv_are_rejected(self):
        candidate = json.dumps({'schema_version': 2, 'facts': [fact()]}).encode()
        self.assertTrue(any(f['rule'] == 'candidate_example_contains_values' for f in privacy.inspect_content('candidate-data.example.json', candidate)))
        self.assertTrue(any(f['rule'] == 'csv_must_be_header_only' for f in privacy.inspect_content('records.csv', b'company,status\nSynthetic,submitted\n')))

    def test_invalid_json_does_not_crash_the_scan(self):
        result = privacy.inspect_content('candidate-data.example.json', b'{')
        self.assertTrue(any(f['rule'] == 'invalid_json' for f in result))

    def test_empty_v2_template_is_allowed(self):
        data = (ROOT / 'examples/candidate-data.example.json').read_bytes()
        self.assertEqual(privacy.inspect_content('candidate-data.example.json', data), [])

    def test_private_windows_path_is_rejected_even_when_json_escaped(self):
        private_path = 'Q:' + chr(92) + 'Users' + chr(92) + 'SyntheticUser' + chr(92) + 'resume.txt'
        data = json.dumps({'path': private_path}).encode()
        self.assertTrue(any(f['rule'] == 'personal_windows_path' for f in privacy.inspect_content('sample.json', data)))

    def test_blocked_runtime_and_binary_files_are_rejected(self):
        self.assertTrue(privacy.inspect_content('private/packet.json', b'{}'))
        self.assertTrue(privacy.inspect_content('photo.png', bytes([255, 0, 200])))

    def test_sensitive_filename_is_redacted_in_findings(self):
        findings = privacy.inspect_content('Candidate Alpha.md', b'Synthetic content', ['Candidate Alpha'])
        self.assertNotIn('Candidate Alpha', json.dumps(findings))
        self.assertTrue(any(f['rule'] == 'private_denylist' for f in findings))


if __name__ == "__main__":
    unittest.main()
