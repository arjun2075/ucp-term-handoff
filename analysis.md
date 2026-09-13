# Results and review recommendation

## Result summary

The eleven vectors now cover two boundaries:

1. accepted terms → authoritative Cart/Checkout binding (V1–V7); and
2. bound transaction → execution/release, including grouped partial binding (V8–V11).

The original conclusion remains: preservation, authority provenance, commitment semantics, and revalidation are independent. The extension adds two more independent concerns: post-bind lifecycle semantics and binding-unit atomicity/idempotency. “Bound” is not synonymous with “executed,” and “partial” is meaningful only when the accepted commercial scope declares independent units.

## What Weston's review validated

Weston's [latest #812 review](https://github.com/Universal-Commerce-Protocol/ucp/discussions/812#discussioncomment-18414304) confirms that I7–I11 match the authority problem and that separating `issuer` from `authorized_by` makes the no-authority-escalation check mechanically verifiable. This revision preserves those invariants and V1–V7 byte-for-byte.

The review identified two gaps in the single-evaluation assumption behind I12:

- state can drift after successful binding but before execution, while term expiry and transaction lifetime may be different clocks; and
- artifact-wide results cannot safely represent partial success, but naïve per-line binding breaks cross-line commercial dependencies.

## What V8–V11 add

- **V8 post-bind drift:** a valid artifact binds, then a declared execution condition changes. The result is `post_bind_invalidated`, not silent repricing and not retroactive artifact invalidity.
- **V9 conditional release:** commercial terms lock at binding while settlement waits for delivery confirmation. Drift does not reprice; a failed condition produces `release_condition_failed`.
- **V10 independent units:** a 40-line award has four independent binding units. Three units covering 38 lines are effectively bound, including one idempotent replay; the two-line failed unit is explicit and remains failed on replay without a new transition. No line disappears silently.
- **V11 atomic group:** four lines share bundle/volume/freight semantics. One unavailable required line rejects the whole unit, proving that per-line binding is insufficient.

## Executed model matrix

`PASS` means the bare model's declared mechanisms are sufficient for the property exercised. `AMBIGUOUS` means additional semantics are required. `FAIL` means a declared bare-model capability contradicts a required property. The scorer computes this table from `models/model-capabilities.json` and each vector.

| Vector | Opaque reference | Portable artifact | Semantic outcome |
|---|---|---|---|
| V1 normal accepted RFQ | PASS | AMBIGUOUS | bound |
| V2 async counter / stale revision | PASS | AMBIGUOUS | invalid: stale revision |
| V3 human approval | PASS | PASS | bound |
| V4 scope mutation | PASS | PASS | invalid: scope expansion |
| V5 expiry | PASS | PASS | invalid: expired |
| V6 Business rejects at binding | AMBIGUOUS | AMBIGUOUS | valid + recognized, but rejected |
| V7 modeled firm commitment | PASS | AMBIGUOUS | bound despite unrelated pre-bind drift |
| V8 post-bind state drift | AMBIGUOUS | AMBIGUOUS | bound, later post-bind invalidated |
| V9 conditional release | AMBIGUOUS | AMBIGUOUS | bound, release condition failed |
| V10 partial independent units | AMBIGUOUS | AMBIGUOUS | 38/40 effectively bound; two explicitly failed |
| V11 atomic group rejects | PASS | PASS | complete binding unit rejected |

The new vectors do not force a hybrid winner. They show that every carrier needs additional authoritative transaction-lifecycle semantics for V8–V9 and unit-granular binding/idempotency semantics for V10. Both models can preserve an authoritative atomic grouping in V11.

## Revised candidate invariant set

All statements are **candidate invariants derived from implementation and review evidence**, not current UCP requirements.

| Range | Candidate invariants |
|---|---|
| I1–I5 | Preserve identity, current revision, bounded scope, expiry, and acceptance provenance. |
| I6–I11 | Separate validity from executability; expose issuer/authorization and commitment; prevent authority escalation; represent permitted rejection; preserve modeled firm commitments. |
| I12 | Make binding deterministic for fixed artifact revision, request, Business state, and evaluation time. |
| I13–I15 | Separate binding from execution; declare post-bind authority; make the term-expiry/transaction-lifetime relationship explicit. |
| I16–I18 | Forbid silent contraction; permit partial success only through explicit independent units; preserve cross-line atomicity. |
| I19 | Make retries idempotent at artifact + revision + binding unit membership + target transaction granularity. |
| I20 | Conditional release preserves agreed terms and reports non-release rather than silently repricing. |

The normative-style detail and test consequences are in `invariants.md`.

## Invariant coverage matrix

| Candidate | Covered by |
|---|---|
| I1 identity | V1, V2, V3, V8 |
| I2 revision | V1, V2, V10 |
| I3 no scope expansion | V1, V4, V10 |
| I4 expiry | V1, V2, V5 |
| I5 acceptance provenance | V1, V2, V3 |
| I6 validity ≠ executability | V6, V7, V8 |
| I7 authority provenance | V1, V3, V6, V7 |
| I8 commitment type | V1, V5, V6, V7, V8, V9 |
| I9 no authority escalation | V1, V4, V6, V7 |
| I10 classified revalidation rejection | V6 |
| I11 modeled firm commitment | V5, V7, V9 |
| I12 deterministic binding | V1–V8, V10, V11 |
| I13 binding ≠ execution | V8, V9 |
| I14 post-bind authority explicit | V8, V9 |
| I15 dual clocks explicit | V8, V9 |
| I16 no silent contraction | V10, V11 |
| I17 explicit partial success | V10 |
| I18 cross-line atomicity | V10, V11 |
| I19 unit-granular idempotency | V10 |
| I20 conditional release preserves terms | V9 |

## Result taxonomy

Binding-time artifact/result distinctions remain: malformed, unknown, forged, unauthorized issuer, identity mismatch, stale, not accepted, expired, scope expansion, scope contraction, currency/term mismatch, revalidation failure, firm-commitment invalidation, partial binding, and binding-unit rejection.

Post-bind distinctions add: bound but not executable, release pending, release-condition failure, post-bind invalidation, and executed. Binding-unit results add: bound, rejected, and idempotent replay/already bound. Names are provisional and describe the harness, not proposed wire codes.

## Model comparison after the new cases

| Concern | Opaque reference | Portable artifact | Derived hybrid |
|---|---|---|---|
| post-bind authority | Business may know it internally; reference alone does not expose it | Rule can travel; artifact cannot enforce transaction state | Can compare declared rule with Business state, but still needs lifecycle semantics |
| continued origin dependence | Natural to re-resolve, with availability cost | Must declare whether offline execution is authorized | Makes dependency explicit; does not remove it |
| origin unavailable at release | Fail/defer unless authority transferred or cached resolution is explicitly valid | Structural checks continue; authority/currentness may be indeterminate | Behavior depends on declared transfer/release rule |
| partial binding | Requires grouped Business results | Can expose group membership/results | Useful combination, but server still owns authoritative results |
| atomicity declaration | Native resolver state can preserve dependencies | Group and conditions must be integrity-bound | Can compare portable projection with native group |
| retry recognition | Business must deduplicate per unit/target | Replay identity can travel but cannot self-enforce | Same server-side requirement |

## Unresolved questions

1. Which post-bind rule is appropriate for which commitment: authority transfer, continued term expiry, separate deadline, conditional release, or another declared model?
2. Which component is authoritative for execution/release events, and what happens when that component or the quote origin is unavailable?
3. What minimum transaction state machine represents bound-not-executable, release pending/failure, invalidated, and executed without overfitting Checkout?
4. How are binding units declared and authorized when their membership reflects volume, bundle, threshold, freight, or contractual dependencies?
5. Can a failed unit later succeed under the same artifact revision, or must recovery always be a new authorized transition/revision?
6. How should a transaction expose effective bound scope versus newly bound scope on idempotent replay?
7. What trust mechanism proves issuer authorization for portable artifacts and their post-bind/atomicity declarations?
8. Must supersession be checked online, or can bounded lifetime and offline-verifiable commitments suffice in some profiles?
9. Where do binding and release operations belong: Cart, Checkout, a separate pre-Checkout resource, or a transaction extension?

## Maturity assessment

| Next artifact | Ready? | Basis |
|---|---|---|
| another #812 discussion comment | **Yes** | Eleven executable vectors now expose both gaps and invite review of concrete semantics. |
| vendor-namespaced experiment | **Not yet started; design is ready to scope** | The next review should first challenge dual-clock choices and group/idempotency semantics. |
| UCP proposal | **Not yet** | Lifecycle placement, release authority, recovery transitions, and group authorization remain unresolved. |
| upstream PR | **No** | No protocol shape or maintainer direction is agreed. |

## Recommended next step for #812

Link this revision and ask reviewers to attack the declared lifecycle and grouping boundaries: whether V8's post-bind invalidation is allowed under the stated commitment, whether V9 cleanly separates release failure from repricing, whether V10's grouping and replay identity are sufficient, and whether V11 captures the right atomic rejection behavior. Do not start a schema proposal or implementation until those semantics survive review.

## Proposed #812 update (do not post)

> Weston, I extended the artifact to cover both gaps you identified without changing V1–V7. V8 now models a successful bind followed by pre-execution state drift, with the term-expiry/transaction-lifetime rule made explicit. V9 models the alternative you named: fixed commercial terms with execution or settlement gated by a declared release condition, where condition failure is explicit and does not reprice.
>
> For partial binding, I did not make lines universally severable. V10 groups a 40-line award into four independent all-or-nothing binding units: 38 lines are effectively bound, two fail explicitly, and replay of an already-bound unit adds no duplicate lines. V11 puts several commercially dependent lines in one atomic unit and rejects the whole group when one required line is unavailable.
>
> The new invariants cover binding versus execution, explicit dual-clock/post-bind authority, no silent contraction, grouped partial success, cross-line atomicity, unit-granular idempotency, and term-preserving conditional release. The model comparison still does not force a hybrid: both carriers need added transaction-lifecycle and binding-operation semantics.
>
> Could you challenge the lifecycle and atomicity choices specifically—especially whether the four post-bind authority modes are distinct enough, whether a failed unit requires a new artifact revision before later success, and whether the replay identity has the right semantic inputs?
