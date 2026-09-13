#!/usr/bin/env python3
"""Executable semantic tests for accepted-term handoff review vectors."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import unittest
from datetime import datetime
from pathlib import Path

from jsonschema import Draft7Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
VECTOR_DIR = ROOT / "vectors"
SCHEMA_PATH = ROOT / "schema" / "test-vector.schema.json"
CAPABILITIES_PATH = ROOT / "models" / "model-capabilities.json"
MODELS = ("opaque_reference", "portable_artifact")
VERDICT_RANK = {"PASS": 0, "AMBIGUOUS": 1, "FAIL": 2}
LEGACY_VECTOR_SHA256 = {
    "V1": "e32f07fd98c94ec27b12975c78e3061581db40c53d59081b239299f64d4c1360",
    "V2": "6ad8f68a7e4a1c04cb4f7a2f5e33d8533188c2e5c331ef476794217481d2ef09",
    "V3": "0407cec74152b80f9911c2d01e08b8cc554cddbf81ee62221de344ad7da76fa0",
    "V4": "285693cfc05cd6e8447ff038a0f55ba1d7a54f2f707803a00207b28db12ff978",
    "V5": "cee27e64e962aa6ad33377e9e1d339e3a3c3ff21c778828e557289e5081dcae7",
    "V6": "602d6cb78230636d80d69dd80ffaf0e9f55a4175cd74773e153e0cd80ca06d50",
    "V7": "9bf73f52f81f4ab00fbbfd7c7fe51ff893d3fc14aa1e5b6282198eb791282c4a",
}


def load_json(path: Path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def load_vectors():
    vectors = [load_json(path) for path in VECTOR_DIR.glob("*.json")]
    return sorted(vectors, key=lambda vector: int(vector["id"][1:]))


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def result(recognized, artifact_valid, bindable, outcome, reason):
    return {
        "recognized": recognized,
        "artifact_valid": artifact_valid,
        "bindable": bindable,
        "outcome": outcome,
        "reason": reason,
    }


def line_identity(line):
    return line.get("line_id", line["item_id"])


def evaluate_binding_units(vector):
    artifact = vector["term_artifact"]
    request = vector["binding_request"]
    artifact_lines = {line_identity(line) for line in artifact["lines"]}
    requested_lines = {line_identity(line) for line in request["lines"]}
    unit_lines = [line_id for unit in vector["binding_units"] for line_id in unit["line_ids"]]

    if len(unit_lines) != len(set(unit_lines)):
        return result(True, False, False, "invalid_artifact", "scope_expansion")
    grouped_lines = set(unit_lines)
    if grouped_lines - requested_lines or requested_lines - artifact_lines:
        return result(True, False, False, "invalid_artifact", "scope_expansion")
    if artifact_lines - grouped_lines or requested_lines - grouped_lines:
        return result(True, False, False, "invalid_artifact", "scope_contraction")

    unit_results = []
    for unit in vector["binding_units"]:
        if unit["accepted_revision"] != artifact["revision"]:
            unit_result = {
                "binding_unit_id": unit["id"], "result": "binding_unit_rejected", "reason": "stale_revision",
                "effective_bound_line_ids": [], "newly_bound_line_ids": [],
            }
        elif set(unit["line_ids"]) - artifact_lines:
            unit_result = {
                "binding_unit_id": unit["id"], "result": "binding_unit_rejected", "reason": "atomicity_violation",
                "effective_bound_line_ids": [], "newly_bound_line_ids": [],
            }
        elif unit["prior_binding"] is not None:
            prior = unit["prior_binding"]
            replay_identity = (
                prior["artifact_id"] == artifact["id"]
                and prior["revision"] == unit["accepted_revision"]
                and prior["binding_unit_id"] == unit["id"]
                and prior["line_ids"] == unit["line_ids"]
                and prior["idempotency_key"] == unit["idempotency_key"]
                and prior["target_transaction"] == unit["target_transaction"]
            )
            unit_result = {
                "binding_unit_id": unit["id"],
                "result": "idempotent_replay" if replay_identity else "binding_unit_rejected",
                "reason": "already_bound" if replay_identity else "idempotency_conflict",
                "effective_bound_line_ids": unit["line_ids"] if replay_identity else [],
                "newly_bound_line_ids": [],
            }
        elif unit.get("prior_failure") is not None:
            prior = unit["prior_failure"]
            same_failed_attempt = (
                prior["artifact_id"] == artifact["id"]
                and prior["revision"] == unit["accepted_revision"]
                and prior["binding_unit_id"] == unit["id"]
                and prior["line_ids"] == unit["line_ids"]
                and prior["idempotency_key"] == unit["idempotency_key"]
                and prior["target_transaction"] == unit["target_transaction"]
            )
            unit_result = {
                "binding_unit_id": unit["id"],
                "result": "binding_unit_rejected",
                "reason": prior["reason"] if same_failed_attempt else "idempotency_conflict",
                "effective_bound_line_ids": [],
                "newly_bound_line_ids": [],
            }
        elif unit["unavailable_line_ids"]:
            # Current harness mode is all_or_nothing: one failed dependency rejects the unit.
            unit_result = {
                "binding_unit_id": unit["id"], "result": "binding_unit_rejected", "reason": "line_unavailable",
                "effective_bound_line_ids": [], "newly_bound_line_ids": [],
            }
        else:
            unit_result = {
                "binding_unit_id": unit["id"], "result": "bound", "reason": "bound",
                "effective_bound_line_ids": unit["line_ids"], "newly_bound_line_ids": unit["line_ids"],
            }
        unit_results.append(unit_result)

    effective = {line_id for unit in unit_results for line_id in unit["effective_bound_line_ids"]}
    newly = {line_id for unit in unit_results for line_id in unit["newly_bound_line_ids"]}
    failed = requested_lines - effective
    successes = [unit for unit in unit_results if unit["result"] in ("bound", "idempotent_replay")]
    failures = [unit for unit in unit_results if unit["result"] == "binding_unit_rejected"]
    if successes and failures:
        outcome, reason, bindable = "partially_bound", "partial_binding", True
    elif failures:
        outcome, reason, bindable = "recognized_rejected", "binding_unit_rejected", False
    else:
        outcome, reason, bindable = "bound", "bound", True
    answer = result(True, True, bindable, outcome, reason)
    answer.update({
        "unit_results": unit_results,
        "effective_bound_line_count": len(effective),
        "newly_bound_line_count": len(newly),
        "failed_line_count": len(failed),
    })
    return answer


def evaluate_post_bind(vector):
    post_bind = vector["post_bind"]
    semantics = post_bind["governing_semantics"]
    attempt = post_bind["execution_attempt"]
    active = set(attempt["active_invalidation_conditions"])
    allowed = set(semantics["execution_invalidation_conditions"])

    if not attempt["terms_unchanged"]:
        return {"status": "post_bind_invalidated", "reason": "commercial_terms_reinterpreted", "executed": False, "terms_preserved": False}
    if semantics["mode"] == "conditional_release":
        if attempt["release_condition_met"] is None:
            return {"status": "release_pending", "reason": "release_condition_pending", "executed": False, "terms_preserved": True}
        if not attempt["release_condition_met"]:
            return {"status": "release_condition_failed", "reason": "delivery_not_confirmed", "executed": False, "terms_preserved": True}
    if active.intersection(allowed):
        reason = sorted(active.intersection(allowed))[0]
        return {"status": "post_bind_invalidated", "reason": reason, "executed": False, "terms_preserved": True}
    if semantics["mode"] == "term_expiry_continues" and instant(attempt["at"]) >= instant(vector["term_artifact"]["expires_at"]):
        return {"status": "post_bind_invalidated", "reason": "term_expired_after_binding", "executed": False, "terms_preserved": True}
    deadline = semantics["post_bind_valid_until"]
    if semantics["mode"] == "post_bind_deadline" and deadline and instant(attempt["at"]) >= instant(deadline):
        return {"status": "post_bind_invalidated", "reason": "post_bind_deadline_elapsed", "executed": False, "terms_preserved": True}
    return {"status": "executed", "reason": "executed", "executed": True, "terms_preserved": True}


def evaluate(vector):
    """Apply the candidate invariants independently of either wire model."""
    artifact = vector["term_artifact"]
    request = vector["binding_request"]
    state = vector["business_state"]

    if not state["artifact_known"]:
        return result(False, False, False, "invalid_artifact", "unknown_artifact")
    if not state["artifact_authentic"]:
        return result(True, False, False, "invalid_artifact", "forged_artifact")
    if not state["issuer_authorized"]:
        return result(True, False, False, "invalid_artifact", "unauthorized_issuer")
    if request["artifact_id"] != artifact["id"] or request["issuer"] != artifact["issuer"] or request["buyer"] != artifact["buyer_scope"]:
        return result(True, False, False, "invalid_artifact", "identity_mismatch")
    if request["revision"] != artifact["revision"] or artifact["revision"] != state["current_revision"]:
        return result(True, False, False, "invalid_artifact", "stale_revision")

    acceptance = artifact["acceptance"]
    if (
        acceptance["state"] not in ("accepted", "awarded")
        or acceptance["accepted_revision"] != artifact["revision"]
        or request["acceptance_state"] != acceptance["state"]
        or request["accepted_revision"] != acceptance["accepted_revision"]
    ):
        return result(True, False, False, "invalid_artifact", "not_accepted")
    if instant(request["at"]) >= instant(artifact["expires_at"]):
        return result(True, False, False, "invalid_artifact", "expired")
    if request["currency"] != artifact["currency"]:
        return result(True, False, False, "invalid_artifact", "currency_mismatch")
    if request["commercial_terms"] != artifact["commercial_terms"]:
        return result(True, False, False, "invalid_artifact", "commercial_terms_mismatch")

    accepted_lines = {line["item_id"]: line for line in artifact["lines"]}
    for requested in request["lines"]:
        accepted = accepted_lines.get(requested["item_id"])
        if accepted is None or requested["quantity"] > accepted["quantity"] or requested["unit_price"] != accepted["unit_price"]:
            return result(True, False, False, "invalid_artifact", "scope_expansion")
        if "binding_units" in vector and requested["quantity"] < accepted["quantity"]:
            return result(True, False, False, "invalid_artifact", "scope_contraction")

    commitment = artifact["commitment"]
    if commitment["type"] == "accepted_revalidate" and not state["revalidation_passes"]:
        return result(True, True, False, "recognized_rejected", "business_revalidation_failed")
    if commitment["type"] == "business_firm":
        allowed = set(commitment["invalidation_conditions"])
        active = set(state["active_invalidation_conditions"])
        if allowed.intersection(active):
            return result(True, True, False, "recognized_rejected", "firm_commitment_invalidated")
        # Ordinary state drift is deliberately ignored for a firm commitment.
        return result(True, True, True, "bound", "bound")
    if commitment["type"] == "proposed":
        return result(True, False, False, "invalid_artifact", "not_accepted")
    if "binding_units" in vector:
        return evaluate_binding_units(vector)
    return result(True, True, True, "bound", "bound")


def score_model(vector, model, capabilities):
    statuses = [capabilities[model][name] for name in vector["model_requirements"][model]["requires"]]
    return max(statuses, key=lambda status: VERDICT_RANK[status])


class TestVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_json(SCHEMA_PATH)
        cls.vectors = load_vectors()
        cls.capabilities = load_json(CAPABILITIES_PATH)
        cls.validator = Draft7Validator(cls.schema, format_checker=FormatChecker())

    def test_all_vectors_validate_against_harness_schema(self):
        for vector in self.vectors:
            with self.subTest(vector=vector["id"]):
                errors = sorted(self.validator.iter_errors(vector), key=lambda error: list(error.path))
                self.assertEqual([], errors, "\n".join(error.message for error in errors))

    def test_expected_results_follow_candidate_invariants(self):
        for vector in self.vectors:
            with self.subTest(vector=vector["id"]):
                self.assertEqual(vector["expected"], evaluate(vector))

    def test_post_bind_results_follow_declared_lifecycle_semantics(self):
        for vector in self.vectors:
            if "post_bind" in vector:
                with self.subTest(vector=vector["id"]):
                    self.assertEqual(vector["post_bind"]["expected"], evaluate_post_bind(vector))

    def test_model_matrix_is_computed_from_declared_capabilities(self):
        for vector in self.vectors:
            for model in MODELS:
                with self.subTest(vector=vector["id"], model=model):
                    expected = vector["model_requirements"][model]["expected_verdict"]
                    self.assertEqual(expected, score_model(vector, model, self.capabilities))

    def test_vector_set_and_model_coverage_are_complete(self):
        self.assertEqual([f"V{number}" for number in range(1, 12)], [vector["id"] for vector in self.vectors])
        for vector in self.vectors:
            self.assertEqual(set(MODELS), set(vector["model_requirements"]))

    def test_timelines_are_ordered_and_do_not_cross_artifact_identity(self):
        for vector in self.vectors:
            with self.subTest(vector=vector["id"]):
                times = [instant(event["at"]) for event in vector["timeline"]]
                self.assertEqual(times, sorted(times))
                self.assertEqual(vector["term_artifact"]["id"], vector["binding_request"]["artifact_id"])

    def test_v1_through_v7_are_byte_for_byte_unchanged(self):
        for path in VECTOR_DIR.glob("v[1-7]-*.json"):
            vector_id = load_json(path)["id"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(LEGACY_VECTOR_SHA256[vector_id], digest)
        self.assertEqual(set(LEGACY_VECTOR_SHA256), {f"V{number}" for number in range(1, 8)})

    def test_accepted_does_not_always_mean_executable(self):
        vector = next(item for item in self.vectors if item["id"] == "V6")
        self.assertEqual("accepted", vector["term_artifact"]["acceptance"]["state"])
        self.assertTrue(vector["expected"]["artifact_valid"])
        self.assertFalse(vector["expected"]["bindable"])
        self.assertEqual("recognized_rejected", vector["expected"]["outcome"])

    def test_business_revalidation_is_not_always_permitted(self):
        vector = next(item for item in self.vectors if item["id"] == "V7")
        self.assertEqual("business_firm", vector["term_artifact"]["commitment"]["type"])
        self.assertFalse(vector["business_state"]["revalidation_passes"])
        self.assertTrue(vector["expected"]["bindable"])

    def test_bound_does_not_mean_executed(self):
        vector = next(item for item in self.vectors if item["id"] == "V8")
        self.assertEqual("bound", vector["expected"]["outcome"])
        self.assertFalse(vector["post_bind"]["expected"]["executed"])
        self.assertEqual("post_bind_invalidated", vector["post_bind"]["expected"]["status"])

    def test_conditional_release_preserves_terms_without_repricing(self):
        vector = next(item for item in self.vectors if item["id"] == "V9")
        self.assertEqual("conditional_release", vector["post_bind"]["governing_semantics"]["mode"])
        self.assertEqual("release_condition_failed", vector["post_bind"]["expected"]["status"])
        self.assertTrue(vector["post_bind"]["expected"]["terms_preserved"])
        self.assertFalse(vector["post_bind"]["expected"]["executed"])

    def test_conditional_release_reports_pending_before_failure(self):
        vector = copy.deepcopy(next(item for item in self.vectors if item["id"] == "V9"))
        vector["post_bind"]["execution_attempt"]["release_condition_met"] = None
        pending = evaluate_post_bind(vector)
        self.assertEqual("release_pending", pending["status"])
        self.assertFalse(pending["executed"])
        self.assertTrue(pending["terms_preserved"])

    def test_dual_clocks_are_explicit_and_need_not_share_a_deadline(self):
        v8 = next(item for item in self.vectors if item["id"] == "V8")
        v9 = next(item for item in self.vectors if item["id"] == "V9")
        self.assertNotEqual(v8["term_artifact"]["expires_at"], v8["post_bind"]["transaction"]["valid_until"])
        self.assertNotEqual(v8["term_artifact"]["expires_at"], v8["post_bind"]["governing_semantics"]["post_bind_valid_until"])
        self.assertGreater(instant(v9["post_bind"]["execution_attempt"]["at"]), instant(v9["term_artifact"]["expires_at"]))
        self.assertEqual("conditional_release", v9["post_bind"]["governing_semantics"]["mode"])

    def test_partial_success_is_explicit_and_does_not_drop_scope(self):
        vector = next(item for item in self.vectors if item["id"] == "V10")
        evaluated = evaluate(vector)
        self.assertEqual("partially_bound", evaluated["outcome"])
        self.assertEqual(38, evaluated["effective_bound_line_count"])
        self.assertEqual(2, evaluated["failed_line_count"])
        self.assertEqual(4, len(evaluated["unit_results"]))

    def test_atomic_group_cannot_be_silently_split(self):
        vector = next(item for item in self.vectors if item["id"] == "V11")
        unit = evaluate(vector)["unit_results"][0]
        self.assertEqual("binding_unit_rejected", unit["result"])
        self.assertEqual([], unit["effective_bound_line_ids"])
        self.assertEqual(4, vector["expected"]["failed_line_count"])

    def test_idempotent_unit_retry_does_not_duplicate_success(self):
        vector = next(item for item in self.vectors if item["id"] == "V10")
        replay = evaluate(vector)["unit_results"][0]
        self.assertEqual("idempotent_replay", replay["result"])
        self.assertEqual(10, len(replay["effective_bound_line_ids"]))
        self.assertEqual([], replay["newly_bound_line_ids"])

    def test_retry_cannot_turn_prior_failure_into_success_without_transition(self):
        vector = copy.deepcopy(next(item for item in self.vectors if item["id"] == "V10"))
        failed = vector["binding_units"][3]
        failed["unavailable_line_ids"] = []
        result_for_retry = evaluate(vector)["unit_results"][3]
        self.assertEqual("binding_unit_rejected", result_for_retry["result"])
        self.assertEqual("line_unavailable", result_for_retry["reason"])

    def test_retry_cannot_silently_move_lines_between_groups(self):
        vector = copy.deepcopy(next(item for item in self.vectors if item["id"] == "V10"))
        replay = vector["binding_units"][0]
        replay["prior_binding"]["line_ids"] = replay["prior_binding"]["line_ids"][:-1]
        result_for_retry = evaluate(vector)["unit_results"][0]
        self.assertEqual("binding_unit_rejected", result_for_retry["result"])
        self.assertEqual("idempotency_conflict", result_for_retry["reason"])

    def test_scope_expansion_and_contraction_are_distinct(self):
        expansion = next(item for item in self.vectors if item["id"] == "V4")
        self.assertEqual("scope_expansion", evaluate(expansion)["reason"])
        partial = copy.deepcopy(next(item for item in self.vectors if item["id"] == "V10"))
        partial["binding_units"] = partial["binding_units"][:-1]
        self.assertEqual("scope_contraction", evaluate(partial)["reason"])

    def test_new_lifecycle_does_not_weaken_legacy_firm_commitment(self):
        firm = next(item for item in self.vectors if item["id"] == "V7")
        self.assertEqual({"recognized": True, "artifact_valid": True, "bindable": True, "outcome": "bound", "reason": "bound"}, evaluate(firm))

    def test_stale_expired_scope_and_business_rejection_remain_distinct(self):
        reasons = {vector["id"]: vector["expected"]["reason"] for vector in self.vectors}
        self.assertEqual("stale_revision", reasons["V2"])
        self.assertEqual("scope_expansion", reasons["V4"])
        self.assertEqual("expired", reasons["V5"])
        self.assertEqual("business_revalidation_failed", reasons["V6"])
        self.assertEqual(4, len({reasons[key] for key in ("V2", "V4", "V5", "V6")}))

    def test_result_taxonomy_can_distinguish_invalidity_classes(self):
        reason_values = set(self.schema["definitions"]["expected"]["properties"]["reason"]["enum"])
        required = {
            "malformed_artifact", "unknown_artifact", "forged_artifact", "expired",
            "stale_revision", "scope_expansion", "scope_contraction",
            "business_revalidation_failed", "partial_binding", "binding_unit_rejected",
        }
        self.assertTrue(required.issubset(reason_values))

    def test_post_bind_and_binding_unit_taxonomies_are_explicit(self):
        lifecycle = set(self.schema["definitions"]["postBind"]["properties"]["expected"]["properties"]["status"]["enum"])
        units = set(self.schema["definitions"]["unitResult"]["properties"]["result"]["enum"])
        self.assertTrue({"bound_not_executable", "release_pending", "release_condition_failed", "post_bind_invalidated", "executed"}.issubset(lifecycle))
        self.assertTrue({"bound", "binding_unit_rejected", "idempotent_replay"}.issubset(units))

    def test_binding_unit_expectations_match_actual_unit_results(self):
        for vector in self.vectors:
            if "binding_units" in vector:
                with self.subTest(vector=vector["id"]):
                    actual = evaluate(vector)["unit_results"]
                    declared = [unit["expected"] for unit in vector["binding_units"]]
                    self.assertEqual(declared, actual)

    def test_documented_matrix_matches_actual_model_scorer(self):
        rows = {}
        for line in (ROOT / "analysis.md").read_text(encoding="utf-8").splitlines():
            if line.startswith("| V") and not line.startswith("| Vector"):
                columns = [column.strip() for column in line.strip("|").split("|")]
                vector_id = columns[0].split()[0]
                rows[vector_id] = (columns[1], columns[2])
        self.assertEqual({vector["id"] for vector in self.vectors}, set(rows))
        for vector in self.vectors:
            actual = tuple(score_model(vector, model, self.capabilities) for model in MODELS)
            self.assertEqual(actual, rows[vector["id"]])


def print_matrix():
    vectors = load_vectors()
    capabilities = load_json(CAPABILITIES_PATH)
    print("| Vector | Opaque reference | Portable artifact | Semantic outcome |")
    print("|---|---|---|---|")
    for vector in vectors:
        opaque = score_model(vector, "opaque_reference", capabilities)
        portable = score_model(vector, "portable_artifact", capabilities)
        expected = vector["expected"]
        semantic_outcome = f"{expected['outcome']} / {expected['reason']}"
        if "post_bind" in vector:
            post = vector["post_bind"]["expected"]
            semantic_outcome += f" -> {post['status']} / {post['reason']}"
        elif "binding_units" in vector:
            semantic_outcome += (
                f" ({expected['effective_bound_line_count']} effective, "
                f"{expected['failed_line_count']} failed)"
            )
        print(f"| {vector['id']} | {opaque} | {portable} | {semantic_outcome} |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", action="store_true")
    args, remaining = parser.parse_known_args()
    if args.matrix:
        print_matrix()
    else:
        unittest.main(argv=[__file__, *remaining])
