"""Adversarial coverage for deadline, commercial authorization, and retry boundaries."""
import copy
import unittest
from jsonschema import Draft7Validator, FormatChecker
from test_vectors import load_vectors, evaluate, evaluate_post_bind, load_json, SCHEMA_PATH


class ReviewTests(unittest.TestCase):
    def fixture(self, number):
        return copy.deepcopy(next(v for v in load_vectors() if v['id'] == 'V' + str(number)))

    def pending(self):
        v = self.fixture(9)
        v['post_bind']['execution_attempt'].update(release_condition_met=None, release_resolved_at=None)
        return v

    def test_release_success_before_deadline(self):
        v = self.fixture(9)
        v['post_bind']['execution_attempt']['release_condition_met'] = True
        self.assertTrue(evaluate_post_bind(v)['executed'])

    def test_success_observed_late_uses_verified_event_time(self):
        v = self.fixture(9)
        v['post_bind']['execution_attempt'].update(release_condition_met=True, at='2026-09-21T00:00:00Z')
        self.assertTrue(evaluate_post_bind(v)['executed'])

    def test_release_exactly_at_deadline_is_too_late(self):
        v = self.fixture(13)
        a = v['post_bind']['execution_attempt']
        a.update(release_condition_met=True, release_resolved_at=a['at'])
        self.assertEqual('return_to_buyer', evaluate_post_bind(v)['reason'])

    def test_pending_after_deadline_cannot_remain_pending(self):
        v = self.fixture(13)
        v['post_bind']['execution_attempt']['at'] = '2026-10-01T00:00:00Z'
        self.assertEqual('deadline_non_execution', evaluate_post_bind(v)['status'])

    def test_explicit_deemed_acceptance_allocates_to_business(self):
        v = self.fixture(13)
        v['post_bind']['governing_semantics']['pending_at_deadline'] = 'deemed_acceptance_to_business'
        self.assertEqual('deemed_acceptance_to_business', evaluate_post_bind(v)['reason'])
        self.assertTrue(evaluate_post_bind(v)['executed'])

    def test_transaction_clock_shorter_than_term_expiry(self):
        v = self.pending()
        v['post_bind']['transaction']['valid_until'] = '2026-09-12T11:00:00Z'
        self.assertEqual('return_to_buyer', evaluate_post_bind(v)['reason'])

    def test_explicit_deadline_shorter_than_other_clocks(self):
        v = self.pending()
        v['post_bind']['governing_semantics'].update(deadline_source='explicit_post_bind_deadline', post_bind_valid_until='2026-09-12T11:00:00Z')
        self.assertEqual('return_to_buyer', evaluate_post_bind(v)['reason'])

    def test_term_expiry_source_with_release(self):
        v = self.pending()
        v['post_bind']['governing_semantics']['deadline_source'] = 'term_expiry'
        self.assertEqual('return_to_buyer', evaluate_post_bind(v)['reason'])

    def test_no_release_still_obeys_deadline(self):
        v = self.fixture(8)
        v['post_bind']['execution_attempt'].update(at='2026-09-14T00:00:00Z', active_invalidation_conditions=[])
        self.assertEqual('execution_deadline_elapsed', evaluate_post_bind(v)['reason'])

    def test_ordinary_drift_does_not_weaken_firm_post_bind_terms(self):
        v = self.fixture(9)
        v['post_bind']['execution_attempt'].update(release_condition_met=True, active_invalidation_conditions=['contract_tier_changed'])
        self.assertTrue(evaluate_post_bind(v)['executed'])

    def test_release_cannot_silently_reprice(self):
        v = self.fixture(9)
        v['post_bind']['execution_attempt'].update(release_condition_met=True, terms_unchanged=False)
        self.assertEqual('commercial_terms_reinterpreted', evaluate_post_bind(v)['reason'])

    def test_execution_requires_actual_binding_not_expected_label(self):
        v = self.fixture(9)
        v['business_state']['artifact_authentic'] = False
        self.assertFalse(evaluate_post_bind(v)['executed'])

    def test_future_release_evidence_rejected(self):
        v = self.fixture(9)
        v['post_bind']['execution_attempt']['release_resolved_at'] = '2026-10-01T00:00:00Z'
        self.assertEqual('invalid_release_evidence', evaluate_post_bind(v)['reason'])

    def test_bound_target_must_match_execution_target(self):
        v = self.fixture(9)
        v['post_bind']['transaction']['id'] = 'unrelated-transaction'
        self.assertEqual('transaction_mismatch', evaluate_post_bind(v)['reason'])

    def test_ambiguous_tier_thresholds_rejected(self):
        v = self.fixture(12)
        rule = v['term_artifact']['binding_authorization']['contraction_rule']
        rule['tiers'].append({'minimum_units':1, 'unit_price':9999})
        self.assertEqual('invalid_artifact_semantics', evaluate(v)['reason'])

    def test_schema_requires_deadline_and_disposition(self):
        validator = Draft7Validator(load_json(SCHEMA_PATH), format_checker=FormatChecker())
        for field in ('deadline_source', 'pending_at_deadline'):
            v = self.fixture(9)
            del v['post_bind']['governing_semantics'][field]
            self.assertFalse(validator.is_valid(v))
        v = self.fixture(9)
        v['post_bind']['governing_semantics']['pending_at_deadline'] = None
        self.assertFalse(validator.is_valid(v))

    def test_authorized_tier_is_deterministic_and_changes_surviving_prices(self):
        v = self.fixture(12)
        self.assertEqual({'L01':1200, 'L02':1200, 'L03':1200}, evaluate(v)['effective_unit_prices'])
        self.assertEqual(evaluate(v), evaluate(copy.deepcopy(v)))
        v['term_artifact']['binding_authorization']['contraction_rule']['tiers'][0]['unit_price'] = 1300
        self.assertEqual(1300, evaluate(v)['effective_unit_prices']['L01'])

    def test_missing_adjustment_rule_fails_closed(self):
        v = self.fixture(12)
        v['term_artifact']['binding_authorization']['contraction_rule'] = None
        self.assertEqual('unauthorized_adjustment', evaluate(v)['reason'])

    def test_unverified_adjustment_fails_closed(self):
        v = self.fixture(12)
        v['business_state']['adjustment_authorization_verified'] = False
        self.assertEqual('unauthorized_adjustment', evaluate(v)['reason'])

    def test_ad_hoc_request_price_fails(self):
        v = self.fixture(12)
        v['binding_request']['lines'][0]['unit_price'] = 777
        self.assertEqual('scope_expansion', evaluate(v)['reason'])

    def test_minimum_commercial_basis_rejects_survivors(self):
        v = self.fixture(12)
        v['term_artifact']['binding_authorization']['contraction_rule']['tiers'] = [{'minimum_units':4,'unit_price':1000}]
        self.assertEqual('commercial_basis_unsatisfied', evaluate(v)['reason'])

    def test_restock_same_attempt_remains_failed(self):
        v = self.fixture(10)
        v['binding_units'][3]['unavailable_line_ids'] = []
        self.assertEqual('line_unavailable', evaluate(v)['unit_results'][3]['reason'])

    def test_restock_new_attempt_same_revision_succeeds(self):
        v = self.fixture(14)
        self.assertEqual(4, v['term_artifact']['revision'])
        self.assertEqual('bound', evaluate(v)['unit_results'][3]['reason'])

    def test_fresh_attempt_does_not_repair_structural_history(self):
        for reason in ('stale_revision','atomicity_violation','unauthorized_grouping','unauthorized_scope','invalid_artifact_semantics'):
            v = self.fixture(14)
            v['business_state']['attempt_history'][1]['reason'] = reason
            self.assertEqual(reason, evaluate(v)['unit_results'][3]['reason'])
            self.assertEqual('new_authorized_transition', evaluate(v)['unit_results'][3]['retry_class'])

    def test_current_stale_revision_blocks_new_attempt(self):
        v = self.fixture(14)
        v['business_state']['current_revision'] = 5
        self.assertEqual('stale_revision', evaluate(v)['reason'])

    def test_expired_authorization_blocks_new_attempt(self):
        v = self.fixture(14)
        v['binding_request']['at'] = '2026-10-01T00:00:00Z'
        self.assertEqual('expired', evaluate(v)['reason'])

    def test_fresh_key_cannot_change_group_membership(self):
        v = self.fixture(14)
        a,b = v['binding_units'][:2]
        a['line_ids'][0],b['line_ids'][0] = b['line_ids'][0],a['line_ids'][0]
        a['attempt_id'] = 'new-key'
        self.assertEqual('unauthorized_grouping', evaluate(v)['reason'])

    def test_single_line_binding_unit_is_supported(self):
        v = self.fixture(12)
        self.assertTrue(all(len(g['line_ids']) == 1 for g in v['binding_units']))
        self.assertEqual('partially_bound', evaluate(v)['outcome'])

    def test_prior_success_does_not_duplicate_on_new_attempt(self):
        v = self.fixture(14)
        v['binding_units'][0]['attempt_id'] = 'fresh-success-key'
        out = evaluate(v)
        self.assertEqual([], out['unit_results'][0]['newly_bound_line_ids'])
        self.assertEqual(30, out['newly_bound_line_count'])

    def test_missing_history_fails_closed(self):
        v = self.fixture(14)
        v['business_state']['attempt_history_available'] = False
        self.assertEqual('attempt_history_unavailable', evaluate(v)['reason'])

    def test_unverified_group_authorization_rejected(self):
        v = self.fixture(11)
        v['business_state']['binding_authorization_verified'] = False
        self.assertEqual('unauthorized_grouping', evaluate(v)['reason'])

    def test_duplicate_attempt_id_conflicts(self):
        v = self.fixture(14)
        v['binding_units'][1]['attempt_id'] = v['binding_units'][0]['attempt_id']
        self.assertEqual('idempotency_conflict', evaluate(v)['reason'])

    def test_group_target_cannot_change(self):
        v = self.fixture(14)
        v['binding_units'][0]['target_transaction'] = 'another-checkout'
        self.assertEqual('idempotency_conflict', evaluate(v)['reason'])

    def test_prior_bound_units_cannot_be_repriced_by_later_contraction(self):
        v = self.fixture(12)
        g = v['binding_units'][0]
        v['business_state']['attempt_history'] = [dict(attempt_id=g['attempt_id'], artifact_id=v['term_artifact']['id'], revision=4, binding_unit_id=g['id'], line_ids=g['line_ids'], target_transaction=g['target_transaction'], reason='bound')]
        self.assertEqual('prior_bound_adjustment_requires_transition', evaluate(v)['reason'])
