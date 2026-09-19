# Boundary model and candidate invariants

## Status and terminology

The statements below are **candidate invariants derived from current implementation evidence**. Uppercase key words express the behavior tested by this artifact; they are not normative UCP requirements.

- **Term artifact**: durable output of a quote, RFQ, negotiation, award, or other term-formation mechanism.
- **Binding**: the Business evaluates that artifact and returns authoritative Cart/Checkout state or a classified rejection.
- **Bound transaction**: authoritative Cart/Checkout state that records a successful binding. It is not necessarily executed, completed, settled, or released.
- **Binding unit / atomicity group**: one or more accepted lines that bind atomically. Fulfillment-separable units may share commercial dependencies governed by an authorized contraction rule; no unit can be silently split.
- **Execution/release boundary**: the declared event at which the transaction completes, value moves, settlement occurs, or a conditional obligation is released.
- **Recognized**: the Business can resolve or authenticate the artifact. Recognition does not imply that it is valid, executable, or authoritative.
- **Transaction authority**: the Business remains authoritative for creation and mutation of its UCP Cart/Checkout. A term artifact only carries its declared commercial authority within its accepted scope.

## Four independent questions

1. **Integrity / preservation** — Did the same artifact, revision, parties, scope, terms, acceptance, and validity window arrive?
2. **Authority provenance** — Who issued or authorized those commercial terms, and can the Business verify that fact?
3. **Commitment semantics** — Is this a proposal, mutual acceptance subject to revalidation, or a Business-issued firm commitment?
4. **Revalidation / invalidation** — Which binding-time checks are allowed, and how is a recognized-but-non-executable artifact distinguished from an invalid one?

Passing one question does not answer another. In particular, a byte-perfect portable artifact can be unauthorized, and an authentic unexpired artifact can be non-executable when its declared commitment permits revalidation.

## Lifecycle phases

The harness treats these as distinct phases:

1. term formation;
2. acceptance or award;
3. binding into authoritative transaction state (`bound_at`);
4. a post-bind holding period governed by declared post-bind validity and transaction lifetime;
5. execution, completion, settlement, or conditional release.

Binding success answers whether authoritative transaction state was created. It does not answer whether later execution is permitted. The names `bound_at`, `post_bind_valid_until`, `release_condition`, and `execution_invalidation_conditions` are provisional harness vocabulary.

## Candidate invariants

| ID | Candidate invariant | Test consequence |
|---|---|---|
| I1 | Accepted-term identity MUST survive the handoff. | The authoritative response or rejection correlates to artifact id and revision. |
| I2 | A stale or superseded revision MUST NOT bind. | Current-revision comparison is fail-closed. |
| I3 | Binding MUST NOT silently expand accepted item or quantity scope. | Added SKU or quantity is rejected or separately repriced without claiming quoted authority. |
| I4 | Expired terms MUST NOT bind as current accepted terms. | Expiry is evaluated at binding time; renewal creates newly authorized state. |
| I5 | Acceptance/award state and its provenance MUST survive the handoff. | Actor, time, and accepted revision remain attributable across async/human pauses. |
| I6 | Artifact validity and transaction executability MUST be distinguishable. | `recognized_rejected` differs from malformed, unknown, forged, stale, and expired. |
| I7 | Authority provenance MUST identify who supplied and who authorized the commercial terms. | Buyer acceptance alone cannot be mistaken for Business price authorization. |
| I8 | Commitment semantics MUST distinguish a Business firm commitment from terms requiring Business revalidation. | The same values can yield different permitted binding behavior. |
| I9 | Business-authoritative transaction state MUST NOT acquire more commercial authority than the artifact grants. | Binding cannot turn limited scope or advisory terms into an unlimited price mandate. |
| I10 | When commitment semantics permit revalidation, Business-side rejection at binding MUST be representable. | A valid artifact may produce a classified non-executable result. |
| I11 | Under this harness's modeled `business_firm` semantics, a Business MUST NOT arbitrarily invalidate its commitment during the validity window. | Rejection is allowed only for an explicitly declared invalidation condition. This is a candidate semantic, not an existing UCP rule. |
| I12 | Binding MUST be deterministic for a fixed artifact revision, request, Business state, and evaluation time. | Replays under identical inputs yield the same classification and do not select another revision. |
| I13 | Binding and execution MUST be modeled as distinct lifecycle points when a holding period exists. | A bound transaction may be pending, executed, released, or explicitly non-executable. |
| I14 | Execution deadline and optional release condition MUST be independent, explicitly authorized policies. | Every release path evaluates the selected clock; condition presence cannot bypass it. |
| I15 | Every modeled execution path MUST select term expiry, transaction lifetime, or an explicit post-bind deadline. | The selected timestamp is enforced, including `transaction.valid_until` when selected. |
| I16 | Scope contraction MUST NOT be silent. | Omitted accepted scope is rejected or reported as an explicit failed binding unit. |
| I17 | Partial success MUST identify independent binding units and their results. | Artifact-wide success cannot hide failed units; artifact-wide failure need not discard successful independent units. |
| I18 | Cross-line dependencies MUST have declared atomicity and, where units are separable, authorized contraction semantics. | An atomic unit binds whole or rejects; cross-unit commercial conditions follow I21. |
| I19 | Attempt identity MUST be separate from accepted artifact revision, and successful history MUST preserve the effective commercial basis of bound scope. | Same-attempt replay preserves the recorded result and price basis; successful scope cannot bind twice, even under a fresh attempt. |
| I20 | Conditional release MUST preserve agreed commercial terms. | Intermediate drift and release disposition cannot silently reprice. |
| I21 | Cross-unit contraction and later adjustment MUST use a deterministic rule covered by accepted Business authorization; changes to already-bound scope MUST be explicit. | Fixed prices, accepted tiers, or a declared minimum are permissible; accepted tier changes emit adjustments against historical basis, while missing, unverifiable, or uncovered authority fails closed. |
| I22 | Pending release at the governing deadline MUST have an explicit authorized disposition that is final once applied. | Buyer return/non-execution and deemed acceptance toward the Business are separate economic choices; neither is a default, and late evidence cannot rewrite the allocated outcome. |
| I23 | Retry/recovery behavior MUST identify who or what can make progress while preserving authorized unit composition. | Attempt-id conflicts require a new id under the same revision, availability drift permits a fresh attempt, history-store outage permits the same attempt later, and structural/authorization failures require a new authorized transition. |

I13–I23 are candidate semantics prompted by Weston's lifecycle and partial-binding review. They do not revise I1–I12 or claim current UCP requirements.

## Candidate property audit

“Invariant” here means a semantic fact that an interoperable handoff needs. It does not mean every value must be copied into a portable wire object.

| Candidate property | Classification | Rationale |
|---|---|---|
| term/quote identifier | invariant | Correlation and replay protection require stable identity. |
| revision | invariant | Async counteroffers require explicit supersession checks. |
| issuer/originating party | invariant | Needed for provenance and verifier selection. |
| buyer/customer identity or scope | invariant, representation-specific | Binding must constrain the beneficiary; a protocol need not impose a universal identity model. |
| item identity | invariant, identifier-specific | Scope needs stable item equivalence; the identifier vocabulary may be local. |
| quantity scope | invariant | Authority is bounded by amount and sale basis. |
| agreed unit price/commercial terms | semantic invariant | The agreed meaning must survive; an opaque model may keep values server-side. Tax, freight, discount, and price decomposition are implementation-specific unless relied upon. |
| currency | invariant when monetary terms exist | Amounts are uninterpretable without it. |
| expiry | invariant when terms are time-bound | Absence must have explicit semantics; it cannot mean “forever” by accident. |
| acceptance/award state | invariant | Proposed and accepted state cannot be conflated. |
| deterministic binding | invariant | The artifact/revision must map to one evaluated result for fixed inputs. |
| authority provenance | invariant | Integrity without authorization is unsafe. |
| commitment type | invariant | Determines whether revalidation or refusal is permitted. |
| revalidation requirement | invariant | Must be explicit or derived unambiguously from commitment type. |
| invalidation reason/binding rejection | invariant result taxonomy | Needed to separate invalidity from recognized non-executability. Exact codes are provisional. |
| relationship to Business-authoritative state | invariant | The Business response is transaction state; the artifact remains evidence/input with bounded authority. |
| `bound_at` and execution/release boundary | invariant when binding precedes execution | They identify the holding interval without prescribing the operation that implements it. |
| post-bind authority rule and validity | invariant when a holding interval exists | The authority/clock relationship must be explicit; no single rule is universally required. |
| transaction lifetime | invariant at the execution boundary | It is a distinct clock from term expiry even when policy aligns their deadlines. |
| release and execution invalidation conditions | semantic invariant when used | Conditions must be declared and produce explicit outcomes; exact condition vocabulary is implementation-specific. |
| binding-unit identity, revision, included lines, atomicity, result, and replay identity | invariant for partial binding | Group composition and key format remain implementation-specific. |
| effective commercial basis of successfully bound scope | invariant for replay and later adjustment | Authoritative history must record enough per-line/unit basis to compare later accepted rules without guessing from list price. |
| negotiation messages, status names, polling interval, internal approvals, tax display decomposition | implementation-specific | Useful to the formation mechanism, but not necessary at the handoff if acceptance provenance and semantic scope survive. |

## Authority model

### Artifact validity

Validity asks whether the artifact is recognized/authentic, internally coherent, on the current revision, accepted, unexpired, issued by an authorized party, and not outside its buyer/item/quantity scope. Each failure has a distinct harness reason.

### Artifact authority

Authority answers who may originate or authorize a commercial assertion. The harness separates `issuer` from `authorized_by`. A buyer may accept an offer without gaining authority to invent the Business's price. Authentication must therefore bind content, issuer, revision, and scope—not merely the artifact id.

### Commitment semantics

- `proposed`: no accepted-term binding authority.
- `accepted_revalidate`: mutually accepted terms that the Business may revalidate against current state and reject with a classified reason.
- `business_firm`: a Business-authorized commitment that must be honored until expiry unless a declared invalidation condition occurs.

These labels belong to the harness. A future protocol could encode the distinction differently.

### Transaction authority

Only the Business creates or mutates the authoritative Cart/Checkout. Successful binding means the Business returns transaction state that reflects no more than the artifact's authorized scope. It does not allow the artifact holder to write prices, totals, fulfillment, or other state directly.

## Execution deadline and optional release

A verified accepted policy selects exactly one execution bound: `term_expiry`,
`transaction_lifetime`, or `explicit_post_bind_deadline`. The other timestamps
do not silently acquire veto authority. Selecting transaction lifetime models the
explicit transfer of commercial authority at bind; selecting term expiry retains
the original limit. All modeled paths are bounded.

Independently, `release_condition` is null or an authorized condition.
A condition requires `pending_at_deadline`: `return_to_buyer` means explicit
non-execution and return/release of held value toward the buyer;
`deemed_acceptance_to_business` means release toward the Business.
These are modeled economic instructions, not actual payment movements.
Additional dispositions need defined behavior before the harness accepts them.
Accepted `execution_invalidation_conditions` are disjoint from the lifecycle
reason namespace, so a declared condition can never be read as a lifecycle class.

The deadline is exclusive. A resolution exactly at it is late and the declared
pending disposition applies. An authenticated resolution before it governs if it
is available before a terminal outcome is applied. The harness persists the first
terminal outcome, including its application time and classification; later
evaluation of the same bound transaction reproduces it. Late evidence may support
a separate correction or dispute, but cannot rewrite the original allocation.
Persisted deadline dispositions cannot claim an application time before the
selected governing deadline. A persisted terminal outcome is not replayed blindly:
the disposition authorized by the accepted `pending_at_deadline` evidence is
derived and the persisted record is validated against it. A record conflicting
with that authorized disposition is not reproduced and does not execute; it
returns `post_bind_invalidated` with a reason naming the conflict, which stays
distinct from the absent-evidence case. Validation compares the complete
authorized semantic outcome, namely status, reason, execution, and term
preservation, not the reason label alone, so an outcome that is relabeled or has
any single semantic field altered conflicts. Application time is validated
separately as timing. A reason with no canonical authorized form, and a persisted
deadline disposition for which the accepted evidence authorizes none, both
conflict rather than replaying unchecked. Correction and dispute processing of
that conflict remains outside this harness.

Terminal finality governs replay. A persisted outcome is validated against its own
classification, its application time, its persisted authorization basis where one
is modeled, and the immutable accepted policy. It is never re-derived from a later
`execution_attempt`, whose fields describe the current attempt rather than the
evidence that authorized the stored outcome, so ordinary post-terminal state drift
reproduces the historical outcome instead of invalidating it.

Not every lifecycle result is eligible to become history. A result that describes
why a request was refused, namely an unsuccessful binding, a mismatched
transaction, incoherent lifecycle timing, incoherent release evidence, a replay
conflict, and the non-terminal pending state, is never persisted as a terminal
outcome even when it shares a status with a legitimate one. Every persisted
record is a terminal fact that the replay validator accepts and reproduces under
the same accepted policy and state. The rule is enforced on both sides: those
results have no canonical historical class, so supplying one directly as a
persisted outcome is rejected rather than replayed. The conflict reason in
particular names a verdict about an invalid record and is never itself a valid
historical classification.

Initial authorization and replay validation are separate. When a terminal outcome
is first produced, current authoritative evidence and the accepted policy must
authorize it. On replay, the record is validated from its own persisted fields,
the immutable accepted policy, and its persisted authorization basis where one is
modeled; replay reads no field of the current `execution_attempt`.

A release terminal outcome persists its authorization basis:
`release_authorization_basis` records the release result (`condition_met`) and the
release event time (`resolved_at`) that authorized it at application. Exactly the
two release classes carry a basis; any other class presenting one is not a
canonical record. Replay requires the basis to record the result its
classification claims and to cite an event inside the bound-to-exclusive-deadline
window that occurs no later than the outcome's application time. A missing, contradictory,
or out-of-window basis fails closed. This is what allows a release outcome to be
both authorized when created and final afterwards: later attempts may omit or
contradict the release fields without rewriting it.

Immutability is an assumption of the trusted Business-store model, not something
this harness enforces. JSON Schema constrains a record's shape, never its
mutation over time; history here is supplied as a trusted store snapshot. The
basis is also not separately authenticated, so it is not independently
tamper-proof: it is trusted to the same degree as the terminal record carrying it.

`resolved_at` is the release EVENT time. The harness models no observation or
delivery time, so the check establishes that the cited event occurs no later
than application;
it does not prove the evidence was available to the evaluator before application.
That remains an explicit out-of-scope limitation rather than a guarantee.

`terminal_outcome` is otherwise trusted as authoritative Business-store history.
For classes that retain no authorization basis, namely ordinary execution,
deadline elapse, declared invalidations and terms reinterpretation, replay checks
canonical shape, policy compatibility and timing, then trusts the persisted
classification. The boundary is precise: replay detects an internally
inconsistent or policy/timing-incompatible persisted terminal record, including a
release record whose classification disagrees with its own basis. It does not
detect coherent replacement of the entire trusted terminal record together with
its authorization provenance. A policy declaring a condition as
execution-invalidating establishes that such an event could invalidate execution;
it does not establish that the event occurred when the outcome was applied.
Modeling provenance for those classes would make such substitution detectable and
is left to implementation work.
`release_resolved_at` records event time; future or pre-bind evidence rejects, so
an event or application exactly at `bound_at` is valid while anything earlier is
not. First-time evaluation and replay share that inclusive lower bound, and the
governing deadline remains exclusive on both sides.
Without a condition, execution at or after the deadline rejects. With a pending
condition before the deadline it remains pending; at or after the deadline it
cannot remain pending. `release_pending` is not terminal.

Declared execution invalidations and term preservation are checked independently.
An ordinary drift event cannot invalidate a firm commitment unless authorized.
The harness assumes release evidence and the bound policy are authenticated
Business/transaction facts; it does not implement their trust transport.

## Binding units, commercial coupling, and attempts

Binding units remain the general abstraction; a one-line unit is a special case.
The accepted artifact's `binding_authorization.groups` fixes membership and
atomicity. Requests cannot split groups or move lines, even using new attempt ids.
The harness implements all-or-nothing within a unit and partial success across
units. Fulfillment independence does not imply commercial independence.

An accepted `contraction_rule` makes the commercial relationship explicit:
`fixed_prices` preserves prices; the small `unit_count_tier` example chooses
the highest accepted minimum-unit threshold satisfied by effective bound units.
It emits the resulting prices explicitly. No matching threshold rejects the
commercial basis. A missing rule or failed adjustment verification rejects
contracted scope. This table is an example fixture, not a general pricing language.
Successful attempt history records the effective per-line prices at binding. If a
later accepted tier changes what is owed on already-bound scope, the historical
prices remain visible and the result emits explicit adjustments with previous
basis, new basis, and accepted authorization source. The accepted rule itself is
sufficient authority; a new revision is not invented. Missing historical basis or
an adjustment not covered by that rule fails closed.

Each applied adjustment is appended to its own history rather than rewriting the
bind-time price, and records the artifact/line, previous and new basis, triggering
attempt, tier row, and revision. The current commercial basis is derived as the
bind-time basis plus that applied history, and evaluation compares against the
derived current basis, not the original bind-time price. An adjustment whose
triggering attempt, tier row, and revision are already recorded is treated as
already applied under that single canonical identity: it is neither rejected,
re-persisted, nor re-emitted, provided the single persisted record for that
identity carries the effect the transition authorizes; a same-key record with a
different effect, or one identity recorded twice, is contradictory history. The
chain is scoped to one artifact revision, so records belonging to another
revision remain in the append-only store without joining this chain. Within the
chain, every record must name a line the reconstructed bound basis contains: the
producer emits an adjustment only for a line whose authoritative attempt history
records it as bound, and that history is append-only across cycles just as the
adjustment store is, so a same-revision record for any other line is orphaned
history no lifecycle operation could have produced. No record may be a no-op
either, since the producer skips a line whose basis already equals the authorized
price. Those two rules also reject a repeated transition identity, which must
either restate its predecessor's move or collapse into a no-op to chain at all. Every persisted record must also be consistent with producer output. Its tier
row must exist in the accepted rule, its new basis must be that row's authorized
price, its recorded `effective_unit_count` must select exactly that row as the
highest accepted threshold satisfied, its `authorization_source` must be the
accepted tier authority, and its triggering attempt must be either the attempt
newly binding scope now or an authoritative successful bound attempt for the same
revision. A structurally linkable record whose derived price happens to match
today's target is rejected without that provenance.

Three facts about the recorded count are checked separately, because none can be
inferred from the others. Tier and price validation proves the count selects the
economic effect the record states. The realized bound proves that count could
actually have been reached by authoritative binding state, which prices cannot
show: accepted tier prices need be neither unique nor monotonic, so a fabricated
count may select exactly the price the true count selects. The minimum of two
proves the producer had both previously-bound scope and a different newly-binding
unit; that minimum is expressed statically in the schema and re-checked
semantically, since a caller may bypass schema validation. Authoritative
successful bound history is itself validated against the accepted binding
authorization before anything consumes it, so realized effective units remain a
subset of the accepted binding units. Occupying an attempt id and successfully
binding accepted scope are separate facts: raw attempt history answers the first,
so a malformed record sharing a current attempt id still yields the established
request-level idempotency conflict, while only records matching the accepted
authorization enter the validated projection every commercial and provenance
consumer reads. Preserving that conflict never authenticates the conflicting
record as a valid successful bind, and a malformed record the request does not
replay remains structural invalidity.

Stored adjustment history is validated on its own terms whenever a same-revision
chain exists and both histories are available, using that validated projection
rather than what the current request reconstructed. A stale, rejected or
idempotency-conflicting request therefore neither hides genuinely corrupt history
nor makes valid history look corrupt; it simply returns its own request-level
outcome. Request-relative state still decides which units are already bound or
newly binding and whether a new transition is emitted.

Where the current transition is partially persisted, the request does carry
enough information to check it. One evaluation may newly bind several units, so
the count a record may claim is bounded by the union of validated historical
binding units and every unit this evaluation makes effective, not by a fixed
increment. The only in-flight trigger a record may cite is the attempt the
producer would itself select, so an already-bound, stale or rejected unit cannot
supply one.

That union is the whole of what corroborates a count. The accepted scope is never
substituted for it: the artifact's size says what could theoretically exist, not
what authoritative state has established. When an evaluation makes no unit
effective, the union is validated history alone, so a record claiming a count
history has not reached fails closed even though the artifact is large enough to
hold it. A transition whose adjustment was persisted but whose bound records were
not, and which no replay can reproduce, is therefore rejected rather than trusted.

An authoritative successful bound record carries the accepted binding unit's
identity, its exact line membership, the expected target transaction, and an
effective-price map whose key set is exactly those bound lines, so every consumer
may treat that map as the authoritative bind-time basis for that scope. The
accepted tier rule must also name each threshold once; that is a property of the
accepted policy, checked whether or not the current request exercises pricing.

Every record in a same-revision chain is checked against the authoritative
bind-time basis, independent of what the current request reconstructed: its line
must exist in that basis, it must not be a no-op, and its previous basis must
equal the running basis immediately before it. A cited trigger must be either a
validated authoritative successful binding attempt or the in-flight trigger the
current transition selects; having no in-flight trigger is not permission for an
unknown one. Whether a stored chain is orphaned is
judged from that authoritative history rather than from the current request, so a
stale or conflicting request cannot make valid stored history look corrupt. The recorded count must also never decrease across
append-only history, since no unbind is modelled, and stay consistent across every
record sharing one triggering attempt, which cannot claim two transition contexts,
and conversely one effective count identifies one triggering attempt, since a
single adjustment-producing evaluation chooses one of each. Several line
adjustments from that transition share both. Counts need not be contiguous; an
evaluation may legitimately jump from one to three.
A record matching the transition being replayed must record that transition's own
count, even where two counts would select the same tier at the same price.

Historical adjustment validation establishes structural, tier-selection, price,
trigger-existence, and cross-record transition-context consistency. The association between a historical trigger
attempt and the transition count it records is trusted because attempt ordering
is not retained. Re-pointing a record to a different real successful attempt
whose transition context is unchanged is therefore not detectable, and adjustment
history is not fully independently reconstructed producer output. Derivation consumes authoritative history in its
recorded order and requires each adjustment to link to the running basis; history
is never sorted or reordered to repair a broken chain. History that is present but
cannot form a valid append-only chain is immutable structural invalidity rather
than a transient outage, so it fails closed as an invalid artifact projection and
is not reported as retryable. A current
basis that already equals the authorized price requires no transition. Missing
authoritative commercial-basis history, meaning history that cannot currently be
obtained, fails closed exactly as an unavailable attempt history does and stays
retryable, without implying an invalid artifact or a new authorized transition;
history that exists and contradicts either the bound scope or its own chain is
separate evidence of invalidity.

The Business maintains attempt history keyed by `attempt_id`, separate from
artifact identity/revision. At most one successful record may exist for a given
binding identity, since accepted scope cannot bind twice; two such records are
corrupt history rather than idempotent replay. Each record binds unit membership
and target, and a
successful record also binds its effective commercial basis. Replaying an attempt
preserves its recorded success/failure. Recovery follows ownership: an
`idempotency_conflict` requires a new attempt id under the same valid revision;
`line_unavailable` permits a fresh attempt under that revision;
`attempt_history_unavailable` permits the same attempt later after service
recovery; and structural/authorization failures require a new authorized
transition. Already-bound units return no new scope even on a fresh attempt.
Missing authoritative history fails closed without calling the artifact invalid.

History is supplied as a trusted Business-store snapshot in this harness. Revision
content is immutable and verification booleans attest the complete accepted
group/rule projection, not merely a party name. A changed rule requires fresh
authorization; tests that vary an accepted rule model different authorized inputs.
Checking those attestations cryptographically, storing attempt results atomically,
and coordinating simultaneous requests remain implementation work.

## Evaluation order

1. Resolve/recognize and authenticate.
2. Verify issuer authorization and internal coherence.
3. Verify current revision, acceptance, and expiry.
4. Compare buyer, item, quantity, currency, and requested terms to accepted scope.
5. Apply commitment semantics:
   - `accepted_revalidate`: run declared/current Business checks; a failure is `recognized_rejected`.
   - `business_firm`: honor unless a declared invalidation condition is present.
6. If binding units are present, evaluate each declared atomic group and return every unit result; do not infer per-line severability.
7. Return authoritative Cart/Checkout state or a classified non-binding/partial result, correlated to artifact id and revision.
8. During any holding period, apply the selected execution deadline and independent release policy at the execution/release boundary.
9. Execute/release without changing agreed terms, or return an explicit pending, failed-release, or post-bind-invalidated result.

This order ensures a recognized Business rejection is not misreported as forgery or expiry, a firm commitment is not silently downgraded to advisory terms, and a successful bind is not mistaken for final execution.
