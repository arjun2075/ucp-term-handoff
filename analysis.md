# Results and review recommendation

This independent analysis harness now has fourteen executable vectors. It covers
accepted authorization → binding → execution/release, partial binding, authorized
commercial adjustment, and attempt-specific retries. All names and invariants
remain candidates; this is not an upstream UCP proposal.

## External review and derived changes

[Weston's second review](https://github.com/Universal-Commerce-Protocol/ucp/discussions/812#discussioncomment-18423514)
independently validates binding units as the general abstraction, including the
one-line special case. He identifies three defects: deadline and release were
exclusive alternatives; partial binding ignored cross-unit commercial coupling;
and retries conflated attempt identity with commercial revision.

[Weston's September 16 follow-up](https://github.com/Universal-Commerce-Protocol/ucp/discussions/812#discussioncomment-18469224)
confirms those directions while identifying three remaining correctness gaps:
deadline disposition was reversible by late evidence, bound history omitted its
actual commercial basis, and retry classification did not follow recovery owner.

Juan/Shopware supplies independent implementation evidence. Weston supplies
technical review and binding-unit validation. Arjun Garg supplies the generalized
model, binding-unit and authorized-adjustment synthesis, invariants, harness,
vectors, and analysis.

## Exact vector changes

- V1–V7 remain byte-for-byte unchanged, with SHA-256 guards.
- V8 migrates to an explicit post-bind deadline plus no release condition; its
  original inventory invalidation outcome remains.
- V9 migrates to transaction lifetime plus delivery confirmation and an explicit
  buyer-return disposition. Explicit delivery failure remains non-execution.
- V10 retains 38/40 effective bound lines and four units. Accepted membership,
  fixed-price contraction authorization, and authoritative attempt history replace
  the revision-coupled prior-binding/prior-failure fields.
- V11 retains the four-line atomic rejection. It uses the same authorized-group
  and attempt-history representation; one unavailable line still rejects all four.
- V12 adds four independently fulfillable units with an accepted whole-award tier.
  Three survive, one fails; the accepted table changes survivor unit prices from
  1000 to 1200. Replay controls record that 1200 basis; a later U4 restock emits
  explicit accepted adjustments rather than silently rewriting U1–U3.
- V13 adds pending delivery at transaction expiry with explicit non-execution and
  return toward the buyer. Its applied terminal result is persisted; both it and
  the alternative deemed-acceptance disposition resist contradictory late evidence.
- V14 adds fresh U4 attempt B after restock under revision 4; all 40 lines become
  effective, 30 new, with previously successful U1 replayed at its recorded
  commercial basis and without duplication.

## Executable matrix

| Vector | Opaque reference | Portable artifact | Semantic outcome |
|---|---|---|---|
| V1 | PASS | AMBIGUOUS | bound / bound |
| V2 | PASS | AMBIGUOUS | invalid_artifact / stale_revision |
| V3 | PASS | PASS | bound / bound |
| V4 | PASS | PASS | invalid_artifact / scope_expansion |
| V5 | PASS | PASS | invalid_artifact / expired |
| V6 | AMBIGUOUS | AMBIGUOUS | recognized_rejected / business_revalidation_failed |
| V7 | PASS | AMBIGUOUS | bound / bound |
| V8 | AMBIGUOUS | AMBIGUOUS | bound / bound -> post_bind_invalidated / inventory_allocation_changed |
| V9 | AMBIGUOUS | AMBIGUOUS | bound / bound -> release_condition_failed / release_condition_failed |
| V10 | AMBIGUOUS | AMBIGUOUS | partially_bound / partial_binding (38 effective, 2 failed) |
| V11 | PASS | PASS | recognized_rejected / binding_unit_rejected (0 effective, 4 failed) |
| V12 | AMBIGUOUS | AMBIGUOUS | partially_bound / partial_binding (3 effective, 1 failed) |
| V13 | AMBIGUOUS | AMBIGUOUS | bound / bound -> deadline_non_execution / return_to_buyer |
| V14 | AMBIGUOUS | AMBIGUOUS | bound / bound (40 effective, 0 failed) |

PASS/AMBIGUOUS/FAIL assess declared carrier capabilities, not production adapters.
The original A/B verdicts remain stable. The same evaluator executes every vector;
the scorer is an inspectable capability assessment, not empirical interoperability
proof. V12–V14 require added authoritative semantics under either carrier.

## Invariants and executable coverage

I1–I12 retain their numbering and semantics. I13, I16–I17 and I20 retain their
principles. I14–I15 now distinguish deadline source and optional release; I18
allows authorized cross-unit coupling alongside atomicity; I19 separates attempt
identity from revision. I21–I23 are new.

| Candidate | Concrete coverage |
|---|---|
| I1–I12 | Original V1–V7 and unchanged hash guards; later vectors retain authority checks |
| I13 binding differs from execution | V8, V9; execution requires successful evaluated binding |
| I14 orthogonal deadline and release | V9, V13; release success/failure/pending with each clock |
| I15 explicit enforced deadline | transaction shorter than term, explicit deadline shorter than both, exact boundary tests |
| I16 explicit contraction | V10–V12; dropped groups fail distinctly from expansion |
| I17 grouped partial success | V10, V12; every unit result accounts for accepted scope |
| I18 authorized atomic groups | V11; fresh-key membership mutation and unverified grouping controls |
| I19 attempt identity, basis, replay | V10, V12, V14; successful history records prices, same attempt replays, fresh keys add no duplicate |
| I20 term preservation on release | V9; repricing rejected, ordinary firm drift ignored |
| I21 authorized contraction/adjustment | V12; historical-basis replay, explicit accepted tier adjustment, missing/uncovered basis controls |
| I22 final deadline disposition | V13; buyer return and deemed acceptance remain final despite contrary late evidence |
| I23 recovery ownership | V14; distinct caller-id, Business-state, service-availability, and authorization recovery actions |

## Corrected semantics

Deadline selection and release are independent. The selected deadline is exclusive;
resolution exactly at it is late. An authenticated earlier resolution governs if
available before disposition. Once the first terminal outcome is applied, its time
and classification are persisted and later evaluation reproduces it; late evidence
belongs to a separate claim/correction process outside this harness. Deadline-time
pending disposition is mandatory when a release condition exists. Neither buyer
return nor deemed acceptance is a UCP default. Transaction lifetime is read when
selected; the other clocks have no implicit precedence.

Binding authorization covers both group membership and contraction rules.
Fulfillment-separable units may share an accepted tier. The harness implements only
fixed prices and a small unit-count tier example, including no-matching-minimum
rejection. Successful history records the basis actually bound. When later scope
changes the accepted tier, historical prices stay intact and explicit adjustments
identify old basis, new basis, and the accepted rule. Missing basis and adjustments
outside that rule fail closed. It does not define a pricing language.

Attempt A's recorded failure remains failed on replay. Recovery identifies who can
make progress: a conflicting id requires a fresh id, inventory recovery permits a
fresh attempt, history-store recovery permits the same attempt later, and changed
structural/commercial semantics require a new authorized transition. Authorization
is not needlessly replaced when it remains valid. Successful units remain
deduplicated even with a fresh attempt id. Attempt history is a supplied trusted
Business snapshot, not client assertions.

## Carrier comparison

| Concern | Opaque reference | Portable artifact | Derived hybrid |
|---|---|---|---|
| Deadline/release authority | Resolver/transaction must expose authoritative policy | Authenticated policy must survive normalization | Can compare both views; still needs lifecycle enforcement |
| Pending disposition | Business must declare and persist terminal outcome | Must carry authorized outcome with condition | No automatic choice or universal default |
| Adjustment authorization | Native accepted rule and bound basis can be resolved | Rule, affected scope, and historical basis must be verifiable | Comparison helps detect mismatch; not a pricing language |
| Cross-unit pricing/freight | Native detail retained | Lossy normalization must reject | Does not remove normalization risk |
| Attempt history | Durable Business store | Portable ids cannot replace storage | Reference locates storage but still needs atomic deduplication |
| Origin outage during retry | Defer/fail closed if history unavailable | Artifact alone cannot establish no previous success | Fresh cached state requires a declared trust/freshness policy |

No carrier uniquely solves these problems. In particular, a hybrid remains
AMBIGUOUS for V8–V10 and V12–V14 without execution and attempt-store contracts;
V11's atomicity can be represented once authorization is established.

## Audit record

The semantic pass checks orthogonality, final deadline disposition, authoritative
historical basis, explicit authorized adjustment, recovery ownership, and
commitment preservation. The first applied terminal result is immutable, accepted
groups constrain retry membership, and outages no longer imply artifact defect.

The adversarial pass exercises contradictory late evidence after both deadline
dispositions, pre-disposition evidence, every clock source, V12 replay at 1200,
restock adjustment to 1000, missing and uncovered historical basis, caller-id
conflict, inventory recovery, history-store recovery, structural failures, changed
grouping, and prior successful scope.

Schema validation applies to all vectors; complete matrix output is compared
verbatim with this document. Legacy hashes and attribution hygiene remain guarded.
Final verification: 69/69 tests pass, all 14 vectors validate, all 16 JSON files
parse, the Draft 7 schema validates, V1–V7 hashes are unchanged, and
`git diff --check` passes. The semantic and adversarial audit checks are in
`tests/test_review.py`; the original regression checks remain in `tests/test_vectors.py`.
Timeline/events are explanatory evidence, not an event-sourced production engine.
Verification flags stand for trusted full-content authorization, not a cryptographic
implementation. Attempt history is not persisted or locked by this harness.

## Remaining review questions and maturity

- Are exclusive deadline boundaries and late observation of verified earlier
  resolutions the intended semantics?
- What proves release event time and the authority of pending disposition?
- Which additional contraction policies are useful without a universal pricing language?
- Which explicit adjustment forms beyond the accepted unit-count tier are needed?
- Where should durable attempt history live, and what isolation guarantees prevent
  simultaneous binds from duplicating scope?
- How should history replay after expired/superseded authorization be exposed?
  Current admission checks fail closed before fresh binding; historical lookup is
  a separate operation not implemented here.
- Which structural failures can recover through an authorized transition without
  issuing a numerically new commercial revision?

Ready for an open review PR and a discussion reply pointing to its diff.
Leave the PR open pending external review. A vendor experiment is not started.
A UCP proposal or upstream PR is premature. Every requested class is represented;
authentication, payment movement, persistent/concurrent attempt storage, and
additional economic dispositions remain explicitly outside this analysis harness.
