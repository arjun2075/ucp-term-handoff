"""Adversarial coverage for deadline, commercial authorization, and retry boundaries."""
import copy
import itertools
import unittest
from jsonschema import Draft7Validator, FormatChecker
from semantics import (InconsistentAdjustmentHistory, adjustment_chain,
                       adjustment_identity,
                       current_commercial_basis, instant,
                       persistable_terminal_outcome, replayable_terminal_outcome,
                       RESERVED_LIFECYCLE_REASONS, TRANSIENT_LIFECYCLE_FAILURES)
from test_vectors import load_vectors, evaluate, evaluate_post_bind, load_json, SCHEMA_PATH


class ReviewTests(unittest.TestCase):
    def fixture(self, number):
        return copy.deepcopy(next(v for v in load_vectors() if v['id'] == 'V' + str(number)))

    def pending(self):
        v = self.fixture(9)
        v['post_bind']['execution_attempt'].update(release_condition_met=None, release_resolved_at=None)
        return v

    def v12_history(self):
        v = self.fixture(12)
        evaluated = evaluate(v)
        prices = evaluated['effective_unit_prices']
        history = []
        for group, result in zip(v['binding_units'], evaluated['unit_results']):
            record = dict(attempt_id=group['attempt_id'], artifact_id=v['term_artifact']['id'],
                          revision=group['accepted_revision'], binding_unit_id=group['id'],
                          line_ids=group['line_ids'], target_transaction=group['target_transaction'],
                          reason=result['reason'])
            if result['reason'] == 'bound':
                record['effective_unit_prices'] = {
                    line: prices[line] for line in result['effective_bound_line_ids']
                }
            history.append(record)
        v['business_state']['attempt_history'] = history
        return v

    def persist(self, vector, result):
        """Append-only persistence of an applied result: history plus adjustments."""
        artifact = vector['term_artifact']
        prices = result.get('effective_unit_prices', {})
        history = vector['business_state']['attempt_history']
        known = {record['attempt_id'] for record in history}
        for group, unit in zip(vector['binding_units'], result['unit_results']):
            if unit['reason'] != 'bound' or group['attempt_id'] in known:
                continue
            history.append(dict(
                attempt_id=group['attempt_id'], artifact_id=artifact['id'],
                revision=group['accepted_revision'], binding_unit_id=group['id'],
                line_ids=group['line_ids'], target_transaction=group['target_transaction'],
                reason='bound',
                effective_unit_prices={line: prices[line]
                                       for line in unit['effective_bound_line_ids']}))
        applied = vector['business_state'].setdefault('commercial_basis_adjustments', [])
        for adjustment in result.get('adjustments', []):
            applied.append(dict(artifact_id=artifact['id'], **adjustment))
        return vector

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
        v['post_bind']['terminal_outcome'] = None
        a = v['post_bind']['execution_attempt']
        a.update(release_condition_met=True, release_resolved_at=a['at'])
        self.assertEqual('return_to_buyer', evaluate_post_bind(v)['reason'])

    def test_pending_after_deadline_cannot_remain_pending(self):
        v = self.fixture(13)
        v['post_bind']['terminal_outcome'] = None
        v['post_bind']['execution_attempt']['at'] = '2026-10-01T00:00:00Z'
        self.assertEqual('deadline_non_execution', evaluate_post_bind(v)['status'])

    def test_persisted_deadline_disposition_cannot_predate_deadline(self):
        v = self.fixture(13)
        v['post_bind']['terminal_outcome']['applied_at'] = '2026-09-19T00:00:00Z'
        self.assertEqual('invalid_lifecycle_timing', evaluate_post_bind(v)['reason'])

    def test_explicit_deemed_acceptance_allocates_to_business(self):
        v = self.fixture(13)
        v['post_bind']['terminal_outcome'] = None
        v['post_bind']['governing_semantics']['pending_at_deadline'] = 'deemed_acceptance_to_business'
        self.assertEqual('deemed_acceptance_to_business', evaluate_post_bind(v)['reason'])
        self.assertTrue(evaluate_post_bind(v)['executed'])

    def test_deemed_acceptance_is_final_despite_late_failed_evidence(self):
        v = self.fixture(13)
        v['post_bind']['governing_semantics']['pending_at_deadline'] = 'deemed_acceptance_to_business'
        v['post_bind']['terminal_outcome'].update(
            status='executed', reason='deemed_acceptance_to_business', executed=True)
        v['post_bind']['execution_attempt'].update(
            at='2026-09-21T00:00:00Z', release_condition_met=False,
            release_resolved_at='2026-09-19T00:00:00Z')
        result = evaluate_post_bind(v)
        self.assertEqual('deemed_acceptance_to_business', result['reason'])
        self.assertTrue(result['executed'])

    def test_return_to_buyer_is_final_despite_late_success_evidence(self):
        v = self.fixture(13)
        v['post_bind']['execution_attempt'].update(
            at='2026-09-21T00:00:00Z', release_condition_met=True,
            release_resolved_at='2026-09-19T00:00:00Z')
        self.assertEqual('return_to_buyer', evaluate_post_bind(v)['reason'])

    def test_available_pre_deadline_evidence_governs_before_terminal_disposition(self):
        v = self.fixture(13)
        v['post_bind']['terminal_outcome'] = None
        v['post_bind']['execution_attempt'].update(
            release_condition_met=True, release_resolved_at='2026-09-19T00:00:00Z')
        self.assertEqual('release_condition_satisfied', evaluate_post_bind(v)['reason'])

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
        result = evaluate(v)['unit_results'][3]
        self.assertEqual('line_unavailable', result['reason'])
        self.assertEqual('new_attempt_same_revision', result['retry_class'])

    def test_restock_new_attempt_same_revision_succeeds(self):
        v = self.fixture(14)
        self.assertEqual(4, v['term_artifact']['revision'])
        self.assertEqual('bound', evaluate(v)['unit_results'][3]['reason'])

    def test_idempotency_conflict_requires_new_attempt_id_not_new_revision(self):
        v = self.fixture(14)
        v['binding_units'][0]['attempt_id'] = 'fresh-U1'
        v['binding_units'][1]['attempt_id'] = v['business_state']['attempt_history'][0]['attempt_id']
        conflicted = evaluate(v)
        self.assertEqual('idempotency_conflict', conflicted['unit_results'][1]['reason'])
        self.assertEqual('new_attempt_id_same_revision', conflicted['unit_results'][1]['retry_class'])
        self.assertEqual(conflicted, evaluate(copy.deepcopy(v)))
        v['binding_units'][1]['attempt_id'] = 'genuinely-fresh-U2'
        recovered = evaluate(v)
        self.assertEqual(4, v['binding_units'][1]['accepted_revision'])
        self.assertEqual('bound', recovered['unit_results'][1]['reason'])

    def test_fresh_attempt_does_not_repair_structural_history(self):
        for reason in ('stale_revision','atomicity_violation','unauthorized_grouping','unauthorized_scope','invalid_artifact_semantics'):
            v = self.fixture(14)
            v['business_state']['attempt_history'][1]['reason'] = reason
            self.assertEqual(reason, evaluate(v)['unit_results'][3]['reason'])
            self.assertEqual('new_authorized_transition', evaluate(v)['unit_results'][3]['retry_class'])

    def test_current_stale_revision_blocks_new_attempt(self):
        v = self.fixture(14)
        v['business_state']['current_revision'] = 5
        result = evaluate(v)
        self.assertEqual('stale_revision', result['reason'])
        self.assertEqual('new_authorized_transition', result['recovery_action'])

    def test_expired_authorization_blocks_new_attempt(self):
        v = self.fixture(14)
        v['binding_request']['at'] = '2026-10-01T00:00:00Z'
        self.assertEqual('expired', evaluate(v)['reason'])

    def test_fresh_key_cannot_change_group_membership(self):
        v = self.fixture(14)
        a,b = v['binding_units'][:2]
        a['line_ids'][0],b['line_ids'][0] = b['line_ids'][0],a['line_ids'][0]
        a['attempt_id'] = 'new-key'
        result = evaluate(v)
        self.assertEqual('unauthorized_grouping', result['reason'])
        self.assertEqual('new_authorized_transition', result['recovery_action'])

    def test_atomicity_and_unauthorized_scope_require_authorized_transition(self):
        atomicity = self.fixture(14)
        atomicity['binding_units'][1]['line_ids'].append(atomicity['binding_units'][0]['line_ids'][0])
        self.assertEqual('new_authorized_transition', evaluate(atomicity)['recovery_action'])
        scope = self.fixture(14)
        scope['binding_units'][0]['line_ids'][0] = 'outside-accepted-scope'
        self.assertEqual('new_authorized_transition', evaluate(scope)['recovery_action'])

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
        unavailable = evaluate(v)
        self.assertEqual('attempt_history_unavailable', unavailable['reason'])
        self.assertTrue(unavailable['artifact_valid'])
        self.assertEqual('recognized_rejected', unavailable['outcome'])
        self.assertEqual('same_attempt_later', unavailable['recovery_action'])
        v['business_state']['attempt_history_available'] = True
        self.assertEqual('bound', evaluate(v)['outcome'])

    def test_unverified_group_authorization_rejected(self):
        v = self.fixture(11)
        v['business_state']['binding_authorization_verified'] = False
        self.assertEqual('unauthorized_grouping', evaluate(v)['reason'])

    def test_duplicate_attempt_id_conflicts(self):
        v = self.fixture(14)
        v['binding_units'][1]['attempt_id'] = v['binding_units'][0]['attempt_id']
        result = evaluate(v)
        self.assertEqual('idempotency_conflict', result['reason'])
        self.assertEqual('new_attempt_id_same_revision', result['recovery_action'])

    def test_group_target_cannot_change(self):
        v = self.fixture(14)
        v['binding_units'][0]['target_transaction'] = 'another-checkout'
        self.assertEqual('idempotency_conflict', evaluate(v)['reason'])

    def test_v12_replay_uses_historical_bound_basis(self):
        v = self.v12_history()
        result = evaluate(v)
        self.assertEqual('partially_bound', result['outcome'])
        self.assertEqual({'L01':1200, 'L02':1200, 'L03':1200}, result['effective_unit_prices'])
        self.assertNotEqual('prior_bound_adjustment_requires_transition', result['reason'])
        self.assertEqual(result, evaluate(copy.deepcopy(v)))

    def test_restock_surfaces_accepted_tier_adjustments(self):
        v = self.v12_history()
        v['binding_units'][3]['attempt_id'] = 'fresh-U4-after-restock'
        v['binding_units'][3]['unavailable_line_ids'] = []
        result = evaluate(v)
        self.assertEqual('bound', result['outcome'])
        self.assertEqual('bound', result['unit_results'][3]['reason'])
        self.assertTrue(all(price == 1000 for price in result['effective_unit_prices'].values()))
        self.assertEqual({'L01':1200},
                         v['business_state']['attempt_history'][0]['effective_unit_prices'])
        self.assertEqual(3, len(result['adjustments']))
        self.assertTrue(all(a['previous_unit_price'] == 1200 and a['new_unit_price'] == 1000
                            and a['authorization_source'] == 'accepted_unit_count_tier'
                            for a in result['adjustments']))

    def test_restock_replay_recognizes_existing_adjustment(self):
        """U1-U3 keep bind-time 1200, U4 binds at 1000, then the request replays."""
        v = self.v12_history()
        v['binding_units'][3]['attempt_id'] = 'fresh-U4-after-restock'
        v['binding_units'][3]['unavailable_line_ids'] = []
        first = evaluate(v)
        self.assertEqual(3, len(first['adjustments']))
        self.persist(v, first)
        history = copy.deepcopy(v['business_state']['attempt_history'])
        applied = copy.deepcopy(v['business_state']['commercial_basis_adjustments'])

        replay = evaluate(v)
        self.assertNotEqual('invalid_artifact', replay['outcome'])
        self.assertNotEqual('prior_bound_adjustment_requires_transition', replay['reason'])
        self.assertEqual('bound', replay['outcome'])
        # The existing adjustment is recognized, so nothing new is emitted.
        self.assertNotIn('adjustments', replay)
        self.assertTrue(all(price == 1000 for price in replay['effective_unit_prices'].values()))
        # Bind-time history stays immutable and no duplicate history is written.
        self.assertEqual(history, v['business_state']['attempt_history'])
        self.assertEqual({'L01': 1200}, v['business_state']['attempt_history'][0]['effective_unit_prices'])
        self.persist(v, replay)
        self.assertEqual(applied, v['business_state']['commercial_basis_adjustments'])
        self.assertEqual(3, len(v['business_state']['commercial_basis_adjustments']))
        self.assertEqual(replay, evaluate(copy.deepcopy(v)))

    def test_later_bind_with_unchanged_tier_emits_no_further_adjustment(self):
        """A 2-unit tier at 1100 adjusts once, then stays put as U3 binds."""
        v = self.fixture(12)
        rule = v['term_artifact']['binding_authorization']['contraction_rule']
        rule['tiers'].append({'minimum_units': 2, 'unit_price': 1100})
        v['business_state']['attempt_history'] = []
        emitted, derived_after = [], []
        for index in range(4):
            request = copy.deepcopy(v)
            # Present all four units every time; the rest are unavailable.
            for position, group in enumerate(request['binding_units']):
                group['attempt_id'] = 'seq-%d-U%d' % (index, position + 1)
                group['unavailable_line_ids'] = [] if position <= index else group['line_ids']
            result = evaluate(request)
            emitted.append(result)
            self.assertTrue(result['bindable'])
            self.assertNotEqual('prior_bound_adjustment_requires_transition', result['reason'])
            v['business_state'] = copy.deepcopy(self.persist(request, result)['business_state'])
            # Reconstruct from each line's real bind-time basis, taken from the
            # authoritative attempt history rather than assumed.
            bind_time = {}
            for record in v['business_state']['attempt_history']:
                bind_time.update(record.get('effective_unit_prices', {}))
            derived_after.append(current_commercial_basis(
                v['business_state'], v['term_artifact']['id'],
                v['term_artifact']['revision'], bind_time)['L01'])

        # U2 binds: count 2, tier 1100, and L01 records a persisted 1200 -> 1100.
        self.assertEqual(2, emitted[1]['effective_bound_line_count'])
        self.assertEqual(1100, emitted[1]['effective_unit_prices']['L01'])
        self.assertEqual([{'line_id': 'L01', 'previous_unit_price': 1200, 'new_unit_price': 1100,
                           'authorization_source': 'accepted_unit_count_tier',
                           'triggering_attempt_id': 'seq-1-U2', 'tier_minimum_units': 2,
                           'effective_unit_count': 2, 'revision': 4}],
                         emitted[1]['adjustments'])

        # U3 binds: count 3, the authorized tier is still 1100, nothing new is emitted.
        self.assertEqual(3, emitted[2]['effective_bound_line_count'])
        self.assertEqual(1100, emitted[2]['effective_unit_prices']['L01'])
        self.assertNotIn('adjustments', emitted[2])
        # U4 is still unavailable at this step, so the request succeeds partially.
        self.assertEqual('partially_bound', emitted[2]['outcome'])
        # All four bound units reach the 1000 tier on the final request.
        self.assertEqual('bound', emitted[3]['outcome'])

        # Bind-time history still records 1200 after every adjustment.
        self.assertEqual(1200, v['business_state']['attempt_history'][0]['effective_unit_prices']['L01'])
        # Each request derives its current basis rather than re-reading bind time.
        self.assertEqual(1100, derived_after[1])
        self.assertEqual(1100, derived_after[2])
        # Only the fourth unit moves the basis again, to the 4-unit tier.
        self.assertEqual(1000, derived_after[3])

    def adjustment(self, previous, new, attempt, tier, line='L01', artifact='award-10001'):
        return dict(artifact_id=artifact, line_id=line, previous_unit_price=previous,
                    new_unit_price=new, authorization_source='accepted_unit_count_tier',
                    triggering_attempt_id=attempt, tier_minimum_units=tier,
                    effective_unit_count=tier, revision=4)

    def test_current_basis_consumes_sequential_chain_in_recorded_order(self):
        chain = [self.adjustment(1200, 1100, 'a1', 2), self.adjustment(1100, 1000, 'a2', 4)]
        state = {'commercial_basis_adjustments': chain + [
            self.adjustment(1000, 1, 'a3', 4, artifact='other-artifact')]}
        bind_time = {'L01': 1200, 'L02': 1200}
        self.assertEqual({'L01': 1000, 'L02': 1200},
                         current_commercial_basis(state, 'award-10001', 4, bind_time))
        # Bind-time records are never rewritten by derivation.
        self.assertEqual({'L01': 1200, 'L02': 1200}, bind_time)

    def test_reversed_chain_fails_closed_without_reordering(self):
        chain = [self.adjustment(1200, 1100, 'a1', 2), self.adjustment(1100, 1000, 'a2', 4)]
        state = {'commercial_basis_adjustments': list(reversed(chain))}
        with self.assertRaises(InconsistentAdjustmentHistory):
            current_commercial_basis(state, 'award-10001', 4, {'L01': 1200})

    def test_broken_chain_link_fails_closed(self):
        state = {'commercial_basis_adjustments': [
            self.adjustment(1200, 1100, 'a1', 2), self.adjustment(999, 1000, 'a2', 4)]}
        with self.assertRaises(InconsistentAdjustmentHistory):
            current_commercial_basis(state, 'award-10001', 4, {'L01': 1200})

    def restock_with_adjustments(self, *adjustments):
        v = self.v12_history()
        v['binding_units'][3]['attempt_id'] = 'fresh-U4-after-restock'
        v['binding_units'][3]['unavailable_line_ids'] = []
        v['business_state']['commercial_basis_adjustments'] = list(adjustments)
        return v

    def assertStructurallyInvalid(self, vector):
        result = evaluate(vector)
        # Present-but-contradictory history is structural invalidity, never a
        # retryable outage.
        self.assertEqual('invalid_artifact_semantics', result['reason'])
        self.assertFalse(result['artifact_valid'])
        self.assertEqual('invalid_artifact', result['outcome'])
        self.assertNotEqual('commercial_basis_history_unavailable', result['reason'])
        self.assertNotEqual('same_attempt_later', result['recovery_action'])
        return result

    def applied_adjustment(self, previous, new, line='L01', attempt='fresh-U4-after-restock',
                           tier=4, revision=4, count=None):
        """A persisted adjustment record.

        `count` is the effective bound-unit count recorded with the transition;
        it defaults to the tier threshold, the smallest count that selects it.
        """
        return dict(artifact_id='award-10001', line_id=line,
                    previous_unit_price=previous, new_unit_price=new,
                    authorization_source='accepted_unit_count_tier',
                    triggering_attempt_id=attempt, tier_minimum_units=tier,
                    effective_unit_count=tier if count is None else count,
                    revision=revision)

    def restock(self):
        v = self.v12_history()
        v['binding_units'][3]['attempt_id'] = 'fresh-U4-after-restock'
        v['binding_units'][3]['unavailable_line_ids'] = []
        return v

    def sequential_tier_history(self):
        """Bind one unit at a time under a 2-unit tier, building a real chain.

        Produces two distinct transition identities on L01: 1200->1100 under the
        2-unit tier, then 1100->1000 under the 4-unit tier.
        """
        v = self.fixture(12)
        v['term_artifact']['binding_authorization']['contraction_rule']['tiers'].append(
            {'minimum_units': 2, 'unit_price': 1100})
        v['business_state']['attempt_history'] = []
        v['business_state']['commercial_basis_adjustments'] = []
        final = None
        for index in range(4):
            request = copy.deepcopy(v)
            for position, group in enumerate(request['binding_units']):
                group['attempt_id'] = 'seq-%d-U%d' % (index, position + 1)
                group['unavailable_line_ids'] = [] if position <= index else group['line_ids']
            result = evaluate(request)
            v['business_state'] = copy.deepcopy(self.persist(request, result)['business_state'])
            final = request
        final['business_state'] = v['business_state']
        return final

    def test_multi_step_chain_validates_against_predecessor_basis(self):
        """A later transition is checked against the basis immediately before it.

        This exercises the chain-link path, not the already-applied identity
        branch: on a fully persisted replay every unit is already bound, so
        there is no newly-bound triggering attempt and no identity can match.
        `test_identity_branch_is_exercised_on_partial_replay` covers that branch.
        """
        request = self.sequential_tier_history()
        chain = [a for a in request['business_state']['commercial_basis_adjustments']
                 if a['line_id'] == 'L01']
        self.assertEqual([(1200, 1100), (1100, 1000)],
                         [(a['previous_unit_price'], a['new_unit_price']) for a in chain])
        self.assertNotEqual(adjustment_identity(chain[0]), adjustment_identity(chain[1]))

        # Replaying the fully persisted request emits nothing further.
        replay = evaluate(request)
        self.assertEqual('bound', replay['outcome'])
        self.assertNotIn('adjustments', replay)
        self.assertEqual(1000, replay['effective_unit_prices']['L01'])

        # B is validated against 1100, not bind-time 1200 nor final 1000.
        for wrong_previous in (1200, 1000):
            with self.subTest(tampered_previous=wrong_previous):
                tampered = self.sequential_tier_history()
                for record in tampered['business_state']['commercial_basis_adjustments']:
                    if record['line_id'] == 'L01' and record['tier_minimum_units'] == 4:
                        record['previous_unit_price'] = wrong_previous
                self.assertEqual('invalid_artifact_semantics', evaluate(tampered)['reason'])

        # A is likewise validated against its own predecessor, the bind-time basis.
        tampered = self.sequential_tier_history()
        for record in tampered['business_state']['commercial_basis_adjustments']:
            if record['line_id'] == 'L01' and record['tier_minimum_units'] == 2:
                record['previous_unit_price'] = 1000
        self.assertEqual('invalid_artifact_semantics', evaluate(tampered)['reason'])

    def test_repeated_transition_identity_is_rejected(self):
        """A repeated transition identity cannot form valid history.

        There is no dedicated duplicate check: to chain, a duplicate must either
        restate its predecessor's move (breaking the link) or collapse into a
        no-op the producer never emits. The chain-link and no-op rules therefore
        reject every form, which is why no separate guard is retained.
        """
        duplicates = (
            ('no-op then canonical',
             [self.applied_adjustment(1200, 1200), self.applied_adjustment(1200, 1000)]),
            ('two chaining steps under one identity',
             [self.applied_adjustment(1200, 1100),
              dict(self.applied_adjustment(1200, 1100),
                   previous_unit_price=1100, new_unit_price=1000)]),
            ('canonical then no-op',
             [self.applied_adjustment(1200, 1000),
              dict(self.applied_adjustment(1200, 1000),
                   previous_unit_price=1000, new_unit_price=1000)]),
            ('exact duplicate',
             [self.applied_adjustment(1200, 1000), dict(self.applied_adjustment(1200, 1000))]),
        )
        for label, records in duplicates:
            with self.subTest(history=label):
                v = self.restock()
                v['business_state']['commercial_basis_adjustments'] = records
                self.assertEqual('invalid_artifact_semantics', evaluate(v)['reason'])

    def test_unobtainable_history_is_never_read_as_corruption(self):
        """Orphan rejection requires authoritative history to be available.

        An adjustment can only be judged orphaned against a bound basis that was
        actually obtained. When the authoritative history cannot be read, the
        harness reports unavailability and stays retryable rather than inferring
        corruption from absence.
        """
        orphan = self.applied_adjustment(1000, 900, line='L04', attempt='a-later-cycle')

        unavailable = self.restock()
        unavailable['business_state']['attempt_history_available'] = False
        unavailable['business_state']['commercial_basis_adjustments'] = [orphan]
        result = evaluate(unavailable)
        self.assertEqual('attempt_history_unavailable', result['reason'])
        self.assertTrue(result['artifact_valid'])
        self.assertEqual('same_attempt_later', result['recovery_action'])

        basis_unavailable = self.restock()
        basis_unavailable['business_state']['commercial_basis_history_available'] = False
        basis_unavailable['business_state']['commercial_basis_adjustments'] = [orphan]
        result = evaluate(basis_unavailable)
        self.assertEqual('commercial_basis_history_unavailable', result['reason'])
        self.assertTrue(result['artifact_valid'])
        self.assertEqual('same_attempt_later', result['recovery_action'])

        # With history available, the same record is impossible, not unavailable.
        available = self.restock()
        available['business_state']['commercial_basis_adjustments'] = [orphan]
        result = evaluate(available)
        self.assertEqual('invalid_artifact_semantics', result['reason'])
        self.assertFalse(result['artifact_valid'])

    def test_same_revision_record_for_unknown_line_fails_closed(self):
        """A line no revision of the artifact carries cannot describe a transition."""
        v = self.restock()
        self.assertNotIn('L99', {line['line_id'] for line in v['term_artifact']['lines']})
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, line='L99')]
        result = evaluate(v)
        self.assertEqual('invalid_artifact_semantics', result['reason'])
        self.assertFalse(result['artifact_valid'])

    def test_same_revision_record_for_unbound_line_is_orphaned_history(self):
        """L04 is a real artifact line, but nothing records it as bound.

        The producer emits an adjustment only for a line whose authoritative
        attempt history records it as bound, and that history is append-only
        across cycles just as the adjustment store is. A same-revision record for
        a line absent from the reconstructed bound basis therefore could not have
        been produced by any modeled lifecycle operation, so it fails closed even
        though the line exists in the artifact.
        """
        v = self.restock()
        first = evaluate(self.restock())
        bound_lines = set(first['effective_unit_prices'])
        self.assertIn('L04', {line['line_id'] for line in v['term_artifact']['lines']})
        v['business_state']['commercial_basis_adjustments'] = [
            dict(artifact_id='award-10001', **adjustment) for adjustment in first['adjustments']]
        self.assertNotIn('L04', {a['line_id'] for a in
                                 v['business_state']['commercial_basis_adjustments']})
        v['business_state']['commercial_basis_adjustments'].append(
            self.applied_adjustment(1000, 900, line='L04', attempt='a-later-cycle'))
        result = evaluate(v)
        self.assertEqual('invalid_artifact_semantics', result['reason'])
        self.assertFalse(result['artifact_valid'])
        self.assertIsNotNone(bound_lines)

    def test_other_revision_record_for_unknown_line_is_out_of_chain(self):
        v = self.restock()
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, line='L99', revision=3)]
        self.assertEqual('bound', evaluate(v)['outcome'])

    def test_reserved_namespace_matches_schema_restriction(self):
        """One source of truth: code and schema must reserve the same names."""
        schema = load_json(SCHEMA_PATH)
        conditions = (schema['definitions']['postBind']['properties']['governing_semantics']
                      ['properties']['execution_invalidation_conditions'])
        forbidden = frozenset(conditions['items']['not']['enum'])
        self.assertEqual(RESERVED_LIFECYCLE_REASONS, forbidden)
        # Every transient failure is part of the reserved namespace.
        self.assertTrue(TRANSIENT_LIFECYCLE_FAILURES <= RESERVED_LIFECYCLE_REASONS)

    def test_emitted_adjustment_becomes_a_record_only_once_persisted(self):
        """Boundary: units() emits an adjustment; persistence adds artifact_id."""
        schema = load_json(SCHEMA_PATH)
        adjustment_schema = schema['definitions']['adjustment']
        record_schema = schema['definitions']['adjustmentRecord']
        v = self.restock()
        emitted = evaluate(v)['adjustments'][0]
        # The emitted object is a complete `adjustment` but NOT yet a record.
        self.assertTrue(Draft7Validator(adjustment_schema).is_valid(emitted))
        self.assertFalse(Draft7Validator(record_schema).is_valid(emitted))
        self.assertEqual({'artifact_id'}, set(record_schema['required']) - set(emitted))

        # The enclosing persistence step supplies artifact_id.
        first = evaluate(v)
        self.persist(v, first)
        stored = v['business_state']['commercial_basis_adjustments']
        for record in stored:
            with self.subTest(line=record['line_id']):
                self.assertTrue(Draft7Validator(record_schema).is_valid(record))
                self.assertEqual('award-10001', record['artifact_id'])
        # It lands in the correctly scoped chain and replays without re-emission.
        self.assertEqual(len(stored),
                         len(adjustment_chain(v['business_state'], 'award-10001', 4)))
        self.assertEqual([], adjustment_chain(v['business_state'], 'award-10001', 5))
        self.assertNotIn('adjustments', evaluate(v))

    def test_same_identity_with_different_effect_fails_closed(self):
        """An idempotency key is not proof the right adjustment was applied.

        1200->1100 is structurally linkable and carries the currently authorized
        identity, but the authorized transition is 1200->1000. It must not
        suppress the required adjustment.
        """
        v = self.restock()
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1100)]
        result = evaluate(v)
        self.assertEqual('invalid_artifact_semantics', result['reason'])
        self.assertFalse(result['artifact_valid'])

    def test_duplicate_identity_fails_even_when_prices_chain(self):
        """One transition identity recorded twice is contradictory history."""
        v = self.restock()
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1100), self.applied_adjustment(1100, 1000)]
        self.assertEqual('invalid_artifact_semantics', evaluate(v)['reason'])

    def test_identity_branch_is_exercised_on_partial_replay(self):
        """Proves the already-applied identity branch actually runs.

        The branch needs a newly-bound unit whose attempt triggered the persisted
        adjustment. The restock replay is exactly that state: U4 is still binding
        under `fresh-U4-after-restock`, which is the trigger recorded on the
        persisted adjustments, so the reconstructed identity matches.
        """
        v = self.restock()
        first = evaluate(self.restock())
        trigger = {a['triggering_attempt_id'] for a in first['adjustments']}
        self.assertEqual({'fresh-U4-after-restock'}, trigger)
        v['business_state']['commercial_basis_adjustments'] = [
            dict(artifact_id='award-10001', **adjustment) for adjustment in first['adjustments']]

        replay = evaluate(v)
        # U4 is still newly bound, so a triggering attempt exists and the
        # identity branch is reachable rather than short-circuited.
        self.assertEqual(['L04'], replay['unit_results'][3]['newly_bound_line_ids'])
        self.assertNotIn('adjustments', replay)
        self.assertEqual('bound', replay['outcome'])

        # The branch is what suppresses re-emission: corrupt only the persisted
        # effect and the same path now reports a conflict.
        contradictory = self.restock()
        contradictory['business_state']['commercial_basis_adjustments'] = [
            dict(artifact_id='award-10001', **adjustment) for adjustment in first['adjustments']]
        contradictory['business_state']['commercial_basis_adjustments'][0][
            'previous_unit_price'] = 1150
        self.assertEqual('invalid_artifact_semantics', evaluate(contradictory)['reason'])

    def test_producer_never_dates_a_record_after_the_current_attempt(self):
        """`applied_at` must satisfy bound_at <= applied_at <= execution_attempt.at."""
        cases = (
            ('release success', 9, True, self.LEGITIMATE_EVENT, 'release_condition_satisfied'),
            ('release failure', 9, False, self.LEGITIMATE_EVENT, 'release_condition_failed'),
        )
        for label, vector_id, met, resolved, expected in cases:
            with self.subTest(case=label):
                v = self.fixture(vector_id)
                v['post_bind']['terminal_outcome'] = None
                v['post_bind']['execution_attempt'].update(
                    at='2026-09-12T17:00:00Z', release_condition_met=met,
                    release_resolved_at=resolved)
                first = evaluate_post_bind(v)
                self.assertEqual(expected, first['reason'])
                # After the current attempt: refused.
                self.assertIsNone(
                    persistable_terminal_outcome(v, first, '2026-09-12T19:00:00Z'))
                # Before binding: refused.
                self.assertIsNone(
                    persistable_terminal_outcome(v, first, '2026-09-12T09:00:00Z'))
                # Inclusive bounds both hold.
                for applied in ('2026-09-12T13:00:00Z', '2026-09-12T17:00:00Z'):
                    record = persistable_terminal_outcome(v, first, applied)
                    self.assertIsNotNone(record)
                    replayed = copy.deepcopy(v)
                    replayed['post_bind']['terminal_outcome'] = record
                    self.assertEqual(first, evaluate_post_bind(replayed))

        # Ordinary execution and a declared invalidation, same bound.
        for label, conditions, expected in (('ordinary execution', [], 'executed'),
                                            ('declared invalidation',
                                             ['inventory_allocation_changed'],
                                             'inventory_allocation_changed')):
            with self.subTest(case=label):
                v = self.fixture(8)
                v['post_bind']['terminal_outcome'] = None
                v['post_bind']['execution_attempt'].update(
                    at='2026-09-12T12:00:00Z', active_invalidation_conditions=conditions)
                first = evaluate_post_bind(v)
                self.assertEqual(expected, first['reason'])
                self.assertIsNone(
                    persistable_terminal_outcome(v, first, '2026-09-12T13:00:00Z'))
                self.assertIsNotNone(
                    persistable_terminal_outcome(v, first, '2026-09-12T12:00:00Z'))

    def partial_persistence_retry(self):
        """History with A(1200->1100) and B(1100->1000) persisted, B's trigger live.

        U1-U3 bind across two tiers, then U4 binds and emits B. The adjustment
        writes are durable but U4's bound attempt record is not, so on retry U4
        binds newly again and B's canonical identity is reconstructed.
        """
        v = self.fixture(12)
        v['term_artifact']['binding_authorization']['contraction_rule']['tiers'].append(
            {'minimum_units': 2, 'unit_price': 1100})
        v['business_state']['attempt_history'] = []
        v['business_state']['commercial_basis_adjustments'] = []
        for index in range(3):
            request = copy.deepcopy(v)
            for position, group in enumerate(request['binding_units']):
                group['attempt_id'] = 'seq-%d-U%d' % (index, position + 1)
                group['unavailable_line_ids'] = [] if position <= index else group['line_ids']
            result = evaluate(request)
            v['business_state'] = copy.deepcopy(self.persist(request, result)['business_state'])
        final = copy.deepcopy(v)
        for position, group in enumerate(final['binding_units']):
            group['attempt_id'] = 'final-U%d' % (position + 1)
            group['unavailable_line_ids'] = []
        emitted = evaluate(final)
        retry = copy.deepcopy(final)
        retry['business_state'] = copy.deepcopy(v['business_state'])
        retry['business_state']['commercial_basis_adjustments'] = (
            list(v['business_state']['commercial_basis_adjustments'])
            + [dict(artifact_id='award-10001', **a) for a in emitted['adjustments']])
        return retry

    def test_later_adjustment_replays_against_its_predecessor_not_bind_time(self):
        """The identity branch must use the running basis before that record."""
        retry = self.partial_persistence_retry()
        l01 = [(a['previous_unit_price'], a['new_unit_price'])
               for a in retry['business_state']['commercial_basis_adjustments']
               if a['line_id'] == 'L01']
        self.assertEqual([(1200, 1100), (1100, 1000)], l01)

        result = evaluate(retry)
        # The trigger is live, so the identity branch is reached.
        self.assertEqual(['L04'], result['unit_results'][3]['newly_bound_line_ids'])
        self.assertEqual('bound', result['outcome'])
        self.assertNotIn('adjustments', result)

        # B is checked against 1100, not bind-time 1200 nor final 1000.
        for wrong in (1200, 1000):
            with self.subTest(tampered_previous=wrong):
                tampered = self.partial_persistence_retry()
                for record in tampered['business_state']['commercial_basis_adjustments']:
                    if record['line_id'] == 'L01' and record['tier_minimum_units'] == 4:
                        record['previous_unit_price'] = wrong
                self.assertEqual('invalid_artifact_semantics', evaluate(tampered)['reason'])

    def two_unit_tier_history(self, persisted_count=None):
        """History where U1 then U2 bind under a 2-unit tier at 1100.

        `persisted_count` rewrites the recorded transition context on the
        persisted adjustment, to model false provenance.
        """
        v = self.fixture(12)
        v['term_artifact']['binding_authorization']['contraction_rule']['tiers'].append(
            {'minimum_units': 2, 'unit_price': 1100})
        v['business_state']['attempt_history'] = []
        v['business_state']['commercial_basis_adjustments'] = []
        first = copy.deepcopy(v)
        for position, group in enumerate(first['binding_units']):
            group['attempt_id'] = 'b0-U%d' % (position + 1)
            group['unavailable_line_ids'] = [] if position == 0 else group['line_ids']
        v['business_state'] = copy.deepcopy(
            self.persist(first, evaluate(first))['business_state'])
        second = copy.deepcopy(v)
        for position, group in enumerate(second['binding_units']):
            group['attempt_id'] = 'b1-U%d' % (position + 1)
            group['unavailable_line_ids'] = [] if position <= 1 else group['line_ids']
        emitted = evaluate(second)
        records = [dict(artifact_id='award-10001', **a) for a in emitted['adjustments']]
        if persisted_count is not None:
            for record in records:
                record['effective_unit_count'] = persisted_count
        retry = copy.deepcopy(second)
        retry['business_state'] = copy.deepcopy(v['business_state'])
        retry['business_state']['commercial_basis_adjustments'] = (
            list(v['business_state']['commercial_basis_adjustments']) + records)
        return retry

    def test_reserved_name_policy_blocks_every_first_time_class(self):
        """An invalid policy authorizes no first-time class, as in replay."""
        cases = (('terms reinterpretation', False, []),
                 ('ordinary execution', True, []),
                 ('declared invalidation', True, ['inventory_allocation_changed']))
        for label, terms_unchanged, conditions in cases:
            with self.subTest(path=label):
                v = self.fixture(8)
                v['post_bind']['terminal_outcome'] = None
                v['post_bind']['governing_semantics'][
                    'execution_invalidation_conditions'] = ['executed']
                v['post_bind']['execution_attempt'].update(
                    at='2026-09-12T12:00:00Z', terms_unchanged=terms_unchanged,
                    active_invalidation_conditions=conditions)
                result = evaluate_post_bind(v)
                self.assertEqual('invalid_lifecycle_timing', result['reason'])
                self.assertNotEqual('commercial_terms_reinterpreted', result['reason'])
        # A release path under the same invalid policy.
        release = self.fixture(9)
        release['post_bind']['terminal_outcome'] = None
        release['post_bind']['governing_semantics'][
            'execution_invalidation_conditions'] = ['release_condition_satisfied']
        release['post_bind']['execution_attempt'].update(
            at='2026-09-12T17:00:00Z', release_condition_met=True,
            release_resolved_at=self.LEGITIMATE_EVENT)
        self.assertEqual('invalid_lifecycle_timing',
                         evaluate_post_bind(release)['reason'])

    def bogus_bound_record(self, **overrides):
        record = dict(attempt_id='a-ghost-attempt', artifact_id='award-10001',
                      revision=4, binding_unit_id='U1', line_ids=['L01'],
                      target_transaction='checkout-10001', reason='bound',
                      effective_unit_prices={'L01': 1200})
        record.update(overrides)
        record['effective_unit_prices'] = {record['line_ids'][0]: 1200}
        return record

    def test_successful_bound_history_must_match_accepted_authorization(self):
        """Authoritative history is validated before anything consumes it."""
        cases = (
            ('binding unit outside the accepted groups',
             dict(binding_unit_id='UX', line_ids=['LX'])),
            ('accepted unit with the wrong line membership',
             dict(binding_unit_id='U1', line_ids=['L99'])),
            ('accepted unit and lines with the wrong target',
             dict(target_transaction='another-checkout')),
        )
        for label, overrides in cases:
            with self.subTest(record=label):
                v = self.restock()
                v['business_state']['attempt_history'].append(
                    self.bogus_bound_record(**overrides))
                result = evaluate(v)
                self.assertEqual('invalid_artifact_semantics', result['reason'])
                self.assertFalse(result['artifact_valid'])
        # Unmodified authoritative history is still accepted.
        self.assertEqual('bound', evaluate(self.restock())['outcome'])

    MALFORMED_BOUND_SHAPES = (
        ('binding unit outside the accepted groups',
         dict(binding_unit_id='UX', line_ids=['LX'])),
        ('accepted unit with the wrong line membership',
         dict(binding_unit_id='U1', line_ids=['L99'])),
        ('accepted unit and lines with the wrong target',
         dict(target_transaction='another-checkout')),
    )

    def test_colliding_record_is_excluded_from_authoritative_projections(self):
        """Occupancy and a successful bind are different facts.

        A malformed record that the request replays keeps the established
        per-unit idempotency conflict, yet must not reach the authoritative
        basis, realized count, trigger set or duplicate-success detection. The
        outcome differs specifically when it is included versus excluded.
        """
        v = self.restock()
        replayed = [h for h in v['business_state']['attempt_history']
                    if h['binding_unit_id'] == 'U1'][0]
        # Corrupt an existing record the request replays: same attempt id, so no
        # duplicate-id short circuit, but no longer a valid accepted bind.
        replayed.update(binding_unit_id='UX', line_ids=['LX'],
                        effective_unit_prices={'LX': 1200})
        # A chain that is only coherent if UX supplies basis and trigger.
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, line='LX',
                                    attempt=replayed['attempt_id'], count=4)]
        result = evaluate(v)
        self.assertEqual('invalid_artifact_semantics', result['reason'])
        self.assertFalse(result['artifact_valid'])

    def multi_unit_transition(self, tamper=None):
        """U1 bound, then U2 and U3 newly bind together under a 3-unit tier.

        Returns the replay of that transition with the adjustment persisted but
        the U2/U3 attempt records not yet durable, so the transition is
        partially persisted and still in flight.
        """
        v = self.fixture(12)
        v['term_artifact']['binding_authorization']['contraction_rule']['tiers'] = [
            {'minimum_units': 1, 'unit_price': 1200},
            {'minimum_units': 3, 'unit_price': 1000}]
        v['business_state']['attempt_history'] = []
        first = copy.deepcopy(v)
        for position, group in enumerate(first['binding_units']):
            group['attempt_id'] = 'b0-U%d' % (position + 1)
            group['unavailable_line_ids'] = [] if position == 0 else group['line_ids']
        v['business_state'] = copy.deepcopy(
            self.persist(first, evaluate(first))['business_state'])
        second = copy.deepcopy(v)
        for position, group in enumerate(second['binding_units']):
            group['attempt_id'] = 'b1-U%d' % (position + 1)
            group['unavailable_line_ids'] = [] if position <= 2 else group['line_ids']
        emitted = evaluate(second)
        records = [dict(artifact_id='award-10001', **a) for a in emitted['adjustments']]
        if tamper:
            for record in records:
                record.update(tamper)
        second['business_state'] = copy.deepcopy(v['business_state'])
        second['business_state']['commercial_basis_adjustments'] = records
        return second

    # A flat table whose first row already authorizes 1000, so a count-3 record
    # needs no tier beyond what history corroborates and each hostile variant
    # below fails on its own rule rather than on tier or price.
    HISTORY_ONLY_TIERS = [{'minimum_units': 1, 'unit_price': 1000},
                          {'minimum_units': 4, 'unit_price': 900}]

    def stale_with_chain(self, chain, tiers=None):
        v = self.restock()
        v['business_state']['commercial_basis_adjustments'] = chain
        if tiers is not None:
            v['term_artifact']['binding_authorization']['contraction_rule']['tiers'] = tiers
        for group in v['binding_units']:
            group['accepted_revision'] = 3
        return v

    # tier 1 prices at the bind-time basis and tier 3 at 1000, so a 1200->1000
    # record at count 3 is a real, correctly tiered, correctly priced transition.
    REAL_TRANSITION_TIERS = [{'minimum_units': 1, 'unit_price': 1200},
                             {'minimum_units': 3, 'unit_price': 1000}]

    def stale_with_history(self, prices=None, chain=None, tiers=None):
        """A stale request over restock history, optionally with a mutated map."""
        v = self.restock()
        if prices is not None:
            record = next(h for h in v['business_state']['attempt_history']
                          if h['binding_unit_id'] == 'U1')
            record['effective_unit_prices'] = prices
        if chain is not None:
            v['business_state']['commercial_basis_adjustments'] = chain
        v['term_artifact']['binding_authorization']['contraction_rule']['tiers'] = (
            tiers if tiers is not None else self.REAL_TRANSITION_TIERS)
        for group in v['binding_units']:
            group['accepted_revision'] = 3
        return v

    def test_bound_record_price_map_must_match_its_line_membership(self):
        """An authoritative price map describes exactly the scope it bound."""
        # A chain on L02 so validation runs whatever U1's map contains.
        chain = [self.applied_adjustment(1200, 1000, line='L02',
                                         attempt='tier-attempt-0', count=3, tier=3)]
        malformed = (
            ('an extra line', {'L01': 1200, 'L99': 1200}),
            ('a missing line', {}),
            ('a different line of the same cardinality', {'L99': 1200}),
        )
        for label, prices in malformed:
            with self.subTest(price_map=label):
                result = evaluate(self.stale_with_history(prices, chain))
                self.assertEqual('invalid_artifact_semantics', result['reason'])
                self.assertFalse(result['artifact_valid'])
        # The exact map is accepted and leaves the request-level outcome.
        exact = evaluate(self.stale_with_history({'L01': 1200}, chain))
        self.assertNotEqual('invalid_artifact_semantics', exact['reason'])
        self.assertTrue(exact['artifact_valid'])

    def test_duplicate_tier_thresholds_are_invalid_without_active_pricing(self):
        """Tier validity is an accepted-policy invariant, not a pricing one."""
        chain = [self.applied_adjustment(1200, 1000, line='L01',
                                         attempt='tier-attempt-1', count=3, tier=3)]
        duplicates = (
            ('identical prices', [{'minimum_units': 1, 'unit_price': 1200},
                                  {'minimum_units': 3, 'unit_price': 1000},
                                  {'minimum_units': 3, 'unit_price': 1000}]),
            ('conflicting prices', [{'minimum_units': 1, 'unit_price': 1200},
                                    {'minimum_units': 3, 'unit_price': 1000},
                                    {'minimum_units': 3, 'unit_price': 900}]),
        )
        for label, tiers in duplicates:
            with self.subTest(rule=label):
                result = evaluate(self.stale_with_history(None, chain, tiers))
                self.assertEqual('invalid_artifact_semantics', result['reason'])
                self.assertFalse(result['artifact_valid'])
        # Unique thresholds remain valid under the same stale request.
        unique = evaluate(self.stale_with_history(None, chain))
        self.assertNotEqual('invalid_artifact_semantics', unique['reason'])
        self.assertTrue(unique['artifact_valid'])

    def test_orphan_line_is_rejected_by_history_validation(self):
        """A record naming a line with no authoritative bind-time basis."""
        # L04 has no bound history in the restock fixture; every other property
        # of the record is valid.
        v = self.stale_with_chain(
            [self.applied_adjustment(1200, 1000, line='L04',
                                     attempt='tier-attempt-1', count=3, tier=1)],
            self.HISTORY_ONLY_TIERS)
        self.assertNotIn('L04', {line for h in v['business_state']['attempt_history']
                                 if h['reason'] == 'bound'
                                 for line in h.get('effective_unit_prices', {})})
        self.assertEqual('invalid_artifact_semantics', evaluate(v)['reason'])

    def test_no_op_record_is_rejected_by_history_validation(self):
        """Count is >= 2 so the minimum-count guard cannot mask the no-op."""
        # 1200 is both L01's authoritative bind-time basis and the price the
        # cited tier row authorizes, so the record chains, prices and tiers
        # correctly; only the no-op rule can reject it.
        tiers = [{'minimum_units': 1, 'unit_price': 1200},
                 {'minimum_units': 4, 'unit_price': 900}]
        record = self.applied_adjustment(1200, 1200, line='L01',
                                         attempt='tier-attempt-1', count=3, tier=1)
        self.assertGreaterEqual(record['effective_unit_count'], 2)
        self.assertEqual(record['previous_unit_price'], record['new_unit_price'])
        self.assertEqual(record['new_unit_price'], tiers[0]['unit_price'])
        self.assertEqual('invalid_artifact_semantics',
                         evaluate(self.stale_with_chain([record], tiers))['reason'])

    def test_broken_predecessor_is_rejected_by_history_validation(self):
        v = self.stale_with_chain(
            [self.applied_adjustment(999, 1000, line='L01',
                                     attempt='tier-attempt-1', count=3, tier=1)],
            self.HISTORY_ONLY_TIERS)
        self.assertEqual('invalid_artifact_semantics', evaluate(v)['reason'])

    def test_unknown_trigger_fails_without_an_in_flight_transition(self):
        """Absence of an in-flight trigger is not permission.

        Every other property of this record is valid, and the stale request
        makes no unit effective, so only the trigger rule can reject it.
        """
        v = self.stale_with_chain(
            [self.applied_adjustment(1200, 1000, line='L01',
                                     attempt='ghost-attempt', count=3, tier=1)],
            self.HISTORY_ONLY_TIERS)
        self.assertEqual('invalid_artifact_semantics', evaluate(v)['reason'])
        # A real historical trigger in the same shape is accepted.
        ok = self.stale_with_chain(
            [self.applied_adjustment(1200, 1000, line='L01',
                                     attempt='tier-attempt-1', count=3, tier=1)],
            self.HISTORY_ONLY_TIERS)
        self.assertNotEqual('invalid_artifact_semantics', evaluate(ok)['reason'])

    def test_accepted_scope_is_not_evidence_a_count_was_reached(self):
        """Realized state, not artifact size, bounds a historical count.

        The artifact holds four units and history reached three, but with no
        current transition nothing corroborates a count of four. The 4-unit row
        prices at 900, so the false count is not economically detectable.
        """
        v = self.stale_with_chain(
            [self.applied_adjustment(1200, 900, line='L01',
                                     attempt='tier-attempt-1', count=4, tier=4)],
            self.HISTORY_ONLY_TIERS)
        self.assertEqual(4, len(v['term_artifact']['binding_authorization']['groups']))
        self.assertEqual('invalid_artifact_semantics', evaluate(v)['reason'])

    def test_one_transition_may_newly_bind_several_units(self):
        """The reachable count is not historical units plus one."""
        replay = self.multi_unit_transition()
        records = replay['business_state']['commercial_basis_adjustments']
        self.assertEqual([3], sorted({r['effective_unit_count'] for r in records}))
        # Only U1 has authoritative bound history, yet count 3 is reachable
        # because U2 and U3 both become effective in this transition.
        bound = {h['binding_unit_id'] for h in replay['business_state']['attempt_history']
                 if h['reason'] == 'bound'}
        self.assertEqual({'U1'}, bound)

        result = evaluate(replay)
        self.assertEqual('partially_bound', result['outcome'])
        self.assertNotIn('adjustments', result)

        # A count beyond that union still fails closed.
        self.assertEqual('invalid_artifact_semantics',
                         evaluate(self.multi_unit_transition(
                             {'effective_unit_count': 4}))['reason'])

    def test_in_flight_trigger_must_be_the_producer_selection(self):
        """Presence in the request is not trigger eligibility."""
        selected = self.multi_unit_transition()[
            'business_state']['commercial_basis_adjustments'][0]['triggering_attempt_id']
        self.assertEqual('b1-U2', selected)
        # The other newly-binding unit is in the request but is not what the
        # producer selects.
        for attempt in ('b1-U3', 'b1-U1', 'b1-U4'):
            with self.subTest(trigger=attempt):
                tampered = self.multi_unit_transition(
                    {'triggering_attempt_id': attempt})
                self.assertEqual('invalid_artifact_semantics',
                                 evaluate(tampered)['reason'])

    def test_already_bound_attempt_with_history_stays_citable(self):
        """CHARACTERIZATION: an attempt with a validated bound record is citable.

        The producer would not select an already-bound unit for THIS transition,
        but that attempt has a real bound record, so it could legitimately have
        triggered an earlier one. Distinguishing the two needs attempt ordering,
        which the harness does not retain, so this stays within the documented
        limit. The line-membership rule still rejects a record citing the very
        attempt that bound the line it adjusts.
        """
        v = self.restock()
        already_bound = v['binding_units'][0]['attempt_id']
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, line='L02',
                                    attempt=already_bound, count=4)]
        self.assertEqual('bound', evaluate(v)['outcome'])

        # Citing the attempt that bound the adjusted line remains impossible.
        self_citing = self.restock()
        self_citing['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, line='L01',
                                    attempt=already_bound, count=4)]
        self.assertEqual('invalid_artifact_semantics',
                         evaluate(self_citing)['reason'])

    def test_corrupt_history_is_detected_despite_a_failing_request(self):
        """A stale request must not hide corrupt stored history."""
        corrupt = (
            ('broken predecessor link', [self.applied_adjustment(999, 1000)]),
            ('no-op adjustment',
             [self.applied_adjustment(1200, 1200, attempt='tier-attempt-1', tier=1)]),
            ('unrecognised authorization source',
             [dict(self.applied_adjustment(1200, 1000),
                   authorization_source='made_up_authority')]),
            ('price the cited tier does not authorize',
             [self.applied_adjustment(1200, 1050)]),
        )
        for label, chain in corrupt:
            with self.subTest(chain=label):
                v = self.restock()
                v['business_state']['commercial_basis_adjustments'] = chain
                for group in v['binding_units']:
                    group['accepted_revision'] = 3
                self.assertEqual('invalid_artifact_semantics',
                                 evaluate(v)['reason'])

        # Control: a chain whose count authoritative history alone corroborates
        # stays a request-level outcome under the same stale request.
        control = self.restock()
        control['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, line='L01',
                                    attempt='tier-attempt-1', count=3, tier=1)]
        control['term_artifact']['binding_authorization']['contraction_rule'][
            'tiers'] = [{'minimum_units': 1, 'unit_price': 1000},
                        {'minimum_units': 4, 'unit_price': 900}]
        for group in control['binding_units']:
            group['accepted_revision'] = 3
        result = evaluate(control)
        self.assertNotEqual('invalid_artifact_semantics', result['reason'])
        self.assertTrue(result['artifact_valid'])

    def test_attempt_id_collision_does_not_authenticate_the_stored_record(self):
        """Occupying an attempt id and binding accepted scope are different facts.

        A malformed record sharing a current attempt id keeps the established
        request-level idempotency conflict, but it is excluded from the
        authoritative bound view, so it cannot supply basis, count or trigger.
        """
        for label, overrides in self.MALFORMED_BOUND_SHAPES:
            with self.subTest(record=label):
                v = self.restock()
                colliding = v['binding_units'][2]['attempt_id']
                v['business_state']['attempt_history'].append(
                    self.bogus_bound_record(attempt_id=colliding, **overrides))
                # The established contract for the current request is preserved.
                self.assertEqual('idempotency_conflict', evaluate(v)['reason'])

    def test_colliding_malformed_record_cannot_supply_trigger_or_count(self):
        """It must not become authoritative history for any other purpose."""
        for label, overrides in self.MALFORMED_BOUND_SHAPES:
            with self.subTest(record=label):
                v = self.restock()
                # Collide with a unit that is already bound, so the request keeps
                # evaluating and the historical projections are actually read.
                colliding = v['binding_units'][0]['attempt_id']
                v['business_state']['attempt_history'].append(
                    self.bogus_bound_record(attempt_id=colliding, **overrides))
                # An adjustment that would only be valid if the malformed record
                # counted as authoritative history.
                v['business_state']['commercial_basis_adjustments'] = [
                    self.applied_adjustment(1200, 1000, line='L01',
                                            attempt=colliding, count=4)]
                result = evaluate(v)
                self.assertNotEqual('bound', result['outcome'])
                self.assertNotEqual('partially_bound', result['outcome'])

    def test_non_colliding_malformed_history_remains_global_corruption(self):
        """The exception is narrow: only the reported collision is excused."""
        for label, overrides in self.MALFORMED_BOUND_SHAPES:
            with self.subTest(record=label):
                v = self.restock()
                v['business_state']['attempt_history'].append(
                    self.bogus_bound_record(attempt_id='not-a-current-attempt',
                                            **overrides))
                result = evaluate(v)
                self.assertEqual('invalid_artifact_semantics', result['reason'])
                self.assertFalse(result['artifact_valid'])

    def test_bogus_bound_history_cannot_inflate_the_realized_count(self):
        """Realized effective units stay a subset of accepted binding units.

        Without global validation a fabricated `bound` record for a unit outside
        the accepted groups would raise the realized count and let an otherwise
        impossible transition count pass.
        """
        v = self.restock()
        v['business_state']['attempt_history'] = [
            h for h in v['business_state']['attempt_history']
            if h['binding_unit_id'] != 'U3']
        v['binding_units'][2]['unavailable_line_ids'] = ['L03']
        v['business_state']['attempt_history'].append(
            self.bogus_bound_record(binding_unit_id='UX', line_ids=['LX']))
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, line='L01', count=4,
                                    attempt='tier-attempt-1')]
        result = evaluate(v)
        self.assertEqual('invalid_artifact_semantics', result['reason'])
        self.assertFalse(result['artifact_valid'])

    def test_stored_chain_survives_a_request_that_cannot_reconstruct_it(self):
        """Orphan detection reads authoritative history, not this request.

        A stale or conflicting request reclassifies no unit as already-bound, so
        a request-relative check would call valid stored history orphaned.
        """
        persisted = [dict(artifact_id='award-10001', **adjustment)
                     for adjustment in evaluate(self.restock())['adjustments']]

        # A chain whose count history alone corroborates survives a stale
        # request: it is rejected on the request's own terms, not by declaring
        # the stored history corrupt.
        stale = self.restock()
        stale['term_artifact']['binding_authorization']['contraction_rule'][
            'tiers'] = [{'minimum_units': 1, 'unit_price': 1000},
                        {'minimum_units': 4, 'unit_price': 900}]
        stale['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, line='L01',
                                    attempt='tier-attempt-1', count=3, tier=1)]
        for group in stale['binding_units']:
            group['accepted_revision'] = 3
        result = evaluate(stale)
        self.assertNotEqual('invalid_artifact_semantics', result['reason'])
        self.assertTrue(result['artifact_valid'])

        conflicted = self.restock()
        conflicted['business_state']['commercial_basis_adjustments'] = list(persisted)
        conflicted['binding_units'][1]['attempt_id'] = (
            conflicted['binding_units'][0]['attempt_id'])
        self.assertEqual('idempotency_conflict', evaluate(conflicted)['reason'])

        # A genuinely orphaned chain still fails closed.
        orphaned = self.fixture(12)
        orphaned['business_state']['attempt_history'] = []
        orphaned['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000)]
        self.assertEqual('invalid_artifact_semantics', evaluate(orphaned)['reason'])

    def test_adjustment_chain_without_any_bound_basis_is_impossible(self):
        """An adjustment needs already-bound scope to apply to."""
        v = self.fixture(12)
        v['business_state']['attempt_history'] = []
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000)]
        result = evaluate(v)
        self.assertEqual('invalid_artifact_semantics', result['reason'])
        self.assertFalse(result['artifact_valid'])

        # Unavailable history still fails closed as retryable, not corrupt.
        unavailable = self.fixture(12)
        unavailable['business_state']['attempt_history'] = []
        unavailable['business_state']['attempt_history_available'] = False
        unavailable['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000)]
        retry = evaluate(unavailable)
        self.assertEqual('attempt_history_unavailable', retry['reason'])
        self.assertEqual('same_attempt_later', retry['recovery_action'])

        # Another revision's records are outside this chain and harmless.
        other = self.fixture(12)
        other['business_state']['attempt_history'] = []
        other['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, revision=3)]
        self.assertEqual('partially_bound', evaluate(other)['outcome'])

    def test_trigger_must_match_an_accepted_binding_unit_and_target(self):
        """Retained membership and target provenance is checked, not just existence."""
        v = self.restock()
        # The attempt that bound L01 cannot trigger an adjustment to L01.
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, line='L01', attempt='tier-attempt-0')]
        self.assertEqual('invalid_artifact_semantics', evaluate(v)['reason'])

        # A historical record whose line membership no longer matches its
        # accepted binding unit is incoherent provenance.
        drifted = self.restock()
        for record in drifted['business_state']['attempt_history']:
            if record['binding_unit_id'] == 'U1':
                record['line_ids'] = ['L02']
        drifted['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, line='L03', attempt='tier-attempt-0')]
        self.assertEqual('invalid_artifact_semantics', evaluate(drifted)['reason'])

    def custom_tier_history(self, tiers, binds):
        """Bind units one at a time under a caller-supplied tier table.

        Returns the state after `binds` units, plus a request in which the next
        unit is newly binding, so adversarial records can be injected into a
        realistic chain.
        """
        v = self.fixture(12)
        v['term_artifact']['binding_authorization']['contraction_rule']['tiers'] = tiers
        v['business_state']['attempt_history'] = []
        v['business_state']['commercial_basis_adjustments'] = []
        for index in range(binds):
            request = copy.deepcopy(v)
            for position, group in enumerate(request['binding_units']):
                group['attempt_id'] = 's%d-U%d' % (index, position + 1)
                group['unavailable_line_ids'] = [] if position <= index else group['line_ids']
            v['business_state'] = copy.deepcopy(
                self.persist(request, evaluate(request))['business_state'])
        final = copy.deepcopy(v)
        for position, group in enumerate(final['binding_units']):
            group['attempt_id'] = 'f-U%d' % (position + 1)
            group['unavailable_line_ids'] = [] if position <= binds else group['line_ids']
        final['business_state'] = copy.deepcopy(v['business_state'])
        return final

    def test_false_count_is_rejected_when_prices_cannot_expose_it(self):
        """Realized-count validation is a fact prices cannot establish.

        With thresholds 1, 2 and 4 priced 1200, 1100 and 1100, a record claiming
        count 4 selects the same price as the true count 2, so tier-selection and
        canonical-effect validation cannot see the lie. Only the realized bound
        rejects it: authoritative state has reached three units, never four.
        """
        tiers = [{'minimum_units': 1, 'unit_price': 1200},
                 {'minimum_units': 2, 'unit_price': 1100},
                 {'minimum_units': 4, 'unit_price': 1100}]
        self.assertEqual(tiers[1]['unit_price'], tiers[2]['unit_price'])

        honest = self.custom_tier_history(tiers, 2)
        self.assertEqual('partially_bound', evaluate(honest)['outcome'])

        false_count = self.custom_tier_history(tiers, 2)
        for record in false_count['business_state']['commercial_basis_adjustments']:
            if record['line_id'] == 'L01':
                self.assertEqual(2, record['effective_unit_count'])
                record.update(effective_unit_count=4, tier_minimum_units=4)
        result = evaluate(false_count)
        self.assertEqual('invalid_artifact_semantics', result['reason'])
        self.assertFalse(result['artifact_valid'])

    def test_adjustment_count_below_two_is_impossible_producer_output(self):
        """The producer minimum is a fact prices cannot establish either.

        With thresholds 1, 2 and 3 priced 1200, 1100 and 1200, a count-1 record
        moving 1100 to 1200 cites a row that authorizes exactly that price and is
        economically identical to the current target, yet no adjustment-producing
        transition can have a single effective unit.
        """
        tiers = [{'minimum_units': 1, 'unit_price': 1200},
                 {'minimum_units': 2, 'unit_price': 1100},
                 {'minimum_units': 3, 'unit_price': 1200}]
        self.assertEqual(tiers[0]['unit_price'], tiers[2]['unit_price'])

        honest = self.custom_tier_history(tiers, 3)
        self.assertEqual('bound', evaluate(honest)['outcome'])

        # Rewrite the whole chain so the only impossible fact is the count: one
        # record, a real compatible trigger, a row that authorizes its price.
        fabricated = self.custom_tier_history(tiers, 3)
        fabricated['business_state']['commercial_basis_adjustments'] = [
            dict(artifact_id='award-10001', line_id='L02',
                 previous_unit_price=1100, new_unit_price=1200,
                 authorization_source='accepted_unit_count_tier',
                 triggering_attempt_id='s2-U3', tier_minimum_units=1,
                 effective_unit_count=1, revision=4)]
        result = evaluate(fabricated)
        self.assertEqual('invalid_artifact_semantics', result['reason'])
        self.assertFalse(result['artifact_valid'])

    def test_count_beyond_realized_state_fails_closed(self):
        """A count authoritative state has not reached is rejected."""
        v = self.restock()
        v['business_state']['attempt_history'] = [
            h for h in v['business_state']['attempt_history']
            if h['binding_unit_id'] != 'U3']
        v['binding_units'][2]['unavailable_line_ids'] = ['L03']
        v['binding_units'][3]['unavailable_line_ids'] = ['L04']
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, line='L01', count=4,
                                    attempt='tier-attempt-1')]
        self.assertFalse(evaluate(v)['artifact_valid'])

    def test_single_unit_adjustment_count_is_unreachable(self):
        """Count 1 cannot describe producer output.

        An adjustment needs previously-bound scope plus a different newly-binding
        unit, so the minimum of two is enforced explicitly in both the schema and
        semantic validation.
        """
        v = self.restock()
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1200, count=1, tier=1)]
        self.assertEqual('invalid_artifact_semantics', evaluate(v)['reason'])

    def test_duplicate_successful_bound_history_is_structural_corruption(self):
        """I19: accepted scope cannot be bound twice, even under a fresh attempt."""
        for label, price in (('identical prices', 1200), ('conflicting prices', 1300)):
            with self.subTest(duplicate=label):
                v = self.restock()
                history = v['business_state']['attempt_history']
                original = next(h for h in history if h['binding_unit_id'] == 'U1')
                duplicate = dict(original, attempt_id='a-second-attempt',
                                 effective_unit_prices={'L01': price})
                history.append(duplicate)
                result = evaluate(v)
                self.assertEqual('invalid_artifact_semantics', result['reason'])
                self.assertFalse(result['artifact_valid'])

        # A fresh request discovering the one existing bound record is fine.
        replay = self.restock()
        replay['binding_units'][0]['attempt_id'] = 'a-fresh-request'
        self.assertEqual('already_bound', evaluate(replay)['unit_results'][0]['reason'])

    def test_effective_count_cannot_exceed_accepted_binding_units(self):
        """A count larger than the accepted scope is impossible producer output."""
        accepted = len(self.fixture(12)['term_artifact']['binding_authorization']['groups'])
        self.assertEqual(4, accepted)
        for count in (999, accepted + 1):
            with self.subTest(effective_unit_count=count):
                # Cite a historical trigger rather than the current transition,
                # so only the scope bound can reject this record.
                v = self.restock()
                # `tier-attempt-1` bound L02, so the trigger-membership rules
                # accept it for an L01 adjustment; only the scope bound rejects
                # a count the artifact cannot contain.
                v['business_state']['commercial_basis_adjustments'] = [
                    self.applied_adjustment(1200, 1000, count=count,
                                            attempt='tier-attempt-1')]
                result = evaluate(v)
                self.assertEqual('invalid_artifact_semantics', result['reason'])
                self.assertFalse(result['artifact_valid'])
        # The largest legitimate count still succeeds.
        valid = self.restock()
        valid['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, count=accepted)]
        self.assertEqual('bound', evaluate(valid)['outcome'])

    def test_effective_count_cannot_decrease_over_append_only_history(self):
        """No unbind is modelled, so the bound-unit count never goes down."""
        rising = self.sequential_tier_history()
        counts = [a['effective_unit_count']
                  for a in rising['business_state']['commercial_basis_adjustments']]
        self.assertEqual([2, 4, 4, 4], counts)
        # 2 -> 4 is valid, and several records may share one count-4 transition.
        self.assertEqual('bound', evaluate(rising)['outcome'])

        # Lower the FIRST record's count below its successor's while keeping
        # every record a real, correctly tiered, correctly chained transition.
        # Only the ordering of the recorded counts is impossible.
        falling = self.sequential_tier_history()
        records = falling['business_state']['commercial_basis_adjustments']
        first, rest = records[0], records[1:]
        self.assertEqual(2, first['effective_unit_count'])
        falling['business_state']['commercial_basis_adjustments'] = rest + [first]
        # Re-chain L01 so the price links still hold in the new order.
        for record in falling['business_state']['commercial_basis_adjustments']:
            if record['line_id'] == 'L01' and record['tier_minimum_units'] == 4:
                record['previous_unit_price'] = 1200
        first['previous_unit_price'] = 1000
        first.update(new_unit_price=1100)
        self.assertEqual('invalid_artifact_semantics', evaluate(falling)['reason'])

    def test_one_transition_context_per_triggering_attempt(self):
        """A single trigger cannot claim two different counts or tiers."""
        v = self.sequential_tier_history()
        for record in v['business_state']['commercial_basis_adjustments']:
            if record['tier_minimum_units'] == 2:
                # Re-point the count-2/tier-2 record at the count-4 transition.
                record['triggering_attempt_id'] = 'seq-3-U4'
        self.assertEqual('invalid_artifact_semantics', evaluate(v)['reason'])

    def test_one_effective_count_identifies_one_triggering_attempt(self):
        """The converse of the per-trigger rule, across records.

        One adjustment-producing evaluation computes a single effective count and
        picks a single triggering attempt, so two different real triggers cannot
        both claim the same count. Every other property of these records is
        individually valid, so only the cross-record invariant can reject them.
        """
        v = self.restock()
        historical = [h['attempt_id'] for h in v['business_state']['attempt_history']
                      if h['reason'] == 'bound']
        other_trigger = historical[2]
        self.assertNotEqual('fresh-U4-after-restock', other_trigger)
        records = [
            self.applied_adjustment(1200, 1000, line='L01',
                                    attempt='fresh-U4-after-restock', tier=4, count=4),
            self.applied_adjustment(1200, 1000, line='L02',
                                    attempt=other_trigger, tier=4, count=4),
        ]
        # Each record is independently well formed: real trigger, accepted tier,
        # that tier's price, a count that selects it, and a valid chain link.
        for record in records:
            self.assertIn(record['triggering_attempt_id'],
                          historical + ['fresh-U4-after-restock'])
            self.assertEqual(4, record['tier_minimum_units'])
            self.assertEqual(1000, record['new_unit_price'])
        v['business_state']['commercial_basis_adjustments'] = records
        result = evaluate(v)
        self.assertEqual('invalid_artifact_semantics', result['reason'])
        self.assertFalse(result['artifact_valid'])

        # Sharing one trigger for that count is the legitimate shape.
        agreed = self.restock()
        agreed['business_state']['commercial_basis_adjustments'] = [
            dict(record, triggering_attempt_id='fresh-U4-after-restock')
            for record in records]
        self.assertEqual('bound', evaluate(agreed)['outcome'])

    def test_transition_counts_need_not_be_contiguous(self):
        """An evaluation may jump counts; only the recorded pairs must cohere."""
        v = self.restock()
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(1200, 1000, line='L01',
                                    attempt='fresh-U4-after-restock', tier=4, count=4)]
        # No count 2 or 3 record exists, and that is fine.
        self.assertEqual('bound', evaluate(v)['outcome'])

    def test_same_identity_requires_matching_transition_context(self):
        """False provenance is rejected even when tier and price are unchanged.

        Counts 2 and 3 both select the 2-unit tier, so the economic effect is
        identical; the persisted record must still describe the transition
        actually being replayed.
        """
        honest = self.two_unit_tier_history()
        self.assertEqual('partially_bound', evaluate(honest)['outcome'])
        self.assertNotIn('adjustments', evaluate(honest))

        false_provenance = self.two_unit_tier_history(persisted_count=3)
        recorded = [a for a in false_provenance['business_state']['commercial_basis_adjustments']
                    if a['effective_unit_count'] == 3]
        self.assertTrue(recorded)
        self.assertEqual(2, recorded[0]['tier_minimum_units'])
        self.assertEqual('invalid_artifact_semantics', evaluate(false_provenance)['reason'])

    def test_recorded_tier_must_be_reachable_from_its_transition_context(self):
        request = self.sequential_tier_history()
        self.assertEqual('bound', evaluate(request)['outcome'])
        # A context that cannot reach the recorded tier.
        low = self.sequential_tier_history()
        for record in low['business_state']['commercial_basis_adjustments']:
            if record['tier_minimum_units'] == 4:
                record['effective_unit_count'] = 1
        self.assertEqual('invalid_artifact_semantics', evaluate(low)['reason'])
        # A context that reaches a higher tier than the one recorded.
        high = self.sequential_tier_history()
        for record in high['business_state']['commercial_basis_adjustments']:
            if record['tier_minimum_units'] == 2:
                record['effective_unit_count'] = 4
        self.assertEqual('invalid_artifact_semantics', evaluate(high)['reason'])

    def test_incompatible_trigger_repointing_is_detected(self):
        """Membership and target provenance catch most re-pointing.

        A trigger that bound the very line being adjusted, or that disagrees with
        the count-to-trigger map, is impossible on retained facts alone.
        """
        # The L01 tier-4 record cannot cite the attempt that bound L01.
        self_citing = self.sequential_tier_history()
        for record in self_citing['business_state']['commercial_basis_adjustments']:
            if record['tier_minimum_units'] == 4 and record['line_id'] == 'L01':
                record['triggering_attempt_id'] = 'seq-0-U1'
        self.assertEqual('invalid_artifact_semantics', evaluate(self_citing)['reason'])
        # Moving every count-4 record to another trigger is equally impossible,
        # because one of them then cites the attempt that bound its own line.
        for candidate in ('seq-0-U1', 'seq-1-U2', 'seq-2-U3'):
            with self.subTest(trigger=candidate):
                moved = self.sequential_tier_history()
                for record in moved['business_state']['commercial_basis_adjustments']:
                    if record['effective_unit_count'] == 4:
                        record['triggering_attempt_id'] = candidate
                self.assertEqual('invalid_artifact_semantics', evaluate(moved)['reason'])

    def test_compatible_trigger_repointing_remains_unprovable(self):
        """CHARACTERIZATION of the residual limit, not a guarantee.

        The count-2 record adjusts L01 and legitimately cites the U2 attempt.
        Re-pointing it to the U3 attempt stays compatible with every retained
        fact: U3 is a real bound attempt for an accepted unit of this artifact
        and transaction, it does not contain L01, and no other record claims
        count 2. Only the historical ordering between that attempt and the
        transition would expose it, and ordering is not retained. Modelling it
        would legitimately make this detectable; tightening is an improvement.
        """
        request = self.sequential_tier_history()
        original = [r['triggering_attempt_id']
                    for r in request['business_state']['commercial_basis_adjustments']
                    if r['effective_unit_count'] == 2]
        self.assertEqual(['seq-1-U2'], original)
        for record in request['business_state']['commercial_basis_adjustments']:
            if record['effective_unit_count'] == 2:
                record['triggering_attempt_id'] = 'seq-2-U3'
        self.assertEqual('bound', evaluate(request)['outcome'])

    def test_unrecognised_authorization_source_is_rejected_semantically(self):
        """Not only by the schema: semantic evaluation rejects it too."""
        validator = Draft7Validator(load_json(SCHEMA_PATH)['definitions']['adjustmentRecord'])
        hostile = dict(self.applied_adjustment(1200, 1000),
                       authorization_source='made_up_authority')
        self.assertFalse(validator.is_valid(hostile))
        v = self.restock()
        v['business_state']['commercial_basis_adjustments'] = [hostile]
        result = evaluate(v)
        self.assertEqual('invalid_artifact_semantics', result['reason'])
        self.assertFalse(result['artifact_valid'])

    def test_persisted_adjustment_must_cite_a_real_tier_row_and_attempt(self):
        """Structural linkage is not proof of authorized producer output."""
        cases = (
            ('ghost trigger and nonexistent tier row',
             dict(self.applied_adjustment(1200, 1000),
                  triggering_attempt_id='ghost-attempt', tier_minimum_units=999)),
            ('real tier row, price it does not authorize',
             self.applied_adjustment(1200, 1050)),
            ('nonexistent tier row, otherwise correct price',
             dict(self.applied_adjustment(1200, 1000), tier_minimum_units=999)),
            ('real tier row citing a different row\'s price',
             dict(self.applied_adjustment(1200, 1000), tier_minimum_units=1)),
            ('real tier and effect, trigger that never happened',
             dict(self.applied_adjustment(1200, 1000),
                  triggering_attempt_id='never-happened')),
        )
        for label, record in cases:
            with self.subTest(record=label):
                v = self.restock()
                v['business_state']['commercial_basis_adjustments'] = [record]
                result = evaluate(v)
                self.assertEqual('invalid_artifact_semantics', result['reason'])
                self.assertFalse(result['artifact_valid'])

    def test_authorized_historical_adjustments_still_succeed(self):
        first = evaluate(self.restock())
        persisted = [dict(artifact_id='award-10001', **a) for a in first['adjustments']]
        # Full persistence.
        full = self.restock()
        full['business_state']['commercial_basis_adjustments'] = persisted
        self.assertEqual('bound', evaluate(full)['outcome'])
        self.assertNotIn('adjustments', evaluate(full))
        # Partial persistence: only some lines recorded before an interruption.
        partial = self.restock()
        partial['business_state']['commercial_basis_adjustments'] = [persisted[0]]
        self.assertEqual('bound', evaluate(partial)['outcome'])
        # A multi-step chain whose triggers are historical bound attempts.
        self.assertEqual('bound', evaluate(self.sequential_tier_history())['outcome'])

    def test_duplicate_identity_detected_independently_of_effect(self):
        """Isolates duplicate-identity detection from the canonical-effect check.

        Both records carry the canonical 1200->1000 effect, so the effect check
        alone would accept them; recording one transition identity twice is still
        contradictory append-only history.
        """
        v = self.restock()
        canonical = self.applied_adjustment(1200, 1000)
        v['business_state']['commercial_basis_adjustments'] = [canonical, dict(canonical)]
        self.assertEqual('invalid_artifact_semantics', evaluate(v)['reason'])

    def test_same_identity_with_same_effect_replays(self):
        """The legitimate replay path still succeeds and emits no duplicate."""
        v = self.restock()
        first = evaluate(v)
        self.assertEqual(3, len(first['adjustments']))
        v['business_state']['commercial_basis_adjustments'] = [
            dict(artifact_id='award-10001', **adjustment) for adjustment in first['adjustments']]
        replay = evaluate(v)
        self.assertEqual('bound', replay['outcome'])
        self.assertNotIn('adjustments', replay)
        self.assertTrue(all(price == 1000 for price in replay['effective_unit_prices'].values()))

    def test_adjustment_history_is_scoped_by_revision(self):
        """A record from another revision belongs to a different chain."""
        state = {'commercial_basis_adjustments': [self.applied_adjustment(1200, 1000)]}
        # Revision 5 bind-time basis is untouched by the revision-4 record.
        self.assertEqual({'L01': 1300},
                         current_commercial_basis(state, 'award-10001', 5, {'L01': 1300}))
        # The same record still governs its own revision.
        self.assertEqual({'L01': 1000},
                         current_commercial_basis(state, 'award-10001', 4, {'L01': 1200}))

    def test_other_revision_history_does_not_block_current_evaluation(self):
        v = self.restock()
        v['business_state']['commercial_basis_adjustments'] = [
            self.applied_adjustment(999, 1, revision=3)]
        result = evaluate(v)
        # The stale-revision record neither invalidates nor suppresses anything.
        self.assertEqual('bound', result['outcome'])
        self.assertEqual(3, len(result['adjustments']))

    def test_emitted_adjustments_carry_full_persistable_identity(self):
        validator = Draft7Validator(load_json(SCHEMA_PATH), format_checker=FormatChecker())
        adjustment_schema = load_json(SCHEMA_PATH)['definitions']['adjustment']
        for adjustment in evaluate(self.restock())['adjustments']:
            with self.subTest(line=adjustment['line_id']):
                for field in ('triggering_attempt_id', 'tier_minimum_units', 'revision'):
                    self.assertIn(field, adjustment)
                self.assertTrue(Draft7Validator(adjustment_schema).is_valid(adjustment))
        # An adjustment missing identity metadata is no longer schema-valid.
        for field in ('triggering_attempt_id', 'tier_minimum_units', 'revision'):
            incomplete = dict(evaluate(self.restock())['adjustments'][0])
            del incomplete[field]
            with self.subTest(missing=field):
                self.assertFalse(Draft7Validator(adjustment_schema).is_valid(incomplete))
        # The producer minimum is expressed statically in the schema as well.
        below_minimum = dict(evaluate(self.restock())['adjustments'][0],
                             effective_unit_count=1)
        self.assertFalse(Draft7Validator(adjustment_schema).is_valid(below_minimum))
        self.assertIsNotNone(validator)

    def test_reserved_lifecycle_reasons_cannot_be_invalidation_conditions(self):
        """Declared conditions must not collide with the lifecycle namespace."""
        validator = Draft7Validator(load_json(SCHEMA_PATH), format_checker=FormatChecker())
        for reserved in sorted(RESERVED_LIFECYCLE_REASONS):
            with self.subTest(condition=reserved):
                v = self.fixture(8)
                v['post_bind']['terminal_outcome'] = None
                v['post_bind']['governing_semantics']['execution_invalidation_conditions'] = [reserved]
                v['post_bind']['execution_attempt'].update(
                    at='2026-09-12T12:00:00Z', active_invalidation_conditions=[reserved])
                # Rejected by the schema...
                self.assertFalse(validator.is_valid(v))
                # ...and semantically, so bypassing the schema changes nothing:
                # the result is never a replayable terminal record.
                # Whatever first-time evaluation returns, it is never usable as
                # terminal history under that reserved name, so a rejection can
                # never round-trip into the reserved class's own meaning.
                result = evaluate_post_bind(v)
                record = persistable_terminal_outcome(v, result, '2026-09-12T11:00:00Z')
                self.assertIsNone(record)
                # A reserved name is never read as a declared invalidation:
                # replay either rejects it, or resolves it through the reserved
                # class's own branch, never as post_bind_invalidated/<name>.
                record = dict(applied_at='2026-09-12T11:00:00Z',
                              status='post_bind_invalidated', reason=reserved,
                              executed=False, terms_preserved=True)
                policy = v['post_bind']['governing_semantics']  # noqa: F841
                authorized = replayable_terminal_outcome(
                    policy, record, instant(policy['post_bind_valid_until']),
                    instant('2026-09-12T11:00:00Z'), instant(v['post_bind']['bound_at']))
                # Either rejected outright, or resolved by the reserved class's
                # own branch; never accepted because the policy "declared" it.
                if authorized is not None:
                    self.assertNotIn(reserved, TRANSIENT_LIFECYCLE_FAILURES)
                    self.assertEqual(
                        authorized,
                        replayable_terminal_outcome(
                            dict(policy, execution_invalidation_conditions=[]),
                            record, instant(policy['post_bind_valid_until']),
                            instant('2026-09-12T11:00:00Z'),
                            instant(v['post_bind']['bound_at'])))

    def test_invalid_reserved_name_policy_authorizes_no_terminal_class(self):
        """Policy-level guard: an invalid policy authorizes nothing at all.

        Replay must reject every historical class under a policy whose declared
        conditions collide with the lifecycle namespace, not just the colliding
        name, matching how first-time evaluation rejects the same policy.
        """
        canonical = dict(applied_at='2026-09-12T11:00:00Z', status='executed',
                         reason='executed', executed=True, terms_preserved=True)
        for reserved in sorted(RESERVED_LIFECYCLE_REASONS):
            with self.subTest(declared=reserved):
                v = self.fixture(8)
                v['post_bind']['governing_semantics'][
                    'execution_invalidation_conditions'] = [reserved]
                v['post_bind']['execution_attempt'].update(
                    at='2026-09-12T12:00:00Z', active_invalidation_conditions=[])
                v['post_bind']['terminal_outcome'] = dict(canonical)
                # An otherwise canonical ordinary execution must not replay.
                self.assertTerminalConflict(v)

    def test_invalid_reserved_name_policy_blocks_every_record_class(self):
        """The guard is policy-level, not specific to any one reason."""
        records = (
            dict(applied_at='2026-09-12T11:00:00Z', status='executed',
                 reason='executed', executed=True, terms_preserved=True),
            dict(applied_at='2026-09-16T00:00:00Z', status='post_bind_invalidated',
                 reason='execution_deadline_elapsed', executed=False, terms_preserved=True),
            dict(applied_at='2026-09-12T11:00:00Z', status='post_bind_invalidated',
                 reason='commercial_terms_reinterpreted', executed=False,
                 terms_preserved=False),
        )
        for record in records:
            with self.subTest(reason=record['reason']):
                v = self.fixture(8)
                v['post_bind']['governing_semantics'][
                    'execution_invalidation_conditions'] = ['executed']
                v['post_bind']['execution_attempt'].update(
                    at='2026-09-17T00:00:00Z', active_invalidation_conditions=[])
                v['post_bind']['terminal_outcome'] = dict(record)
                self.assertTerminalConflict(v)

    def test_terminal_timing_boundaries_agree_between_producer_and_replay(self):
        """`bound_at` is inclusive on both sides; pre-bind and the deadline are not."""
        bound = '2026-09-12T10:00:00Z'
        v = self.fixture(9)
        self.assertEqual(bound, v['post_bind']['bound_at'])

        # A release event exactly at bound_at is valid: only PRE-bind rejects.
        at_bound = self.fixture(9)
        at_bound['post_bind']['terminal_outcome'] = None
        at_bound['post_bind']['execution_attempt'].update(
            at='2026-09-12T17:00:00Z', release_condition_met=True, release_resolved_at=bound)
        first = evaluate_post_bind(at_bound)
        self.assertEqual('release_condition_satisfied', first['reason'])
        record = persistable_terminal_outcome(at_bound, first, bound)
        self.assertIsNotNone(record)
        at_bound['post_bind']['terminal_outcome'] = record
        self.assertEqual(first, evaluate_post_bind(at_bound))

        # Immediately before bound_at is rejected on both sides.
        pre_bind = self.release_record(
            'release_condition_satisfied', True, 'executed',
            resolved='2026-09-12T09:59:59Z', applied='2026-09-12T11:00:00Z', executed=True)
        self.assertTerminalConflict(pre_bind)

        # A release outcome applied exactly at the governing deadline is
        # rejected, since the deadline is exclusive.
        self.assertEqual('transaction_lifetime',
                         v['post_bind']['governing_semantics']['deadline_source'])
        deadline = v['post_bind']['transaction']['valid_until']
        at_deadline = self.release_record(
            'release_condition_satisfied', True, 'executed',
            resolved='2026-09-12T12:00:00Z', applied=deadline, executed=True)
        at_deadline['post_bind']['execution_attempt']['at'] = '2026-09-21T00:00:00Z'
        self.assertTerminalConflict(at_deadline)
        # One second earlier is inside the window and replays.
        inside = self.release_record(
            'release_condition_satisfied', True, 'executed',
            resolved='2026-09-12T12:00:00Z', applied='2026-09-19T23:59:59Z', executed=True)
        inside['post_bind']['execution_attempt']['at'] = '2026-09-21T00:00:00Z'
        self.assertEqual('release_condition_satisfied', evaluate_post_bind(inside)['reason'])

        # A deadline disposition is valid at the deadline and rejected before it.
        v13 = self.fixture(13)
        self.assertEqual('2026-09-20T00:00:00Z',
                         v13['post_bind']['terminal_outcome']['applied_at'])
        self.assertEqual('return_to_buyer', evaluate_post_bind(v13)['reason'])
        early = self.fixture(13)
        early['post_bind']['terminal_outcome']['applied_at'] = '2026-09-19T23:59:59Z'
        self.assertEqual('invalid_lifecycle_timing', evaluate_post_bind(early)['reason'])

    def test_ordinary_invalidation_condition_names_remain_valid(self):
        validator = Draft7Validator(load_json(SCHEMA_PATH), format_checker=FormatChecker())
        for condition in ('inventory_allocation_changed', 'fraud_confirmed',
                          'supplier_withdrew'):
            with self.subTest(condition=condition):
                v = self.fixture(8)
                v['post_bind']['terminal_outcome'] = None
                v['post_bind']['governing_semantics']['execution_invalidation_conditions'] = [condition]
                v['post_bind']['execution_attempt'].update(
                    at='2026-09-12T12:00:00Z', active_invalidation_conditions=[condition])
                self.assertTrue(validator.is_valid(v))
                first = evaluate_post_bind(v)
                self.assertEqual(condition, first['reason'])
                # And it round-trips as legitimate terminal history.
                record = persistable_terminal_outcome(v, first, '2026-09-12T11:00:00Z')
                self.assertIsNotNone(record)
                v['post_bind']['terminal_outcome'] = record
                self.assertEqual(first, evaluate_post_bind(v))

    def test_broken_chain_present_is_structural_invalidity(self):
        self.assertStructurallyInvalid(self.restock_with_adjustments(
            self.adjustment(999, 1000, 'fresh-U4-after-restock', 4)))

    def test_reordered_chain_present_is_structural_invalidity(self):
        chain = [self.adjustment(1200, 1100, 'a1', 2), self.adjustment(1100, 1000, 'a2', 4)]
        self.assertStructurallyInvalid(self.restock_with_adjustments(*reversed(chain)))

    def test_contradictory_running_basis_is_structural_invalidity(self):
        # Second entry's previous basis contradicts the first entry's new basis.
        self.assertStructurallyInvalid(self.restock_with_adjustments(
            self.adjustment(1200, 1100, 'a1', 2), self.adjustment(1150, 1000, 'a2', 4)))

    def test_duplicate_conflicting_entries_are_structural_invalidity(self):
        # Replaying the same transition twice cannot chain from the new basis.
        applied = self.adjustment(1200, 1000, 'fresh-U4-after-restock', 4)
        self.assertStructurallyInvalid(self.restock_with_adjustments(applied, dict(applied)))

    def test_inaccessible_history_remains_retryable(self):
        v = self.restock_with_adjustments()
        v['business_state']['commercial_basis_history_available'] = False
        result = evaluate(v)
        self.assertEqual('commercial_basis_history_unavailable', result['reason'])
        self.assertTrue(result['artifact_valid'])
        self.assertEqual('recognized_rejected', result['outcome'])
        self.assertEqual('same_attempt_later', result['recovery_action'])

    def test_empty_but_valid_history_succeeds(self):
        result = evaluate(self.restock_with_adjustments())
        self.assertEqual('bound', result['outcome'])
        self.assertEqual(3, len(result['adjustments']))

    def test_present_valid_chain_replays_without_new_adjustments(self):
        v = self.restock_with_adjustments()
        first = evaluate(v)
        self.persist(v, first)
        replay = evaluate(v)
        self.assertEqual('bound', replay['outcome'])
        self.assertNotIn('adjustments', replay)

    def test_applied_adjustment_recognized_through_canonical_identity(self):
        v = self.v12_history()
        v['binding_units'][3]['attempt_id'] = 'fresh-U4-after-restock'
        v['binding_units'][3]['unavailable_line_ids'] = []
        first = evaluate(v)
        self.assertEqual(3, len(first['adjustments']))
        # Every emitted adjustment carries the full canonical identity.
        for emitted in first['adjustments']:
            record = dict(artifact_id=v['term_artifact']['id'], **emitted)
            self.assertEqual(
                (v['term_artifact']['id'], emitted['line_id'], 'fresh-U4-after-restock', 4, 4),
                adjustment_identity(record))
        self.persist(v, first)
        applied = copy.deepcopy(v['business_state']['commercial_basis_adjustments'])
        replay = evaluate(v)
        # Recognized through that identity: not emitted again...
        self.assertNotIn('adjustments', replay)
        self.persist(v, replay)
        # ...and not persisted again.
        self.assertEqual(applied, v['business_state']['commercial_basis_adjustments'])

    def test_unsupported_transition_still_fails_closed(self):
        v = self.v12_history()
        v['business_state']['attempt_history'][0]['effective_unit_prices']['L01'] = 1300
        v['binding_units'][3]['attempt_id'] = 'fresh-U4-after-restock'
        v['binding_units'][3]['unavailable_line_ids'] = []
        self.assertEqual('prior_bound_adjustment_requires_transition', evaluate(v)['reason'])

    def test_contradictory_terminal_outcome_takes_correction_path(self):
        v = self.fixture(13)
        self.assertEqual('return_to_buyer',
                         v['post_bind']['governing_semantics']['pending_at_deadline'])
        v['post_bind']['terminal_outcome'].update(
            status='executed', reason='deemed_acceptance_to_business', executed=True)
        result = evaluate_post_bind(v)
        # Existing non-success status; no new lifecycle status is introduced.
        self.assertEqual('post_bind_invalidated', result['status'])
        self.assertEqual('terminal_outcome_conflicts_with_accepted_disposition', result['reason'])
        # The contradictory persisted outcome is not replayed.
        self.assertNotEqual('deemed_acceptance_to_business', result['reason'])
        self.assertFalse(result['executed'])
        self.assertFalse(result['terms_preserved'])
        # Distinct from the no-evidence case, which still yields the disposition.
        missing = self.fixture(13)
        missing['post_bind']['terminal_outcome'] = None
        self.assertEqual('return_to_buyer', evaluate_post_bind(missing)['reason'])
        self.assertNotEqual(evaluate_post_bind(missing)['reason'], result['reason'])
        # No in-harness correction status exists.
        self.assertNotIn('correction', result['status'])

    CONFLICT = 'terminal_outcome_conflicts_with_accepted_disposition'

    def assertTerminalConflict(self, vector):
        result = evaluate_post_bind(vector)
        self.assertEqual('post_bind_invalidated', result['status'])
        self.assertEqual(self.CONFLICT, result['reason'])
        self.assertFalse(result['executed'])
        self.assertFalse(result['terms_preserved'])
        return result

    def test_return_to_buyer_relabeled_as_executed_conflicts(self):
        v = self.fixture(13)
        # Keep the authorized reason but claim it executed.
        v['post_bind']['terminal_outcome'].update(status='executed', executed=True)
        self.assertEqual('return_to_buyer', v['post_bind']['terminal_outcome']['reason'])
        self.assertTerminalConflict(v)

    def test_release_condition_satisfied_without_evidence_conflicts(self):
        v = self.fixture(13)
        self.assertIsNone(v['post_bind']['execution_attempt']['release_resolved_at'])
        v['post_bind']['terminal_outcome'].update(
            status='executed', reason='release_condition_satisfied', executed=True)
        # Must not bypass validation just by sitting outside the deadline set.
        self.assertTerminalConflict(v)

    def test_no_authorized_disposition_rejects_persisted_deadline_outcome(self):
        v = self.fixture(8)
        self.assertIsNone(v['post_bind']['governing_semantics']['release_condition'])
        v['post_bind']['execution_attempt'].update(
            at='2026-09-14T00:00:00Z', active_invalidation_conditions=[])
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-14T00:00:00Z', status='executed',
            reason='deemed_acceptance_to_business', executed=True, terms_preserved=True)
        # authorized_deadline_disposition() is None here; that is not "accept anything".
        self.assertTerminalConflict(v)

    def test_terms_preserved_mutation_conflicts(self):
        v = self.fixture(13)
        v['post_bind']['terminal_outcome']['terms_preserved'] = False
        self.assertTerminalConflict(v)

    def test_correct_reason_wrong_status_only_conflicts(self):
        v = self.fixture(13)
        v['post_bind']['terminal_outcome']['status'] = 'executed'
        self.assertTerminalConflict(v)

    def test_correct_reason_and_status_wrong_executed_only_conflicts(self):
        v = self.fixture(13)
        v['post_bind']['terminal_outcome']['executed'] = True
        self.assertTerminalConflict(v)

    def test_unsupported_persisted_reason_cannot_bypass_authorization(self):
        v = self.fixture(13)
        v['post_bind']['terminal_outcome'].update(
            status='executed', reason='unsupported_disposition', executed=True)
        self.assertTerminalConflict(v)

    def test_deemed_acceptance_inconsistent_fields_conflict(self):
        for field, value in (('status', 'deadline_non_execution'),
                             ('executed', False), ('terms_preserved', False)):
            v = self.fixture(13)
            v['post_bind']['governing_semantics']['pending_at_deadline'] = 'deemed_acceptance_to_business'
            v['post_bind']['terminal_outcome'].update(
                status='executed', reason='deemed_acceptance_to_business', executed=True)
            v['post_bind']['terminal_outcome'][field] = value
            with self.subTest(field=field):
                self.assertTerminalConflict(v)

    def test_every_single_field_mutation_conflicts(self):
        """No single semantic field may be altered and still replay."""
        mutations = {
            'status': ('executed', 'release_pending', 'post_bind_invalidated'),
            'reason': ('deemed_acceptance_to_business', 'release_condition_satisfied'),
            'executed': (True,),
            'terms_preserved': (False,),
        }
        for field, values in mutations.items():
            for value in values:
                v = self.fixture(13)
                if v['post_bind']['terminal_outcome'][field] == value:
                    continue
                v['post_bind']['terminal_outcome'][field] = value
                with self.subTest(field=field, value=value):
                    self.assertTerminalConflict(v)

    def test_timing_validation_is_not_bypassed_by_semantic_validation(self):
        for applied, expected in (('2026-09-19T00:00:00Z', 'invalid_lifecycle_timing'),
                                  ('2026-09-11T00:00:00Z', 'invalid_lifecycle_timing'),
                                  ('2026-10-01T00:00:00Z', 'invalid_lifecycle_timing')):
            v = self.fixture(13)
            v['post_bind']['terminal_outcome']['applied_at'] = applied
            with self.subTest(applied_at=applied):
                self.assertEqual(expected, evaluate_post_bind(v)['reason'])

    def test_evidence_disappearance_does_not_permit_replay(self):
        v = self.fixture(9)
        attempt = v['post_bind']['execution_attempt']
        v['post_bind']['terminal_outcome'] = dict(
            applied_at=attempt['at'], status='executed',
            reason='release_condition_satisfied', executed=True, terms_preserved=True)
        attempt.update(release_condition_met=None, release_resolved_at=None)
        self.assertTerminalConflict(v)

    def test_valid_terminal_outcomes_replay_unchanged(self):
        self.assertEqual(
            {'status': 'deadline_non_execution', 'reason': 'return_to_buyer',
             'executed': False, 'terms_preserved': True},
            evaluate_post_bind(self.fixture(13)))
        business = self.fixture(13)
        business['post_bind']['governing_semantics']['pending_at_deadline'] = 'deemed_acceptance_to_business'
        business['post_bind']['terminal_outcome'].update(
            status='executed', reason='deemed_acceptance_to_business', executed=True)
        self.assertEqual(
            {'status': 'executed', 'reason': 'deemed_acceptance_to_business',
             'executed': True, 'terms_preserved': True},
            evaluate_post_bind(business))

    # Independent oracle: canonical terminal shapes written out by hand, NOT
    # derived from semantics.py, so a regression in the implementation's own
    # canonical mapping cannot silently redefine what the tests expect.
    CANONICAL_SHAPES = {
        'return_to_buyer': ('deadline_non_execution', False, True),
        'deemed_acceptance_to_business': ('executed', True, True),
        'release_condition_satisfied': ('executed', True, True),
        'release_condition_failed': ('release_condition_failed', False, True),
        'executed': ('executed', True, True),
    }

    def test_terminal_mutation_matrix_admits_only_canonical_records(self):
        """Exhaustive mutation matrix over the persisted semantic fields.

        Only a record equal to the independently specified canonical shape of the
        disposition the accepted policy authorizes may replay. Everything else
        must conflict. This is the durable form of the adversarial sweep.
        """
        statuses = ('deadline_non_execution', 'executed', 'release_pending',
                    'release_condition_failed', 'post_bind_invalidated')
        reasons = ('return_to_buyer', 'deemed_acceptance_to_business',
                   'release_condition_satisfied', 'executed', 'unsupported_reason')
        applied_at = '2026-09-21T00:00:00Z'
        checked = replayed = 0
        for policy_disposition in ('return_to_buyer', 'deemed_acceptance_to_business'):
            for status, reason, executed, preserved in itertools.product(
                    statuses, reasons, (True, False), (True, False)):
                v = self.fixture(13)
                v['post_bind']['governing_semantics']['pending_at_deadline'] = policy_disposition
                v['post_bind']['execution_attempt'].update(
                    at=applied_at, release_condition_met=None, release_resolved_at=None)
                v['post_bind']['terminal_outcome'] = dict(
                    applied_at=applied_at, status=status, reason=reason,
                    executed=executed, terms_preserved=preserved)
                # Oracle: authorized only when the record is the canonical shape
                # of the policy's own disposition.
                authorized = (reason == policy_disposition
                              and self.CANONICAL_SHAPES[reason] == (status, executed, preserved))
                result = evaluate_post_bind(v)
                checked += 1
                with self.subTest(policy=policy_disposition, status=status,
                                  reason=reason, executed=executed, preserved=preserved):
                    if authorized:
                        replayed += 1
                        self.assertEqual(reason, result['reason'])
                        self.assertEqual(status, result['status'])
                        self.assertEqual(executed, result['executed'])
                        self.assertEqual(preserved, result['terms_preserved'])
                    else:
                        self.assertEqual(self.CONFLICT, result['reason'])
                        self.assertEqual('post_bind_invalidated', result['status'])
        self.assertEqual(200, checked)
        # Exactly one canonical record per authorized disposition.
        self.assertEqual(2, replayed)

    def test_persisted_release_outcome_cannot_predate_its_evidence(self):
        """Evidence resolving after `applied_at` cannot authorize the record."""
        for reason, met, status in (('release_condition_satisfied', True, 'executed'),
                                    ('release_condition_failed', False, 'release_condition_failed')):
            with self.subTest(reason=reason):
                late = self.release_record(reason, met, status,
                                           resolved='2026-09-12T17:00:00Z',
                                           applied='2026-09-12T13:00:00Z')
                self.assertTerminalConflict(late)
                # Evidence available before application still replays.
                timely = self.release_record(reason, met, status,
                                             resolved='2026-09-12T13:00:00Z',
                                             applied='2026-09-12T14:00:00Z')
                self.assertEqual(reason, evaluate_post_bind(timely)['reason'])

    def release_record(self, reason, met, status, resolved, applied,
                       executed=None, preserved=True, basis='derive'):
        """Build a V9 release replay case.

        `basis` is the persisted historical authorization. 'derive' records the
        result/event the outcome was produced from; None omits provenance
        entirely; a dict supplies a hostile or contradictory basis verbatim.
        """
        v = self.fixture(9)
        post = v['post_bind']
        post['execution_attempt'].update(
            at='2026-09-12T18:00:00Z', release_condition_met=met, release_resolved_at=resolved)
        terminal = dict(
            applied_at=applied, status=status, reason=reason,
            executed=met if executed is None else executed, terms_preserved=preserved)
        if basis == 'derive':
            # Provenance recorded at application: the result this class claims,
            # with the cited event time.
            basis = dict(condition_met=(reason == 'release_condition_satisfied'),
                         resolved_at=resolved) if resolved is not None else None
        if basis is not None:
            terminal['release_authorization_basis'] = basis
        post['terminal_outcome'] = terminal
        return v

    def test_release_resolution_at_deadline_cannot_authorize_release_outcome(self):
        v = self.fixture(9)
        deadline = v['term_artifact']['expires_at']
        v['post_bind']['governing_semantics']['deadline_source'] = 'term_expiry'
        v['post_bind']['execution_attempt'].update(
            at=deadline, release_condition_met=True, release_resolved_at=deadline)
        v['post_bind']['terminal_outcome'] = dict(
            applied_at=deadline, status='executed', reason='release_condition_satisfied',
            executed=True, terms_preserved=True)
        # The deadline is exclusive, so resolution exactly at it is too late.
        self.assertTerminalConflict(v)

    def test_release_condition_failed_validates_symmetrically(self):
        canonical = self.release_record('release_condition_failed', False,
                                        'release_condition_failed',
                                        resolved='2026-09-12T13:00:00Z',
                                        applied='2026-09-12T14:00:00Z')
        self.assertEqual('release_condition_failed', evaluate_post_bind(canonical)['reason'])
        # Missing evidence, opposite evidence, and each field mutation must conflict.
        self.assertTerminalConflict(self.release_record(
            'release_condition_failed', None, 'release_condition_failed',
            resolved=None, applied='2026-09-12T14:00:00Z'))
        self.assertTerminalConflict(self.release_record(
            'release_condition_failed', True, 'release_condition_failed',
            resolved='2026-09-12T13:00:00Z', applied='2026-09-12T14:00:00Z'))
        for field, value in (('status', 'executed'), ('executed', True),
                             ('terms_preserved', False)):
            v = self.release_record('release_condition_failed', False,
                                    'release_condition_failed',
                                    resolved='2026-09-12T13:00:00Z',
                                    applied='2026-09-12T14:00:00Z')
            v['post_bind']['terminal_outcome'][field] = value
            with self.subTest(field=field):
                self.assertTerminalConflict(v)

    def test_ordinary_execution_without_release_condition(self):
        """No release condition: only a pre-deadline plain execution is authorized."""
        v = self.fixture(8)
        self.assertIsNone(v['post_bind']['governing_semantics']['release_condition'])
        v['post_bind']['execution_attempt'].update(
            at='2026-09-12T12:00:00Z', active_invalidation_conditions=[])
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-12T11:00:00Z', status='executed', reason='executed',
            executed=True, terms_preserved=True)
        self.assertEqual('executed', evaluate_post_bind(v)['reason'])

        for applied in ('2026-09-15T00:00:00Z', '2026-09-16T00:00:00Z'):
            late = self.fixture(8)
            late['post_bind']['execution_attempt'].update(
                at='2026-09-17T00:00:00Z', active_invalidation_conditions=[])
            late['post_bind']['terminal_outcome'] = dict(
                applied_at=applied, status='executed', reason='executed',
                executed=True, terms_preserved=True)
            with self.subTest(applied_at=applied):
                self.assertTerminalConflict(late)

    def test_persisted_invalidation_is_final_across_later_attempt_state(self):
        """Terminal finality: a persisted invalidation is not re-derived.

        `terms_unchanged` describes the CURRENT execution attempt, not the
        immutable evidence from the attempt that produced the terminal record. The
        harness does not persist that historical evidence, so a later attempt's
        value must not decide whether an already-applied outcome reproduces.
        """
        def invalidated(terms_unchanged):
            v = self.fixture(9)
            v['post_bind']['execution_attempt'].update(
                at='2026-09-12T18:00:00Z', release_condition_met=True,
                release_resolved_at='2026-09-12T13:00:00Z', terms_unchanged=terms_unchanged)
            v['post_bind']['terminal_outcome'] = dict(
                applied_at='2026-09-12T14:00:00Z', status='post_bind_invalidated',
                reason='commercial_terms_reinterpreted', executed=False, terms_preserved=False)
            return v
        for terms_unchanged in (True, False):
            with self.subTest(terms_unchanged=terms_unchanged):
                self.assertEqual('commercial_terms_reinterpreted',
                                 evaluate_post_bind(invalidated(terms_unchanged))['reason'])
        # The canonical shape is still enforced: a non-canonical record conflicts.
        wrong = invalidated(False)
        wrong['post_bind']['terminal_outcome']['terms_preserved'] = True
        self.assertTerminalConflict(wrong)

    def test_persisted_terminal_outcomes_survive_later_state_drift(self):
        """Finality for every supported non-deadline terminal class."""
        # Invalidation from a declared condition, condition absent later.
        v = self.fixture(8)
        self.assertIn('inventory_allocation_changed',
                      v['post_bind']['governing_semantics']['execution_invalidation_conditions'])
        v['post_bind']['execution_attempt'].update(
            at='2026-09-12T12:00:00Z', active_invalidation_conditions=[])
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-12T11:30:00Z', status='post_bind_invalidated',
            reason='inventory_allocation_changed', executed=False, terms_preserved=True)
        self.assertEqual('inventory_allocation_changed', evaluate_post_bind(v)['reason'])

        # Ordinary execution, later drift appears.
        v = self.fixture(8)
        v['post_bind']['execution_attempt'].update(
            at='2026-09-12T12:00:00Z',
            active_invalidation_conditions=['inventory_allocation_changed'])
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-12T11:00:00Z', status='executed', reason='executed',
            executed=True, terms_preserved=True)
        self.assertEqual('executed', evaluate_post_bind(v)['reason'])

        # Release success, later attempt reports the opposite result for the
        # same authenticated event.
        v = self.release_record('release_condition_satisfied', False, 'executed',
                                resolved='2026-09-12T12:00:00Z',
                                applied='2026-09-12T13:00:00Z', executed=True)
        self.assertEqual('release_condition_satisfied', evaluate_post_bind(v)['reason'])

    def test_undeclared_invalidation_reason_cannot_replay(self):
        v = self.fixture(9)
        self.assertNotIn('inventory_allocation_changed',
                         v['post_bind']['governing_semantics']['execution_invalidation_conditions'])
        v['post_bind']['execution_attempt'].update(at='2026-09-12T17:00:00Z')
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-12T13:00:00Z', status='post_bind_invalidated',
            reason='inventory_allocation_changed', executed=False, terms_preserved=True)
        self.assertTerminalConflict(v)

    def test_arbitrary_reason_strings_cannot_bypass_authorization(self):
        """The schema permits any non-empty reason; none may replay unchecked."""
        for bogus in ('unsupported_reason', 'x' * 50, 'RETURN_TO_BUYER',
                      'return_to_buyer ', 'deemed_acceptance'):
            v = self.fixture(13)
            v['post_bind']['terminal_outcome'].update(
                status='executed', reason=bogus, executed=True)
            with self.subTest(reason=bogus):
                self.assertTerminalConflict(v)

    # Independent oracle for provenance tests: historical facts are written out
    # literally here, never derived from semantics.py.
    LEGITIMATE_EVENT = '2026-09-12T12:00:00Z'
    LEGITIMATE_APPLIED = '2026-09-12T13:00:00Z'

    def persisted_release(self, reason, later_met, later_resolved):
        """A legitimately produced release record, replayed under later state."""
        met = (reason == 'release_condition_satisfied')
        return self.release_record(
            reason, later_met,
            'executed' if met else 'release_condition_failed',
            resolved=later_resolved, applied=self.LEGITIMATE_APPLIED,
            executed=met,
            basis=dict(condition_met=met, resolved_at=self.LEGITIMATE_EVENT))

    def test_release_lifecycle_persists_and_replays_its_own_provenance(self):
        """End-to-end: provenance produced by the implementation, not the test."""
        for label, met, expected in (('success', True, 'release_condition_satisfied'),
                                     ('failure', False, 'release_condition_failed')):
            with self.subTest(lifecycle=label):
                v = self.fixture(9)
                post = v['post_bind']
                post['terminal_outcome'] = None
                post['execution_attempt'].update(
                    at='2026-09-12T17:00:00Z', release_condition_met=met,
                    release_resolved_at=self.LEGITIMATE_EVENT)
                first = evaluate_post_bind(v)
                self.assertEqual(expected, first['reason'])

                # Persist exactly what the implementation produces.
                record = persistable_terminal_outcome(v, first, self.LEGITIMATE_APPLIED)
                self.assertEqual(
                    {'condition_met': met, 'resolved_at': self.LEGITIMATE_EVENT},
                    record['release_authorization_basis'])
                post['terminal_outcome'] = record

                # Destroy every release field on the later attempt.
                post['execution_attempt'].update(
                    at='2026-09-12T20:00:00Z', release_condition_met=None,
                    release_resolved_at=None, terms_unchanged=False,
                    active_invalidation_conditions=['fraud_confirmed'])
                self.assertEqual(first, evaluate_post_bind(v))

    def test_persisted_record_never_contradicts_the_lifecycle_result(self):
        """No parallel decision: the record copies the lifecycle classification.

        `persistable_terminal_outcome()` makes no terminal decision of its own; it
        packages the result `lifecycle()` produced. This sweeps the lifecycle
        inputs and asserts the two can never disagree.
        """
        checked = 0
        for vector_id in (8, 9, 13):
            for at in ('2026-09-12T11:00:00Z', '2026-09-12T17:00:00Z',
                       '2026-09-14T00:00:00Z', '2026-09-21T00:00:00Z'):
                for terms_unchanged in (True, False):
                    for conditions in ([], ['inventory_allocation_changed'], ['fraud_confirmed']):
                        for met, resolved in ((None, None), (True, self.LEGITIMATE_EVENT),
                                              (False, self.LEGITIMATE_EVENT)):
                            v = self.fixture(vector_id)
                            v['post_bind']['terminal_outcome'] = None
                            v['post_bind']['execution_attempt'].update(
                                at=at, terms_unchanged=terms_unchanged,
                                active_invalidation_conditions=conditions,
                                release_condition_met=met, release_resolved_at=resolved)
                            result = evaluate_post_bind(v)
                            record = persistable_terminal_outcome(v, result, at)
                            checked += 1
                            with self.subTest(vector=vector_id, at=at,
                                              terms_unchanged=terms_unchanged,
                                              conditions=len(conditions), met=met):
                                if record is None:
                                    # Refused: either a transient failure, or an
                                    # `applied_at` the class cannot have. Both are
                                    # covered by the eligibility test below.
                                    continue
                                # Whatever IS produced must copy the lifecycle
                                # classification exactly.
                                self.assertNotIn(result['reason'],
                                                 TRANSIENT_LIFECYCLE_FAILURES)
                                for field in ('status', 'reason', 'executed', 'terms_preserved'):
                                    self.assertEqual(result[field], record[field])
        self.assertEqual(216, checked)

    def transient_failure_case(self, reason):
        """Lifecycle inputs producing each transient (non-historical) result."""
        if reason == 'binding_not_successful':
            v = self.fixture(9)
            v['business_state']['artifact_authentic'] = False
            return v
        if reason == 'transaction_mismatch':
            v = self.fixture(9)
            v['post_bind']['transaction']['id'] = 'unrelated-transaction'
            return v
        if reason == 'invalid_lifecycle_timing':
            v = self.fixture(9)
            v['post_bind']['bound_at'] = '2026-09-12T09:00:00Z'
            return v
        if reason == 'invalid_release_evidence':
            v = self.fixture(9)
            v['post_bind']['execution_attempt'].update(
                release_condition_met=True, release_resolved_at=None)
            return v
        if reason == 'release_condition_pending':
            v = self.fixture(9)
            v['post_bind']['execution_attempt'].update(
                at='2026-09-12T11:00:00Z', release_condition_met=None,
                release_resolved_at=None)
            return v
        v = self.fixture(13)
        v['post_bind']['terminal_outcome'].update(status='executed', executed=True)
        return v

    def test_transient_lifecycle_failures_are_never_persisted(self):
        """A rejected request is not authoritative terminal history.

        These results reuse statuses that legitimate terminal outcomes also use,
        but they describe why a request was refused, not something that happened
        to the transaction. Persisting them would fossilize a validation failure.
        """
        for reason in ('binding_not_successful', 'transaction_mismatch',
                       'invalid_lifecycle_timing', 'invalid_release_evidence',
                       'release_condition_pending',
                       'terminal_outcome_conflicts_with_accepted_disposition'):
            with self.subTest(reason=reason):
                v = self.transient_failure_case(reason)
                result = evaluate_post_bind(v)
                self.assertEqual(reason, result['reason'])
                self.assertIsNone(
                    persistable_terminal_outcome(v, result, '2026-09-12T13:00:00Z'))

    def test_transient_verdicts_cannot_be_injected_as_terminal_history(self):
        """Consumer-side invariant, independent of the persistence helper.

        Injecting a diagnostic/verdict result directly as `terminal_outcome`
        must not make it authoritative history. The conflict reason matters most:
        it names a verdict ABOUT an invalid record, so it must never itself be a
        valid historical classification.

        Rejection is distinguished from acceptance by the payload, not the reason
        string: a rejected record is forced to executed=False/terms_preserved=
        False, whereas an accepted one replays its own values verbatim.
        """
        statuses = {
            'binding_not_successful': 'bound_not_executable',
            'transaction_mismatch': 'post_bind_invalidated',
            'invalid_lifecycle_timing': 'post_bind_invalidated',
            'invalid_release_evidence': 'post_bind_invalidated',
            'release_condition_pending': 'release_pending',
            self.CONFLICT: 'post_bind_invalidated',
        }
        self.assertEqual(set(statuses), set(TRANSIENT_LIFECYCLE_FAILURES))
        for reason, status in sorted(statuses.items()):
            for executed, preserved in ((True, True), (False, True), (True, False)):
                with self.subTest(reason=reason, executed=executed, preserved=preserved):
                    v = self.fixture(9)
                    v['post_bind']['execution_attempt'].update(
                        at='2026-09-12T17:00:00Z', release_condition_met=None,
                        release_resolved_at=None)
                    v['post_bind']['terminal_outcome'] = dict(
                        applied_at='2026-09-12T11:00:00Z', status=status,
                        reason=reason, executed=executed, terms_preserved=preserved)
                    self.assertTerminalConflict(v)

    def test_no_transient_reason_has_a_canonical_historical_class(self):
        """The validator itself authorizes no transient reason, in any shape."""
        scenarios = ((9, '2026-09-12T11:00:00Z'), (8, '2026-09-12T11:00:00Z'),
                     (13, '2026-09-21T00:00:00Z'))
        statuses = ('post_bind_invalidated', 'executed', 'bound_not_executable',
                    'release_pending', 'deadline_non_execution')
        checked = 0
        for vector_id, applied_at in scenarios:
            v = self.fixture(vector_id)
            post = v['post_bind']
            policy = post['governing_semantics']
            deadline = {
                'term_expiry': v['term_artifact']['expires_at'],
                'transaction_lifetime': post['transaction']['valid_until'],
                'explicit_post_bind_deadline': policy['post_bind_valid_until'],
            }[policy['deadline_source']]
            for reason in sorted(TRANSIENT_LIFECYCLE_FAILURES):
                for status in statuses:
                    for executed, preserved in itertools.product((True, False), (True, False)):
                        record = dict(applied_at=applied_at, status=status, reason=reason,
                                      executed=executed, terms_preserved=preserved)
                        checked += 1
                        with self.subTest(vector=vector_id, reason=reason, status=status):
                            self.assertIsNone(replayable_terminal_outcome(
                                policy, record, instant(deadline),
                                instant(applied_at), instant(post['bound_at'])))
        self.assertEqual(360, checked)

    def test_every_persisted_record_round_trips_through_replay(self):
        """Producer/consumer invariant, across every terminal class.

        Anything `persistable_terminal_outcome()` returns must be accepted and
        reproduced by the replay validator under the same accepted policy.
        """
        produced = set()
        scenarios = (
            # (vector, attempt time, applied_at, release met, release event)
            (9, '2026-09-12T17:00:00Z', '2026-09-12T13:00:00Z', True, self.LEGITIMATE_EVENT),
            (9, '2026-09-12T17:00:00Z', '2026-09-12T13:00:00Z', False, self.LEGITIMATE_EVENT),
            (8, '2026-09-12T12:00:00Z', '2026-09-12T11:00:00Z', None, None),
            (8, '2026-09-17T00:00:00Z', '2026-09-16T00:00:00Z', None, None),
            (13, '2026-09-21T00:00:00Z', '2026-09-21T00:00:00Z', None, None),
        )
        for vector_id, at, applied_at, met, resolved in scenarios:
            v = self.fixture(vector_id)
            post = v['post_bind']
            post['terminal_outcome'] = None
            post['execution_attempt'].update(at=at, release_condition_met=met,
                                             release_resolved_at=resolved)
            if vector_id == 8:
                post['execution_attempt']['active_invalidation_conditions'] = []
            first = evaluate_post_bind(v)
            record = persistable_terminal_outcome(v, first, applied_at)
            with self.subTest(vector=vector_id, applied_at=applied_at):
                self.assertIsNotNone(record)
                produced.add(first['reason'])
                # Install exactly that record and replay it.
                post['terminal_outcome'] = record
                replayed = evaluate_post_bind(v)
                self.assertEqual(first, replayed)

        # A declared invalidation and terms reinterpretation, also round-tripped.
        v = self.fixture(8)
        v['post_bind']['terminal_outcome'] = None
        v['post_bind']['execution_attempt'].update(
            at='2026-09-12T12:00:00Z',
            active_invalidation_conditions=['inventory_allocation_changed'])
        first = evaluate_post_bind(v)
        self.assertEqual('inventory_allocation_changed', first['reason'])
        record = persistable_terminal_outcome(v, first, '2026-09-12T11:00:00Z')
        v['post_bind']['terminal_outcome'] = record
        self.assertEqual(first, evaluate_post_bind(v))
        produced.add(first['reason'])

        v = self.fixture(9)
        v['post_bind']['terminal_outcome'] = None
        v['post_bind']['execution_attempt'].update(
            at='2026-09-12T17:00:00Z', terms_unchanged=False,
            release_condition_met=None, release_resolved_at=None)
        first = evaluate_post_bind(v)
        self.assertEqual('commercial_terms_reinterpreted', first['reason'])
        record = persistable_terminal_outcome(v, first, '2026-09-12T13:00:00Z')
        v['post_bind']['terminal_outcome'] = record
        self.assertEqual(first, evaluate_post_bind(v))
        produced.add(first['reason'])

        # Every persistable terminal class is covered above.
        self.assertEqual(
            {'release_condition_satisfied', 'release_condition_failed', 'executed',
             'execution_deadline_elapsed', 'return_to_buyer',
             'inventory_allocation_changed', 'commercial_terms_reinterpreted'},
            produced)

    def test_non_terminal_result_persists_no_record(self):
        v = self.fixture(9)
        v['post_bind']['terminal_outcome'] = None
        v['post_bind']['execution_attempt'].update(
            at='2026-09-12T11:00:00Z', release_condition_met=None, release_resolved_at=None)
        pending = evaluate_post_bind(v)
        self.assertEqual('release_pending', pending['status'])
        self.assertIsNone(persistable_terminal_outcome(v, pending, '2026-09-12T11:00:00Z'))

    def test_release_basis_required_by_exactly_the_release_classes(self):
        # A non-release class carrying a release basis is not canonical.
        v = self.fixture(13)
        v['post_bind']['terminal_outcome']['release_authorization_basis'] = dict(
            condition_met=True, resolved_at='2026-09-19T00:00:00Z')
        self.assertTerminalConflict(v)
        # And the release classes require one.
        for reason in ('release_condition_satisfied', 'release_condition_failed'):
            with self.subTest(reason=reason):
                met = reason == 'release_condition_satisfied'
                self.assertTerminalConflict(self.release_record(
                    reason, met, 'executed' if met else 'release_condition_failed',
                    resolved=self.LEGITIMATE_EVENT, applied=self.LEGITIMATE_APPLIED,
                    executed=met, basis=None))

    def test_release_basis_requires_an_accepted_release_condition(self):
        v = self.fixture(8)
        self.assertIsNone(v['post_bind']['governing_semantics']['release_condition'])
        v['post_bind']['execution_attempt']['at'] = '2026-09-12T12:00:00Z'
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-12T11:00:00Z', status='executed',
            reason='release_condition_satisfied', executed=True, terms_preserved=True,
            release_authorization_basis=dict(condition_met=True,
                                             resolved_at='2026-09-12T10:00:00Z'))
        self.assertTerminalConflict(v)

    def test_malformed_provenance_timestamps_fail_in_a_controlled_way(self):
        """No uncaught parse/compare error escapes, including naive timestamps."""
        for bad in ('not-a-timestamp', '2026-13-45T99:99:99Z', '',
                    '2026-09-12T12:00:00'):
            with self.subTest(resolved_at=bad):
                v = self.release_record(
                    'release_condition_satisfied', True, 'executed',
                    resolved=self.LEGITIMATE_EVENT, applied=self.LEGITIMATE_APPLIED,
                    executed=True, basis=dict(condition_met=True, resolved_at=bad))
                with self.assertRaises(ValueError):
                    evaluate_post_bind(v)

    def test_release_success_remains_final_across_later_attempt_state(self):
        """A: persisted release success is final regardless of later evidence."""
        for label, met, resolved in (('agreeing', True, self.LEGITIMATE_EVENT),
                                     ('absent', None, None),
                                     ('contradictory', False, self.LEGITIMATE_EVENT),
                                     ('event moved after application', True, '2026-09-12T16:00:00Z')):
            with self.subTest(later_state=label):
                result = evaluate_post_bind(
                    self.persisted_release('release_condition_satisfied', met, resolved))
                self.assertEqual('release_condition_satisfied', result['reason'])
                self.assertEqual('executed', result['status'])
                self.assertTrue(result['executed'])

    def test_release_failure_remains_final_across_later_attempt_state(self):
        """B: and symmetrically for a persisted release failure."""
        for label, met, resolved in (('agreeing', False, self.LEGITIMATE_EVENT),
                                     ('absent', None, None),
                                     ('contradictory', True, self.LEGITIMATE_EVENT)):
            with self.subTest(later_state=label):
                result = evaluate_post_bind(
                    self.persisted_release('release_condition_failed', met, resolved))
                self.assertEqual('release_condition_failed', result['reason'])
                self.assertFalse(result['executed'])

    def test_event_after_application_cannot_authorize_release_outcome(self):
        """C: provenance citing an event later than application fails closed."""
        v = self.release_record(
            'release_condition_satisfied', True, 'executed',
            resolved=self.LEGITIMATE_EVENT, applied=self.LEGITIMATE_APPLIED, executed=True,
            basis=dict(condition_met=True, resolved_at='2026-09-12T16:00:00Z'))
        self.assertTerminalConflict(v)

    def test_evidence_disappearance_does_not_rewrite_persisted_history(self):
        """D: provenance, not current evidence, carries the authorization."""
        v = self.persisted_release('release_condition_satisfied', None, None)
        self.assertIsNone(v['post_bind']['execution_attempt']['release_resolved_at'])
        self.assertEqual('release_condition_satisfied', evaluate_post_bind(v)['reason'])

    def test_contradictory_persisted_provenance_fails_closed(self):
        """F: hostile or incoherent provenance is never trusted."""
        hostile = (
            ('missing entirely', None),
            ('result contradicts classification',
             dict(condition_met=False, resolved_at=self.LEGITIMATE_EVENT)),
            ('event at or after the exclusive deadline',
             dict(condition_met=True, resolved_at='2026-09-25T00:00:00Z')),
            ('event before binding',
             dict(condition_met=True, resolved_at='2026-09-11T00:00:00Z')),
        )
        for label, basis in hostile:
            with self.subTest(basis=label):
                v = self.release_record(
                    'release_condition_satisfied', True, 'executed',
                    resolved=self.LEGITIMATE_EVENT, applied=self.LEGITIMATE_APPLIED,
                    executed=True, basis=basis)
                self.assertTerminalConflict(v)

    def test_release_provenance_validates_against_schema(self):
        validator = Draft7Validator(load_json(SCHEMA_PATH), format_checker=FormatChecker())
        v = self.fixture(13)
        v['post_bind']['terminal_outcome']['release_authorization_basis'] = dict(
            condition_met=True, resolved_at=self.LEGITIMATE_EVENT)
        self.assertTrue(validator.is_valid(v))
        for bad in (dict(condition_met=True), dict(resolved_at=self.LEGITIMATE_EVENT),
                    dict(condition_met='yes', resolved_at=self.LEGITIMATE_EVENT),
                    dict(condition_met=True, resolved_at=self.LEGITIMATE_EVENT, extra=1)):
            with self.subTest(basis=bad):
                hostile = self.fixture(13)
                hostile['post_bind']['terminal_outcome']['release_authorization_basis'] = bad
                self.assertFalse(validator.is_valid(hostile))
        # A malformed `resolved_at` string is not caught by schema validation
        # because `date-time` needs the optional rfc3339 validator, which this
        # environment lacks; the same is true of the pre-existing `applied_at`.
        # The semantic layer rejects it instead, so it still fails closed.
        malformed = self.release_record(
            'release_condition_satisfied', True, 'executed',
            resolved=self.LEGITIMATE_EVENT, applied=self.LEGITIMATE_APPLIED, executed=True,
            basis=dict(condition_met=True, resolved_at='not-a-timestamp'))
        with self.assertRaises(ValueError):
            evaluate_post_bind(malformed)

    def terminal_case(self, name):
        """Persisted terminal records, one per supported class."""
        if name == 'return_to_buyer':
            return self.fixture(13)
        if name == 'deemed_acceptance_to_business':
            v = self.fixture(13)
            v['post_bind']['governing_semantics']['pending_at_deadline'] = name
            v['post_bind']['terminal_outcome'].update(
                status='executed', reason=name, executed=True)
            return v
        if name == 'execution_deadline_elapsed':
            v = self.fixture(8)
            v['post_bind']['execution_attempt']['at'] = '2026-09-17T00:00:00Z'
            v['post_bind']['terminal_outcome'] = dict(
                applied_at='2026-09-16T00:00:00Z', status='post_bind_invalidated',
                reason=name, executed=False, terms_preserved=True)
            return v
        if name == 'executed':
            v = self.fixture(8)
            v['post_bind']['execution_attempt']['at'] = '2026-09-12T12:00:00Z'
            v['post_bind']['terminal_outcome'] = dict(
                applied_at='2026-09-12T11:00:00Z', status='executed', reason=name,
                executed=True, terms_preserved=True)
            return v
        if name == 'inventory_allocation_changed':
            v = self.fixture(8)
            v['post_bind']['execution_attempt']['at'] = '2026-09-12T12:00:00Z'
            v['post_bind']['terminal_outcome'] = dict(
                applied_at='2026-09-12T11:00:00Z', status='post_bind_invalidated',
                reason=name, executed=False, terms_preserved=True)
            return v
        if name == 'commercial_terms_reinterpreted':
            v = self.fixture(9)
            v['post_bind']['execution_attempt']['at'] = '2026-09-12T17:00:00Z'
            v['post_bind']['terminal_outcome'] = dict(
                applied_at=self.LEGITIMATE_APPLIED, status='post_bind_invalidated',
                reason=name, executed=False, terms_preserved=False)
            return v
        return self.persisted_release(name, True, self.LEGITIMATE_EVENT)

    def test_every_terminal_class_is_final_across_current_attempt_drift(self):
        """E: no supported class re-decides itself from later attempt state."""
        classes = ('return_to_buyer', 'deemed_acceptance_to_business',
                   'execution_deadline_elapsed', 'executed',
                   'release_condition_satisfied', 'release_condition_failed',
                   'inventory_allocation_changed', 'commercial_terms_reinterpreted')
        for name in classes:
            baseline = evaluate_post_bind(self.terminal_case(name))
            self.assertEqual(name, baseline['reason'])
            for terms_unchanged in (True, False):
                for conditions in ([], ['inventory_allocation_changed', 'fraud_confirmed']):
                    for met, resolved in ((None, None), (True, self.LEGITIMATE_EVENT),
                                          (False, self.LEGITIMATE_EVENT)):
                        v = self.terminal_case(name)
                        v['post_bind']['execution_attempt'].update(
                            terms_unchanged=terms_unchanged,
                            active_invalidation_conditions=conditions,
                            release_condition_met=met, release_resolved_at=resolved)
                        with self.subTest(terminal=name, terms_unchanged=terms_unchanged,
                                          conditions=len(conditions), met=met):
                            self.assertEqual(baseline, evaluate_post_bind(v))

    def test_release_class_substitution_is_detected_by_provenance(self):
        """Swapping a release result is caught, because provenance is persisted."""
        v = self.release_record(
            'release_condition_satisfied', False, 'executed',
            resolved='2026-09-12T12:00:00Z', applied='2026-09-12T13:00:00Z', executed=True,
            basis=dict(condition_met=False, resolved_at='2026-09-12T12:00:00Z'))
        self.assertTerminalConflict(v)
        reverse = self.release_record(
            'release_condition_failed', True, 'release_condition_failed',
            resolved='2026-09-12T12:00:00Z', applied='2026-09-12T13:00:00Z', executed=False,
            basis=dict(condition_met=True, resolved_at='2026-09-12T12:00:00Z'))
        self.assertTerminalConflict(reverse)

    def test_substitution_without_provenance_is_a_trust_boundary_not_a_guarantee(self):
        """CHARACTERIZATION of a representational limit, not a security property.

        Replay detects an internally inconsistent or policy/timing-incompatible
        persisted record. It does not detect coherent replacement of the entire
        trusted terminal record, and for classes retaining no provenance
        (ordinary execution, declared invalidations, terms reinterpretation,
        deadline elapse) that means substituting one coherent record for another
        replays. This documents today's trust boundary. Modelling provenance for
        these classes in future would legitimately make such substitutions
        detectable; tightening them is an improvement, not a violation of this
        test's intent.
        """
        # Ordinary execution substituted in, pre-deadline application.
        v = self.fixture(8)
        v['post_bind']['execution_attempt']['at'] = '2026-09-12T12:00:00Z'
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-12T11:00:00Z', status='executed', reason='executed',
            executed=True, terms_preserved=True)
        self.assertEqual('executed', evaluate_post_bind(v)['reason'])

        # A declared invalidation substituted in its place.
        v = self.fixture(8)
        v['post_bind']['execution_attempt']['at'] = '2026-09-12T12:00:00Z'
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-12T11:00:00Z', status='post_bind_invalidated',
            reason='inventory_allocation_changed', executed=False, terms_preserved=True)
        self.assertEqual('inventory_allocation_changed', evaluate_post_bind(v)['reason'])

        # One declared condition swapped for another the policy also declares.
        v = self.fixture(8)
        v['post_bind']['governing_semantics']['execution_invalidation_conditions'] = [
            'inventory_allocation_changed', 'fraud_confirmed']
        v['post_bind']['execution_attempt']['at'] = '2026-09-12T12:00:00Z'
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-12T11:00:00Z', status='post_bind_invalidated',
            reason='fraud_confirmed', executed=False, terms_preserved=True)
        self.assertEqual('fraud_confirmed', evaluate_post_bind(v)['reason'])

        # Wholesale replacement, internally canonical deadline elapse.
        v = self.fixture(8)
        v['post_bind']['execution_attempt']['at'] = '2026-09-17T00:00:00Z'
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-16T00:00:00Z', status='post_bind_invalidated',
            reason='execution_deadline_elapsed', executed=False, terms_preserved=True)
        self.assertEqual('execution_deadline_elapsed', evaluate_post_bind(v)['reason'])

    def test_substitution_is_detected_when_policy_or_timing_disagrees(self):
        """The boundary has teeth: incoherent substitution is still caught."""
        # A deadline disposition substituted where timing forbids it.
        v = self.fixture(9)
        v['post_bind']['governing_semantics']['pending_at_deadline'] = 'return_to_buyer'
        v['post_bind']['execution_attempt'].update(
            at='2026-09-14T00:00:00Z', release_condition_met=None, release_resolved_at=None)
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-13T12:00:00Z', status='deadline_non_execution',
            reason='return_to_buyer', executed=False, terms_preserved=True)
        self.assertEqual('invalid_lifecycle_timing', evaluate_post_bind(v)['reason'])
        # An invalidation the policy does not declare.
        v = self.fixture(9)
        v['post_bind']['execution_attempt']['at'] = '2026-09-12T17:00:00Z'
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-12T13:00:00Z', status='post_bind_invalidated',
            reason='inventory_allocation_changed', executed=False, terms_preserved=True)
        self.assertTerminalConflict(v)
        # Ordinary execution where a release condition exists.
        v = self.fixture(9)
        v['post_bind']['execution_attempt']['at'] = '2026-09-12T17:00:00Z'
        v['post_bind']['terminal_outcome'] = dict(
            applied_at='2026-09-12T13:00:00Z', status='executed', reason='executed',
            executed=True, terms_preserved=True)
        self.assertTerminalConflict(v)

    def test_consistent_terminal_outcome_still_replays(self):
        v = self.fixture(13)
        self.assertEqual('return_to_buyer', evaluate_post_bind(v)['reason'])
        business = self.fixture(13)
        business['post_bind']['governing_semantics']['pending_at_deadline'] = 'deemed_acceptance_to_business'
        business['post_bind']['terminal_outcome'].update(
            status='executed', reason='deemed_acceptance_to_business', executed=True)
        self.assertEqual('deemed_acceptance_to_business', evaluate_post_bind(business)['reason'])

    def test_unavailable_commercial_basis_history_does_not_imply_invalid_artifact(self):
        v = self.v12_history()
        v['business_state']['commercial_basis_history_available'] = False
        v['binding_units'][3]['attempt_id'] = 'fresh-U4-after-restock'
        v['binding_units'][3]['unavailable_line_ids'] = []
        result = evaluate(v)
        self.assertEqual('commercial_basis_history_unavailable', result['reason'])
        # Same shape as attempt_history_unavailable: fails closed, stays valid.
        self.assertTrue(result['artifact_valid'])
        self.assertEqual('recognized_rejected', result['outcome'])
        self.assertEqual('same_attempt_later', result['recovery_action'])
        self.assertNotEqual('invalid_artifact', result['outcome'])
        self.assertNotEqual('new_authorized_transition', result['recovery_action'])

    def test_missing_basis_and_contradictory_basis_are_distinct(self):
        missing = self.v12_history()
        del missing['business_state']['attempt_history'][0]['effective_unit_prices']
        unavailable = evaluate(missing)
        self.assertEqual('commercial_basis_history_unavailable', unavailable['reason'])
        self.assertTrue(unavailable['artifact_valid'])

        contradictory = self.v12_history()
        contradictory['business_state']['attempt_history'][0]['effective_unit_prices'] = {
            'L01': 1200, 'L99': 1200}
        proven = evaluate(contradictory)
        self.assertEqual('invalid_artifact_semantics', proven['reason'])
        self.assertFalse(proven['artifact_valid'])
        self.assertNotEqual(unavailable['reason'], proven['reason'])

    def test_unaccepted_historical_basis_cannot_be_adjusted(self):
        v = self.v12_history()
        v['business_state']['attempt_history'][0]['effective_unit_prices']['L01'] = 1300
        v['binding_units'][3]['attempt_id'] = 'fresh-U4-after-restock'
        v['binding_units'][3]['unavailable_line_ids'] = []
        self.assertEqual('prior_bound_adjustment_requires_transition', evaluate(v)['reason'])

    def test_missing_historical_commercial_basis_fails_closed(self):
        v = self.v12_history()
        del v['business_state']['attempt_history'][0]['effective_unit_prices']
        self.assertEqual('commercial_basis_history_unavailable', evaluate(v)['reason'])
