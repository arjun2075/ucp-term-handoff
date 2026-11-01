"""Decision-oriented negative tests for UCP #845 (analysis harness, not UCP conformance).

The two cases intentionally reuse the frozen PR #1 vector corpus instead of
inventing a quote-extension wire contract. A successful harness assertion is
not proof of a current UCP requirement or an independent implementation.
"""

from __future__ import annotations

import copy
import unittest

from test_vectors import evaluate, evaluate_post_bind, instant, load_vectors


class TestArchitectureDecision845(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectors = {v["id"]: v for v in load_vectors()}

    def test_a_recognized_nonbinding_quote_fails_revalidation_without_repricing(self):
        """A recognized quote must not masquerade as bound or silently change terms."""
        proposed = copy.deepcopy(self.vectors["V6"])
        self.assertEqual(
            "accepted_revalidate", proposed["term_artifact"]["commitment"]["type"]
        )
        self.assertEqual("accepted", proposed["term_artifact"]["acceptance"]["state"])
        self.assertFalse(proposed["business_state"]["revalidation_passes"])
        rejected = evaluate(proposed)

        self.assertTrue(rejected["recognized"])
        self.assertTrue(rejected["artifact_valid"])
        self.assertFalse(rejected["bindable"])
        self.assertEqual("recognized_rejected", rejected["outcome"])
        self.assertEqual("business_revalidation_failed", rejected["reason"])

        # A wrong commercial basis is different from a Business refusing to
        # honor an otherwise recognized, unchanged artifact.
        changed = copy.deepcopy(proposed)
        changed["binding_request"]["commercial_terms"] = [
            "substituted price or cancellation conditions"
        ]
        changed_result = evaluate(changed)
        self.assertFalse(changed_result["bindable"])
        self.assertEqual("invalid_artifact", changed_result["outcome"])
        self.assertEqual("commercial_terms_mismatch", changed_result["reason"])

        forged = copy.deepcopy(proposed)
        forged["business_state"]["artifact_authentic"] = False
        forged_result = evaluate(forged)
        self.assertEqual("invalid_artifact", forged_result["outcome"])
        self.assertEqual("forged_artifact", forged_result["reason"])

        # The negative result is commitment-dependent; failing revalidation
        # alone must not erase an otherwise firm authorized commitment.
        firm = self.vectors["V7"]
        self.assertEqual("business_firm", firm["term_artifact"]["commitment"]["type"])
        self.assertFalse(firm["business_state"]["revalidation_passes"])
        self.assertEqual("bound", evaluate(firm)["outcome"])

    def test_b_acceptance_and_binding_use_distinct_expiry_boundaries(self):
        """Acceptance before expiry is not itself an enduring binding result."""
        accepted_only = self.vectors["V5"]
        self.assertLess(
            instant(accepted_only["term_artifact"]["acceptance"]["accepted_at"]),
            instant(accepted_only["term_artifact"]["expires_at"]),
        )
        self.assertGreaterEqual(
            instant(accepted_only["binding_request"]["at"]),
            instant(accepted_only["term_artifact"]["expires_at"]),
        )
        refused = evaluate(accepted_only)
        self.assertFalse(refused["bindable"])
        self.assertEqual(("invalid_artifact", "expired"),
                         (refused["outcome"], refused["reason"]))

        # In a separately declared transaction-lifetime policy, the artifact
        # was already bound before issuance expiry. Later release evaluation
        # does not re-run the pre-bind validity gate or silently reprice.
        bound_first = self.vectors["V9"]
        expiry = instant(bound_first["term_artifact"]["expires_at"])
        self.assertLess(
            instant(bound_first["term_artifact"]["acceptance"]["accepted_at"]),
            instant(bound_first["post_bind"]["bound_at"]),
        )
        self.assertLess(instant(bound_first["post_bind"]["bound_at"]), expiry)
        self.assertLess(expiry, instant(bound_first["post_bind"]["execution_attempt"]["at"]))
        self.assertLess(
            instant(bound_first["post_bind"]["execution_attempt"]["at"]),
            instant(bound_first["post_bind"]["transaction"]["valid_until"]),
        )
        self.assertEqual(
            "transaction_lifetime",
            bound_first["post_bind"]["governing_semantics"]["deadline_source"],
        )
        self.assertEqual("bound", evaluate(bound_first)["outcome"])
        downstream = evaluate_post_bind(bound_first)
        self.assertEqual("release_condition_failed", downstream["status"])
        self.assertFalse(downstream["executed"])
        self.assertTrue(downstream["terms_preserved"])

        # Guard against a false generalization: merely moving the *binding*
        # itself beyond issuance expiry does not create a bound transaction.
        late_binding = copy.deepcopy(bound_first)
        late_binding["binding_request"]["at"] = "2026-09-13T01:00:00Z"
        late_binding["post_bind"]["bound_at"] = "2026-09-13T01:00:00Z"
        self.assertEqual("expired", evaluate(late_binding)["reason"])
        self.assertEqual(
            "bound_not_executable", evaluate_post_bind(late_binding)["status"]
        )


if __name__ == "__main__":
    unittest.main()
