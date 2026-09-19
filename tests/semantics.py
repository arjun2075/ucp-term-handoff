"""Candidate execution and binding semantics; no production trust implementation."""
from datetime import datetime


# Lifecycle reasons the harness defines itself. An accepted
# `execution_invalidation_conditions` entry must be disjoint from these, or a
# declared condition name would be indistinguishable from a lifecycle class and
# first-time evaluation and replay could disagree about what a record means.
RESERVED_LIFECYCLE_REASONS = frozenset((
    'executed',
    'execution_deadline_elapsed',
    'release_condition_satisfied',
    'release_condition_failed',
    'release_condition_pending',
    'commercial_terms_reinterpreted',
    'return_to_buyer',
    'deemed_acceptance_to_business',
    'binding_not_successful',
    'transaction_mismatch',
    'invalid_lifecycle_timing',
    'invalid_release_evidence',
    'terminal_outcome_conflicts_with_accepted_disposition',
))


def instant(value):
    """Parse an instant, requiring an explicit offset.

    A timezone-naive timestamp would otherwise compare-fail with an uncontrolled
    TypeError, so it is rejected here as a malformed value instead. The schema's
    `date-time` format is not enforced in every environment, which makes this the
    reliable failure point.
    """
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Instant requires an explicit UTC offset: %r' % value)
    return parsed


def recovery_action(reason):
    if reason == 'idempotency_conflict':
        return 'new_attempt_id_same_revision'
    if reason == 'line_unavailable':
        return 'new_attempt_same_revision'
    if reason in ('attempt_history_unavailable', 'commercial_basis_history_unavailable'):
        return 'same_attempt_later'
    if reason in ('bound', 'already_bound'):
        return 'already_bound'
    return 'new_authorized_transition'


def adjustment_identity(record):
    """Identity that distinguishes an applied adjustment from a new transition."""
    return (record['artifact_id'], record['line_id'], record['triggering_attempt_id'],
            record['tier_minimum_units'], record['revision'])


def applied_adjustments(state):
    """Append-only history of successfully applied commercial-basis adjustments."""
    return state.get('commercial_basis_adjustments', [])


class InconsistentAdjustmentHistory(Exception):
    """Authoritative adjustment history does not form a usable chain."""


def adjustment_chain(state, artifact_id, revision):
    """Applied adjustments belonging to one artifact revision's basis chain.

    Records from other revisions of the same artifact legitimately remain in the
    append-only store; they belong to a different chain and must not participate
    in this one.
    """
    return [record for record in applied_adjustments(state)
            if record['artifact_id'] == artifact_id and record['revision'] == revision]


def predecessor_bases(state, artifact_id, revision, bind_time_prices):
    """Running basis immediately before each record, keyed by its identity.

    Lets the identity branch validate any adjustment, first or later, against the
    basis it actually moved from rather than the immutable bind-time price.
    """
    basis = dict(bind_time_prices)
    before = {}
    for record in adjustment_chain(state, artifact_id, revision):
        line = record['line_id']
        if line not in basis:
            continue
        before[adjustment_identity(record)] = basis[line]
        basis[line] = record['new_unit_price']
    return before


def current_commercial_basis(state, artifact_id, revision, bind_time_prices):
    """current basis = bind-time basis + this revision's applied adjustments.

    Consumes authoritative history in its recorded order, starting from the
    immutable bind-time basis. Each adjustment must link to the running basis
    (`previous_unit_price` equals it) before the basis advances, and no record may
    be a no-op, which the producer never emits. Together those reject a repeated
    transition identity: to chain, a duplicate must either restate its
    predecessor's move, breaking the link, or collapse into a no-op. History is
    never sorted or reordered to repair a broken chain; a broken link raises and
    the caller fails closed on inconsistent authoritative history.
    """
    basis = dict(bind_time_prices)
    for record in adjustment_chain(state, artifact_id, revision):
        line = record['line_id']
        if line not in basis:
            # The producer only emits an adjustment for a line whose authoritative
            # attempt history records it as bound, and that history is append-only
            # across cycles just as this store is. A same-revision record for a
            # line absent from the reconstructed bound basis is therefore orphaned
            # history that no lifecycle operation could have produced, whether or
            # not the line exists in the artifact. Records from other revisions
            # belong to a different chain and never reach here.
            raise InconsistentAdjustmentHistory(line)
        if record['previous_unit_price'] == record['new_unit_price']:
            # The producer skips a line whose basis already equals the authorized
            # price, so it never emits a no-op transition.
            raise InconsistentAdjustmentHistory(line)
        if record['previous_unit_price'] != basis[line]:
            raise InconsistentAdjustmentHistory(line)
        basis[line] = record['new_unit_price']
    return basis


DEADLINE_DISPOSITIONS = ('return_to_buyer', 'deemed_acceptance_to_business')
# Fields that carry semantic outcome identity. `applied_at` is validated
# separately as timing and is deliberately not part of this comparison.
SEMANTIC_OUTCOME_FIELDS = ('status', 'reason', 'executed', 'terms_preserved')


def authorized_deadline_disposition(policy):
    """Deadline disposition authorized by the accepted evidence, if any."""
    if policy['release_condition'] is None:
        return None
    return policy['pending_at_deadline']


def semantically_equal(persisted, authorized):
    """Compare terminal outcome identity, ignoring non-authorizing metadata."""
    return all(persisted.get(field) == authorized[field]
               for field in SEMANTIC_OUTCOME_FIELDS)


def outcome(status, reason, executed=False, preserved=True):
    return dict(status=status, reason=reason, executed=executed, terms_preserved=preserved)


def canonical_deadline_outcome(disposition):
    """Canonical semantic outcome for an accepted pending-at-deadline disposition.

    None when the disposition is absent or unsupported, so nothing is authorized.
    """
    if disposition == 'return_to_buyer':
        return outcome('deadline_non_execution', 'return_to_buyer')
    if disposition == 'deemed_acceptance_to_business':
        return outcome('executed', 'deemed_acceptance_to_business', True)
    return None


def replayable_terminal_outcome(policy, terminal, deadline, applied, bound):
    """Outcome a persisted terminal record is authorized to replay, or None.

    Terminal finality means a record is validated against what authorized it when
    it was applied, never re-derived from a later `execution_attempt`. The record
    persists its classification and application time, and the release classes also
    retain a minimal release authorization basis; the other classes keep no record
    of their authorizing evidence. Validation is limited to what the persisted
    record and the immutable accepted policy can establish:

    * a deadline disposition must be the canonical shape of the disposition the
      accepted policy authorizes, and timing has already placed it at or after
      the governing deadline;
    * a release outcome must be the canonical shape for its own release result,
      must have been applied strictly before the governing deadline, and must
      carry a persisted release authorization basis whose recorded result matches
      the classification and whose event time is no later than its application;
    * an ordinary execution must predate the governing deadline;
    * an invalidation must name a condition the accepted policy declares, or the
      terms-reinterpretation result, whose authorizing evidence is not retained.

    Mutable current-attempt state is never consulted, so reproducing a historical
    outcome never depends on conditions that arose after it. The consequence is
    a trust boundary. `terminal_outcome` is treated as authoritative Business-store
    history, and for classes whose authorizing evidence is not retained the
    persisted classification is trusted once its canonical shape, policy
    compatibility, and timing are coherent. Replay detects an internally inconsistent
    or policy/timing-incompatible record, including a release record disagreeing
    with its own basis, but not coherent replacement of the whole trusted record
    together with its provenance. The basis is not separately authenticated, so it
    is trusted to the same degree as the record carrying it.
    """
    if declared_invalidation_conditions(policy) is None:
        # The accepted policy declares a condition that collides with the
        # lifecycle reason namespace, so no record can be interpreted against it
        # unambiguously. This is a policy-level guard, checked before any class
        # dispatch, matching how first-time evaluation rejects the same policy.
        return None
    reason = terminal['reason']
    release_classes = ('release_condition_satisfied', 'release_condition_failed')
    if ('release_authorization_basis' in terminal) != (reason in release_classes):
        # A release basis is required by exactly the release classes. Any other
        # class carrying one is not a canonical record for that class.
        return None
    if reason in DEADLINE_DISPOSITIONS:
        return canonical_deadline_outcome(authorized_deadline_disposition(policy))
    if reason in ('release_condition_satisfied', 'release_condition_failed'):
        # A release result requires an accepted release condition and an event
        # strictly before the exclusive deadline, so its application time must
        # fall strictly inside the bound-to-deadline window.
        if policy['release_condition'] is None:
            return None
        if applied < bound or applied >= deadline:
            return None
        # Authorization comes from the basis persisted with the record, never from
        # a later attempt; its presence is already required above.
        basis = terminal['release_authorization_basis']
        resolved = instant(basis['resolved_at'])
        # The cited event must lie in the bound-to-exclusive-deadline window and
        # predate this outcome's application.
        if resolved < bound or resolved >= deadline or resolved > applied:
            return None
        # The persisted result must be the one this classification claims.
        if basis['condition_met'] != (reason == 'release_condition_satisfied'):
            return None
        if reason == 'release_condition_satisfied':
            return outcome('executed', 'release_condition_satisfied', True)
        return outcome('release_condition_failed', 'release_condition_failed')
    if reason == 'executed':
        # Plain execution is only reachable without a release condition, before
        # the governing deadline.
        if policy['release_condition'] is not None or applied >= deadline:
            return None
        return outcome('executed', 'executed', True)
    if reason == 'execution_deadline_elapsed':
        if policy['release_condition'] is not None or applied < deadline:
            return None
        return outcome('post_bind_invalidated', 'execution_deadline_elapsed')
    if reason == 'commercial_terms_reinterpreted':
        # Authorized by evidence from the originating attempt that the harness
        # does not retain, so only the canonical shape can be enforced.
        return outcome('post_bind_invalidated', 'commercial_terms_reinterpreted',
                       preserved=False)
    declared = declared_invalidation_conditions(policy)
    if declared is not None and reason in declared:
        # An invalidation the accepted policy declares as execution-invalidating.
        # Reserved lifecycle reasons never reach here: a policy declaring one is
        # rejected above, and the reserved classes are handled by their own
        # branches, so a declared name can never be read as a lifecycle class.
        return outcome('post_bind_invalidated', reason)
    # No canonical authorized form for this reason.
    return None


def declared_invalidation_conditions(policy):
    """Accepted execution-invalidation conditions, or None if the policy is invalid.

    A condition sharing a name with a lifecycle reason is not an acceptable
    accepted policy: the resulting record would be ambiguous between a declared
    invalidation and a lifecycle class.
    """
    declared = frozenset(policy['execution_invalidation_conditions'])
    if declared & RESERVED_LIFECYCLE_REASONS:
        return None
    return declared


def authorized_terminal_outcome(vector, deadline, now, bound):
    """Canonical terminal outcome authorized by currently available evidence.

    Used for first-time evaluation, when no terminal record exists yet. Replay of
    a persisted record goes through `replayable_terminal_outcome()` instead, which
    validates the stored record without consulting the current attempt. Returns
    None when the evidence authorizes no terminal outcome at all.
    """
    post = vector['post_bind']
    policy = post['governing_semantics']
    attempt = post['execution_attempt']
    declared = declared_invalidation_conditions(policy)
    if declared is None:
        # A declared condition collides with a reserved lifecycle reason, so the
        # accepted policy cannot be interpreted unambiguously. Checked before any
        # class dispatch, matching how replay rejects the same policy.
        return outcome('post_bind_invalidated', 'invalid_lifecycle_timing')
    if not attempt['terms_unchanged']:
        return outcome('post_bind_invalidated', 'commercial_terms_reinterpreted',
                       preserved=False)
    invalidations = set(attempt['active_invalidation_conditions']) & declared
    if invalidations:
        return outcome('post_bind_invalidated', sorted(invalidations)[0])
    if policy['release_condition'] is None:
        # Without a release condition there is no deadline disposition to
        # authorize; only elapse or plain execution are reachable.
        if now >= deadline:
            return outcome('post_bind_invalidated', 'execution_deadline_elapsed')
        return outcome('executed', 'executed', True)
    resolved = attempt['release_resolved_at']
    met = attempt['release_condition_met']
    if (resolved is None) != (met is None):
        return outcome('post_bind_invalidated', 'invalid_release_evidence')
    if resolved is not None:
        resolved = instant(resolved)
        if resolved < bound or resolved > now:
            return outcome('post_bind_invalidated', 'invalid_release_evidence')
        # The deadline is exclusive: an event exactly at it is too late.
        # A verified earlier event remains effective when observed later.
        if resolved < deadline:
            if met:
                return outcome('executed', 'release_condition_satisfied', True)
            return outcome('release_condition_failed', 'release_condition_failed')
    if now < deadline:
        # Not terminal: nothing is authorized to have been applied yet.
        return None
    # An undeclared or unsupported disposition authorizes nothing.
    return canonical_deadline_outcome(policy['pending_at_deadline'])


# Results that describe a rejected request rather than something that happened to
# the transaction. They are never authoritative history.
TRANSIENT_LIFECYCLE_FAILURES = frozenset((
    'binding_not_successful',
    'transaction_mismatch',
    'invalid_lifecycle_timing',
    'invalid_release_evidence',
    'release_condition_pending',
    'terminal_outcome_conflicts_with_accepted_disposition',
))


def persistable_terminal_outcome(vector, result, applied_at):
    """Terminal record to persist for a first-time terminal `result`.

    Closes the loop between authorization and replay: the record a Business would
    store is derived here from the evidence that authorized the result, rather
    than assembled by hand. For the release classes it captures the authorization
    basis (the release result and its event time) so later replay never needs the
    current attempt.

    Returns None unless the result is a genuine historical terminal fact. A
    lifecycle result matching the evaluator is not by itself eligible to become
    authoritative history: `release_pending` is not terminal, and the transient
    validation failures (a binding that never succeeded, a mismatched
    transaction, incoherent lifecycle timing, incoherent release evidence, and a
    replay conflict) describe a rejected request rather than something that
    happened to the transaction. Persisting those would fossilize a validation
    failure as permanent history and, apart from the conflict result itself,
    could not be consumed by the replay validator. Every record returned here is
    a terminal fact the validator accepts and reproduces under the same accepted
    policy and state.
    """
    if result['reason'] in TRANSIENT_LIFECYCLE_FAILURES:
        return None
    attempt = vector['post_bind']['execution_attempt']
    record = dict(applied_at=applied_at, status=result['status'], reason=result['reason'],
                  executed=result['executed'], terms_preserved=result['terms_preserved'])
    if result['reason'] in ('release_condition_satisfied', 'release_condition_failed'):
        record['release_authorization_basis'] = dict(
            condition_met=attempt['release_condition_met'],
            resolved_at=attempt['release_resolved_at'])
    # Confirm with the replay validator itself rather than a second list of
    # eligible reasons: a record the consumer would not accept is not history.
    post = vector['post_bind']
    policy = post['governing_semantics']
    deadlines = {
        'term_expiry': vector['term_artifact']['expires_at'],
        'transaction_lifetime': post['transaction']['valid_until'],
        'explicit_post_bind_deadline': policy['post_bind_valid_until'],
    }
    deadline = instant(deadlines[policy['deadline_source']])
    applied, bound = instant(applied_at), instant(post['bound_at'])
    # `lifecycle()` applies these timing bounds before dispatching to the
    # validator, so check them here too: a record the consumer would reject on
    # timing is not history either.
    now = instant(attempt['at'])
    if (applied < bound or applied > now
            or (record['reason'] in DEADLINE_DISPOSITIONS and applied < deadline)):
        return None
    authorized = replayable_terminal_outcome(policy, record, deadline, applied, bound)
    if authorized is None or not semantically_equal(record, authorized):
        return None
    return record


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
    terminal = post.get('terminal_outcome')
    if terminal is not None:
        applied = instant(terminal['applied_at'])
        if (applied < bound or applied > now
                or (terminal['reason'] in DEADLINE_DISPOSITIONS and applied < deadline)):
            return answer('post_bind_invalidated', 'invalid_lifecycle_timing')
        # Timing alone does not authorize a stored outcome. Derive the outcome the
        # record's own class is authorized to produce, from the persisted record
        # and the immutable accepted policy, and compare the whole semantic record
        # against it: reason, status, executed, and terms_preserved. A record that
        # is not authorized is never replayed, and an unrecognised reason has no
        # canonical form, so it cannot bypass this.
        authorized = replayable_terminal_outcome(policy, terminal, deadline, applied, bound)
        if authorized is None or not semantically_equal(terminal, authorized):
            # The recorded outcome cannot be accepted. Report it as an invalidated
            # post-bind state rather than replaying it, and do not execute or
            # preserve terms on the strength of a conflicting record.
            # Correction/dispute handling stays outside this harness; the reason
            # exposes the conflict so an external process can act.
            return answer('post_bind_invalidated',
                          'terminal_outcome_conflicts_with_accepted_disposition',
                          False, False)
        return answer(terminal['status'], terminal['reason'], terminal['executed'],
                      terminal['terms_preserved'])
    # No persisted outcome yet, so the result is decided from the currently
    # available evidence. A record persisted from this result is validated on
    # replay by `replayable_terminal_outcome()` instead.
    authorized = authorized_terminal_outcome(vector, deadline, now, bound)
    if authorized is None:
        if now < deadline:
            # Pending before the deadline is the one non-terminal resting state.
            return answer('release_pending', 'release_condition_pending')
        raise ValueError('Missing pending-at-deadline disposition')
    return dict(authorized)


def accepted_tier_rule_is_valid(rule):
    """Accepted-policy invariant, independent of any current request.

    A `unit_count_tier` rule must name each threshold once; duplicates make tier
    selection ambiguous whether or not this request exercises pricing.
    """
    if not rule or rule['type'] != 'unit_count_tier':
        return True
    thresholds = [row['minimum_units'] for row in rule['tiers']]
    return len(thresholds) == len(set(thresholds))


def validate_adjustment_history(chain, artifact, scope, rule, requested,
                                authoritative_bound, effective_units,
                                in_flight_trigger):
    """Validate stored adjustment history against authoritative facts alone.

    Runs whenever a same-revision chain exists, independent of what the current
    request reconstructed, so a stale or conflicting request can neither hide
    corrupt history nor make valid history look corrupt. Returns a failure
    reason, or None when the stored history is coherent.
    """
    # A chain written by an in-flight transition legitimately cites that
    # transition's attempt, which has no bound record yet. Only the attempt the
    # producer would actually select is eligible, which is the first unit that
    # legitimately becomes newly bound, so a stale, already-bound or otherwise
    # non-effective unit cannot supply trigger provenance.
    if not accepted_tier_rule_is_valid(rule):
        return 'invalid_artifact_semantics'
    legitimate_triggers = {h['attempt_id'] for h in authoritative_bound}
    if in_flight_trigger is not None:
        legitimate_triggers.add(in_flight_trigger)
    tier_prices = {row['minimum_units']: row['unit_price']
                   for row in rule['tiers']} if rule and rule['type'] == 'unit_count_tier' else {}
    # Effective units authoritative state has reached: units with bound
    # history, plus any unit newly binding in this transition. No unbind
    # is modelled, so no historical count can exceed it.
    # A record may describe a transition this request is partially replaying, so
    # the reachable count is the union of validated historical binding units and
    # the units that legitimately become effective now. One evaluation may newly
    # bind several units, so no fixed increment is assumed. No unbind is
    # modelled, so the count cannot exceed that union.
    # When this evaluation makes units effective, the reachable count is the
    # union of validated historical units and those, and one evaluation may
    # newly bind several. When it makes none effective it observed no
    # transition at all and cannot refute a partially-persisted record, so the
    # accepted scope bounds the count instead.
    reachable = {h['binding_unit_id'] for h in authoritative_bound} | effective_units
    realized_units = len(reachable)
    bound_records = {h['attempt_id']: h for h in authoritative_bound}
    accepted_groups = {group['id']: group for group in scope['groups']}
    trigger_context = {}
    count_trigger = {}
    previous_count = None
    # Replay the chain over the authoritative bind-time basis so a broken link
    # or a no-op is caught even when this request reconstructs nothing.
    bind_time = {line: price for record in authoritative_bound
                 for line, price in record.get('effective_unit_prices', {}).items()}
    running = dict(bind_time)
    for record in chain:
        line = record['line_id']
        if line not in running:
            # An adjustment applies to already-bound scope, so a same-revision
            # record naming a line with no authoritative bind-time basis is
            # orphaned history rather than something to skip over.
            return 'invalid_artifact_semantics'
        if record['previous_unit_price'] == record['new_unit_price']:
            # The producer skips a line whose basis already equals the
            # authorized price, so it never emits a no-op transition.
            return 'invalid_artifact_semantics'
        if record['previous_unit_price'] != running[line]:
            return 'invalid_artifact_semantics'
        running[line] = record['new_unit_price']
        if record['authorization_source'] != 'accepted_unit_count_tier':
            # The only authority this harness models.
            return 'invalid_artifact_semantics'
        if record['effective_unit_count'] < 2:
            # An adjustment needs previously-bound scope plus a different
            # newly-binding unit, so no producing transition can have
            # fewer than two effective units. Prices cannot establish
            # this: a fabricated count may cite a row that authorizes
            # exactly the price the record records.
            return 'invalid_artifact_semantics'
        if record['effective_unit_count'] > realized_units:
            # The count must also be one authoritative binding state has
            # actually reached. Tier prices need be neither unique nor
            # monotonic, so a false count can select the same price as
            # the true one; only this check rejects it. Realized units
            # are drawn from the accepted binding units, so this also
            # bounds the count by the accepted scope.
            return 'invalid_artifact_semantics'
        historical_trigger = bound_records.get(record['triggering_attempt_id'])
        if historical_trigger is not None:
            accepted_group = accepted_groups.get(historical_trigger['binding_unit_id'])
            if (accepted_group is None
                    or historical_trigger['line_ids'] != accepted_group['line_ids']
                    or historical_trigger['target_transaction'] != requested['target_transaction']):
                # The cited attempt does not correspond to an accepted
                # binding unit of this artifact for this transaction.
                return 'invalid_artifact_semantics'
            if record['line_id'] in historical_trigger['line_ids']:
                # The triggering newly-bound unit cannot contain the line
                # whose prior basis this record adjusts.
                return 'invalid_artifact_semantics'
        if previous_count is not None and record['effective_unit_count'] < previous_count:
            # The harness models no unbind, so the effective bound-unit
            # count cannot decrease over append-only history.
            return 'invalid_artifact_semantics'
        previous_count = record['effective_unit_count']
        context = (record['effective_unit_count'], record['tier_minimum_units'])
        trigger = record['triggering_attempt_id']
        if trigger_context.setdefault(trigger, context) != context:
            # One triggering transition has one context; it cannot claim
            # two different counts or tiers across lines.
            return 'invalid_artifact_semantics'
        if count_trigger.setdefault(record['effective_unit_count'], trigger) != trigger:
            # The converse: one adjustment-producing transition chooses a
            # single triggering attempt, so one effective count cannot be
            # attributed to two different triggers. Counts need not be
            # contiguous; an evaluation may jump from 1 to 3.
            return 'invalid_artifact_semantics'
        if record['tier_minimum_units'] not in tier_prices:
            # No such row in the accepted rule, so no authority for it.
            return 'invalid_artifact_semantics'
        if record['new_unit_price'] != tier_prices[record['tier_minimum_units']]:
            # The recorded effect is not the price that row authorizes.
            return 'invalid_artifact_semantics'
        reachable = [row for row in rule['tiers']
                     if record['effective_unit_count'] >= row['minimum_units']]
        if not reachable or max(
                reachable, key=lambda row: row['minimum_units'])['minimum_units'] != (
                    record['tier_minimum_units']):
            # The recorded tier is not the highest accepted threshold the
            # persisted transition context satisfies, so that context
            # could not have selected it.
            return 'invalid_artifact_semantics'
        if record['triggering_attempt_id'] not in legitimate_triggers:
            # A cited attempt with no validated bound record can only be this
            # transition's own in-flight trigger. When the producer selects one,
            # any other attempt is positively contradicted: the producer would
            # never have chosen an already-bound, stale or rejected unit. When
            # it selects none this request evaluated nothing effective, so it
            # can neither confirm nor refute the record, and the documented
            # ordering limit applies rather than a corruption verdict.
            return 'invalid_artifact_semantics'
    return None


def units(vector):
    artifact = vector['term_artifact']
    scope = artifact['binding_authorization']
    state = vector['business_state']
    requested = vector['binding_request']
    groups = vector['binding_units']
    def failure(reason):
        # Unavailable authoritative history fails closed, but it never proves the
        # artifact or transition invalid; only real evidence of invalidity does.
        artifact_valid = reason in ('attempt_history_unavailable', 'idempotency_conflict',
                                    'commercial_basis_history_unavailable')
        answer = dict(recognized=True, artifact_valid=artifact_valid, bindable=False,
                      outcome='recognized_rejected' if artifact_valid else 'invalid_artifact',
                      reason=reason)
        answer['recovery_action'] = recovery_action(reason)
        return answer
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
    accepted_groups = {group['id']: group for group in scope['groups']}
    authoritative_bound = [h for h in history if h['reason'] == 'bound'
                           and h['artifact_id'] == artifact['id']
                           and h['revision'] == artifact['revision']]
    def matches_accepted_authorization(record):
        accepted_group = accepted_groups.get(record['binding_unit_id'])
        return (accepted_group is not None
                and record['line_ids'] == accepted_group['line_ids']
                and record['target_transaction'] == requested['target_transaction']
                # The price map must describe exactly the scope the record
                # bound, so consumers can treat it as authoritative basis.
                and set(record.get('effective_unit_prices', {})) == set(record['line_ids']))

    # Occupying an attempt id and successfully binding accepted scope are
    # different facts. Raw history answers the first: the duplicate-id check
    # above and the per-unit identity comparison below both read it directly, so
    # a malformed record sharing a current attempt id still yields the
    # established idempotency conflict. Only a record matching the accepted
    # authorization answers the second, so `authoritative_bound` holds exactly
    # those, and every historical successful-binding consumer reads it rather
    # than raw history. A malformed record that the current request does not
    # replay is global corruption instead.
    #
    # A record the request replays is excused from being global corruption, so
    # the per-unit comparison can report the established idempotency conflict,
    # but it is still removed from the validated projection: occupying an
    # attempt id never authenticates a successful bind.
    replayed_attempts = {group['attempt_id'] for group in groups}
    for record in authoritative_bound:
        if record['attempt_id'] in replayed_attempts:
            continue
        if not matches_accepted_authorization(record):
            return failure('invalid_artifact_semantics')
    authoritative_bound = [record for record in authoritative_bound
                           if matches_accepted_authorization(record)]
    bound_identities = [(h['artifact_id'], h['revision'], h['binding_unit_id'],
                         tuple(h['line_ids']), h['target_transaction'])
                        for h in authoritative_bound]
    if len(bound_identities) != len(set(bound_identities)):
        # I19: accepted scope cannot be bound twice. Two authoritative successful
        # records for one binding identity are corrupt history, not a replay.
        return failure('invalid_artifact_semantics')
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
                            retry_class=recovery_action(reason)))
    effective = {line for out in outputs for line in out['effective_bound_line_ids']}
    newly = {line for out in outputs for line in out['newly_bound_line_ids']}
    failed = set(line_map) - effective
    prices = {line: line_map[line]['unit_price'] for line in sorted(effective)}
    historical_prices = {}
    prior_units = set()
    group_map = {group['id']: group for group in groups}
    for out in outputs:
        if out['reason'] != 'already_bound':
            continue
        group = group_map[out['binding_unit_id']]
        identity = dict(artifact_id=artifact['id'], revision=group['accepted_revision'],
                        binding_unit_id=group['id'], line_ids=group['line_ids'],
                        target_transaction=group['target_transaction'])
        record = next((h for h in history
                       if h['reason'] == 'bound'
                       and all(h[k] == value for k, value in identity.items())), None)
        if record is None or 'effective_unit_prices' not in record:
            return failure('commercial_basis_history_unavailable')
        if set(record['effective_unit_prices']) != set(out['effective_bound_line_ids']):
            # Authoritative history exists and contradicts the bound scope. That is
            # evidence of an invalid artifact projection, not an unavailable store.
            return failure('invalid_artifact_semantics')
        prior_units.add(out['binding_unit_id'])
        historical_prices.update(record['effective_unit_prices'])
    rule = scope['contraction_rule']
    selected = None
    # The attempt that newly binds scope is what triggers any basis transition.
    triggering_attempt_id = next((group_map[out['binding_unit_id']]['attempt_id']
                                  for out in outputs if out['newly_bound_line_ids']), None)
    if failed and effective:
        if rule is None or not state['adjustment_authorization_verified']:
            return failure('unauthorized_adjustment')
        if rule['type'] not in ('unit_count_tier', 'fixed_prices'):
            return failure('invalid_artifact_semantics')
    if effective and rule and rule['type'] == 'unit_count_tier':
        if not accepted_tier_rule_is_valid(rule):
            return failure('invalid_artifact_semantics')
        count = sum(bool(out['effective_bound_line_ids']) for out in outputs)
        choices = [row for row in rule['tiers'] if count >= row['minimum_units']]
        if not choices:
            return failure('commercial_basis_unsatisfied')
        selected = max(choices, key=lambda row: row['minimum_units'])
        prices = {line: selected['unit_price'] for line in sorted(effective)}
    chain = adjustment_chain(state, artifact['id'], artifact['revision'])
    if chain and not state.get('commercial_basis_history_available', True):
        return failure('commercial_basis_history_unavailable')
    # Whether a stored chain is orphaned is a property of authoritative history,
    # not of this request. `historical_prices` is request-relative: it holds only
    # the lines this evaluation reclassified as already_bound, so a stale or
    # conflicting request would otherwise make valid stored history look invalid.
    authoritative_basis = {line: price for record in authoritative_bound
                           for line, price in record.get('effective_unit_prices', {}).items()}
    if chain and not authoritative_basis:
        # An adjustment can only apply to already-bound scope, so a chain with no
        # authoritative bound basis at all could not have been produced.
        return failure('invalid_artifact_semantics')
    # Stored history is validated on its own terms whenever a chain exists, so a
    # stale or conflicting request can neither hide corrupt history nor make
    # valid history look corrupt. Only the current transition's pricing below
    # depends on what this request reconstructed.
    if chain:
        # The units this evaluation legitimately makes effective, and the
        # attempt the producer would select, computed exactly as the producer
        # does rather than from every attempt the request presents.
        history_failure = validate_adjustment_history(
            chain, artifact, scope, rule, requested, authoritative_bound,
            {out['binding_unit_id'] for out in outputs
             if out['effective_bound_line_ids']},
            triggering_attempt_id)
        if history_failure is not None:
            return failure(history_failure)
    adjustments = []
    if historical_prices:
        # Authoritative adjustment history must be available to reason about a
        # basis that may already have moved. Missing history fails closed without
        # implying the artifact or the transition is invalid.
        if not state.get('commercial_basis_history_available', True):
            return failure('commercial_basis_history_unavailable')
        if rule and rule['type'] == 'unit_count_tier':
            prior_choices = [row for row in rule['tiers'] if len(prior_units) >= row['minimum_units']]
            if not prior_choices:
                return failure('commercial_basis_unsatisfied')
            prior_authorized_price = max(prior_choices, key=lambda row: row['minimum_units'])['unit_price']
        else:
            prior_authorized_price = None
        # The effective basis is the bind-time basis plus applied adjustments, so
        # an already-adjusted line is compared at its real current value.
        try:
            # The stored chain was validated above on authoritative facts; here
            # it is only replayed to derive the basis this transition prices
            # against.
            predecessors = predecessor_bases(
                state, artifact['id'], artifact['revision'], historical_prices)
            derived = current_commercial_basis(
                state, artifact['id'], artifact['revision'], historical_prices)
        except InconsistentAdjustmentHistory:
            # The history is present but cannot form a valid append-only chain.
            # Immutable contradictory history is structural invalidity, not a
            # transient outage, so it must not be reported as retryable.
            return failure('invalid_artifact_semantics')
        already_applied = {adjustment_identity(record): record
                           for record in adjustment_chain(state, artifact['id'],
                                                          artifact['revision'])}
        tier_row = selected['minimum_units'] if selected is not None else None
        for line in sorted(historical_prices):
            new_price = prices[line]
            current_price = derived[line]
            identity = adjustment_identity(dict(
                artifact_id=artifact['id'], line_id=line,
                triggering_attempt_id=triggering_attempt_id,
                tier_minimum_units=tier_row, revision=artifact['revision']))
            applied_record = already_applied.get(identity)
            if applied_record is not None:
                # The identity is an idempotency key, not proof that the correct
                # adjustment was applied. The record describes a transition that
                # already ran, so its effect is checked against the running basis
                # immediately before it in the chain, which is the bind-time price
                # only for the first adjustment on a line, and against the price
                # this tier authorizes. A same-key record with a different effect
                # is a conflict, not a new adjustment.
                if (applied_record['previous_unit_price'] != predecessors.get(identity)
                        or applied_record['new_unit_price'] != new_price
                        or applied_record['effective_unit_count'] != count):
                    # The persisted transition provenance must describe the
                    # transition being replayed, even when two counts would
                    # select the same tier and the price is unchanged.
                    return failure('invalid_artifact_semantics')
                continue
            if current_price == new_price:
                # The current basis already equals the authorized price, so no
                # transition is required even when bind-time price differed.
                continue
            authorized = (rule and rule['type'] == 'unit_count_tier'
                          and state['adjustment_authorization_verified']
                          and current_price == prior_authorized_price)
            if not authorized:
                return failure('prior_bound_adjustment_requires_transition')
            # Authorization above required the accepted unit-count tier, which is
            # the same condition that selects a tier row, so every emitted
            # adjustment carries the full identity needed to persist and
            # deduplicate it.
            adjustments.append(dict(
                line_id=line, previous_unit_price=current_price,
                new_unit_price=new_price,
                authorization_source='accepted_unit_count_tier',
                triggering_attempt_id=triggering_attempt_id,
                tier_minimum_units=tier_row,
                effective_unit_count=count,
                revision=artifact['revision']))
    outcome = 'partially_bound' if effective and failed else 'bound' if effective else 'recognized_rejected'
    answer = dict(recognized=True, artifact_valid=True, bindable=bool(effective), outcome=outcome,
                  reason={'partially_bound': 'partial_binding', 'bound': 'bound', 'recognized_rejected': 'binding_unit_rejected'}[outcome],
                  unit_results=outputs, effective_bound_line_count=len(effective),
                  newly_bound_line_count=len(newly), failed_line_count=len(failed))
    if scope['contraction_rule'] and scope['contraction_rule']['type'] == 'unit_count_tier':
        answer['effective_unit_prices'] = prices
    if adjustments:
        answer['adjustments'] = adjustments
    return answer
