#!/usr/bin/env python3
"""Executable semantic tests for accepted-term handoff review vectors."""

from __future__ import annotations

import argparse
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


def load_json(path: Path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def load_vectors():
    return [load_json(path) for path in sorted(VECTOR_DIR.glob("*.json"))]


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

    def test_model_matrix_is_computed_from_declared_capabilities(self):
        for vector in self.vectors:
            for model in MODELS:
                with self.subTest(vector=vector["id"], model=model):
                    expected = vector["model_requirements"][model]["expected_verdict"]
                    self.assertEqual(expected, score_model(vector, model, self.capabilities))

    def test_vector_set_and_model_coverage_are_complete(self):
        self.assertEqual([f"V{number}" for number in range(1, 8)], [vector["id"] for vector in self.vectors])
        for vector in self.vectors:
            self.assertEqual(set(MODELS), set(vector["model_requirements"]))

    def test_timelines_are_ordered_and_do_not_cross_artifact_identity(self):
        for vector in self.vectors:
            with self.subTest(vector=vector["id"]):
                times = [instant(event["at"]) for event in vector["timeline"]]
                self.assertEqual(times, sorted(times))
                self.assertEqual(vector["term_artifact"]["id"], vector["binding_request"]["artifact_id"])

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
            "stale_revision", "scope_expansion", "business_revalidation_failed",
        }
        self.assertTrue(required.issubset(reason_values))


def print_matrix():
    vectors = load_vectors()
    capabilities = load_json(CAPABILITIES_PATH)
    print("| Vector | Opaque reference | Portable artifact | Semantic outcome |")
    print("|---|---|---|---|")
    for vector in vectors:
        opaque = score_model(vector, "opaque_reference", capabilities)
        portable = score_model(vector, "portable_artifact", capabilities)
        expected = vector["expected"]
        print(f"| {vector['id']} | {opaque} | {portable} | {expected['outcome']} / {expected['reason']} |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", action="store_true")
    args, remaining = parser.parse_known_args()
    if args.matrix:
        print_matrix()
    else:
        unittest.main(argv=[__file__, *remaining])
