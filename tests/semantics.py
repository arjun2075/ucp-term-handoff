"""Candidate execution and binding semantics; no production trust implementation."""
from datetime import datetime


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def retry_class(reason):
    if reason == 'line_unavailable':
        return 'new_attempt_same_revision'
    if reason in ('bound', 'already_bound'):
        return 'already_bound'
    return 'new_authorized_transition'


def lifecycle(vector, binding):
    post = vector['post_bind']
    policy = post['governing_semantics']
    attempt = post['execution_attempt']
    def answer(status, reason, executed=False, preserved=True):
        return dict(status=status, reason=reason, executed=executed, terms_preserved=preserved)
    if not binding['bindable']:
        return answer('bound_not_executable', 'binding_not_successful')
    if post['transaction']['id'] != vector['binding_request']['target_transaction']:
        return answer('post_bind_invalidated', 'transaction_mismatch')
    if post['bound_at'] != vector['binding_request']['at']:
        return answer('post_bind_invalidated', 'invalid_lifecycle_timing')
    deadlines = {
        'term_expiry': vector['term_artifact']['expires_at'],
        'transaction_lifetime': post['transaction']['valid_until'],
        'explicit_post_bind_deadline': policy['post_bind_valid_until'],
    }
    deadline = instant(deadlines[policy['deadline_source']])
    now, bound = instant(attempt['at']), instant(post['bound_at'])
    if now < bound or deadline <= bound:
        return answer('post_bind_invalidated', 'invalid_lifecycle_timing')
    if not attempt['terms_unchanged']:
        return answer('post_bind_invalidated', 'commercial_terms_reinterpreted', preserved=False)
    invalidations = set(attempt['active_invalidation_conditions']) & set(policy['execution_invalidation_conditions'])
    if invalidations:
        return answer('post_bind_invalidated', sorted(invalidations)[0])
    if policy['release_condition'] is None:
        if now >= deadline:
            return answer('post_bind_invalidated', 'execution_deadline_elapsed')
        return answer('executed', 'executed', True)
    resolved = attempt['release_resolved_at']
    met = attempt['release_condition_met']
    if (resolved is None) != (met is None):
        return answer('post_bind_invalidated', 'invalid_release_evidence')
    if resolved is not None:
        resolved = instant(resolved)
        if resolved < bound or resolved > now:
            return answer('post_bind_invalidated', 'invalid_release_evidence')
        # The deadline is exclusive: an event exactly at it is too late.
        # A verified earlier event remains effective when observed later.
        if resolved < deadline:
            if met:
                return answer('executed', 'release_condition_satisfied', True)
            return answer('release_condition_failed', 'release_condition_failed')
    if now < deadline:
        return answer('release_pending', 'release_condition_pending')
    disposition = policy['pending_at_deadline']
    if disposition == 'return_to_buyer':
        return answer('deadline_non_execution', 'return_to_buyer')
    if disposition == 'deemed_acceptance_to_business':
        return answer('executed', 'deemed_acceptance_to_business', True)
    raise ValueError('Missing pending-at-deadline disposition')


def units(vector):
    artifact = vector['term_artifact']
    scope = artifact['binding_authorization']
    state = vector['business_state']
    requested = vector['binding_request']
    groups = vector['binding_units']
    def failure(reason):
        return dict(recognized=True, artifact_valid=False, bindable=False,
                    outcome='invalid_artifact', reason=reason)
    if not state['binding_authorization_verified']:
        return failure('unauthorized_grouping')
    declared = {g['id']: g for g in scope['groups']}
    actual = {g['id']: g for g in groups}
    if len(actual) != len(groups) or len(declared) != len(scope['groups']):
        return failure('atomicity_violation')
    if set(actual) != set(declared):
        return failure('scope_contraction' if set(actual) < set(declared) else 'unauthorized_grouping')
    line_map = {line['line_id']: line for line in artifact['lines']}
    request_map = {line['line_id']: line for line in requested['lines']}
    flattened = [line for g in groups for line in g['line_ids']]
    if len(line_map) != len(artifact['lines']) or len(request_map) != len(requested['lines']):
        return failure('atomicity_violation')
    if len(flattened) != len(set(flattened)):
        return failure('atomicity_violation')
    if set(flattened) != set(line_map) or request_map != line_map:
        return failure('scope_contraction' if set(flattened) < set(line_map) else 'unauthorized_scope')
    for group in groups:
        auth = declared[group['id']]
        if group['line_ids'] != auth['line_ids'] or group['atomicity_mode'] != auth['atomicity_mode']:
            return failure('unauthorized_grouping')
        if group['atomicity_mode'] != 'all_or_nothing':
            return failure('atomicity_violation')
        if not set(group['unavailable_line_ids']) <= set(group['line_ids']):
            return failure('invalid_artifact_semantics')
        if group['target_transaction'] != requested['target_transaction']:
            return failure('idempotency_conflict')
    history = state['attempt_history']
    if not state['attempt_history_available']:
        return failure('attempt_history_unavailable')
    ids = [h['attempt_id'] for h in history]
    if len(ids) != len(set(ids)) or len({g['attempt_id'] for g in groups}) != len(groups):
        return failure('idempotency_conflict')
    outputs = []
    for group in groups:
        identity = dict(artifact_id=artifact['id'], revision=group['accepted_revision'],
                        binding_unit_id=group['id'], line_ids=group['line_ids'],
                        target_transaction=group['target_transaction'])
        reason, effective, newly, kind = 'bound', group['line_ids'], group['line_ids'], 'bound'
        same = next((h for h in history if h['attempt_id'] == group['attempt_id']), None)
        related = [h for h in history if all(h[k] == v for k, v in identity.items())]
        if same and any(same[k] != v for k, v in identity.items()):
            reason = 'idempotency_conflict'
        elif group['accepted_revision'] != artifact['revision']:
            reason = 'stale_revision'
        elif same:
            reason = same['reason']
        elif any(h['reason'] not in ('bound', 'line_unavailable') for h in related):
            reason = next(h['reason'] for h in related if h['reason'] not in ('bound', 'line_unavailable'))
        elif any(h['reason'] == 'bound' for h in related):
            reason = 'already_bound'
        elif group['unavailable_line_ids']:
            # Inventory drift alone cannot withdraw a firm promise.
            reason = 'bound' if artifact['commitment']['type'] == 'business_firm' else 'line_unavailable'
        if reason == 'bound' and same:
            reason = 'already_bound'
        if reason == 'already_bound':
            newly, kind = [], 'idempotent_replay'
        elif reason != 'bound':
            effective, newly, kind = [], [], 'binding_unit_rejected'
        outputs.append(dict(binding_unit_id=group['id'], result=kind, reason=reason,
                            effective_bound_line_ids=effective, newly_bound_line_ids=newly,
                            retry_class=retry_class(reason)))
    effective = {line for out in outputs for line in out['effective_bound_line_ids']}
    newly = {line for out in outputs for line in out['newly_bound_line_ids']}
    failed = set(line_map) - effective
    prices = {line: line_map[line]['unit_price'] for line in sorted(effective)}
    rule = scope['contraction_rule']
    if failed and effective:
        if rule is None or not state['adjustment_authorization_verified']:
            return failure('unauthorized_adjustment')
        if rule['type'] == 'unit_count_tier':
            thresholds = [row['minimum_units'] for row in rule['tiers']]
            if len(thresholds) != len(set(thresholds)):
                return failure('invalid_artifact_semantics')
            count = sum(len(out['effective_bound_line_ids']) > 0 for out in outputs)
            choices = [row for row in rule['tiers'] if count >= row['minimum_units']]
            if not choices:
                return failure('commercial_basis_unsatisfied')
            selected = max(choices, key=lambda row: row['minimum_units'])
            prices = {line: selected['unit_price'] for line in sorted(effective)}
            # No retroactive adjustment of a previously bound unit in this harness.
            if effective - newly and any(prices[line] != line_map[line]['unit_price'] for line in effective - newly):
                return failure('prior_bound_adjustment_requires_transition')
        elif rule['type'] != 'fixed_prices':
            return failure('invalid_artifact_semantics')
    outcome = 'partially_bound' if effective and failed else 'bound' if effective else 'recognized_rejected'
    answer = dict(recognized=True, artifact_valid=True, bindable=bool(effective), outcome=outcome,
                  reason={'partially_bound': 'partial_binding', 'bound': 'bound', 'recognized_rejected': 'binding_unit_rejected'}[outcome],
                  unit_results=outputs, effective_bound_line_count=len(effective),
                  newly_bound_line_count=len(newly), failed_line_count=len(failed))
    if scope['contraction_rule'] and scope['contraction_rule']['type'] == 'unit_count_tier':
        answer['effective_unit_prices'] = prices
    return answer
