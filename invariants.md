# Boundary model and candidate invariants

## Status and terminology

The statements below are **candidate invariants derived from current implementation evidence**. Uppercase key words express the behavior tested by this artifact; they are not normative UCP requirements.

- **Term artifact**: durable output of a quote, RFQ, negotiation, award, or other term-formation mechanism.
- **Binding**: the Business evaluates that artifact and returns authoritative Cart/Checkout state or a classified rejection.
- **Bound transaction**: authoritative Cart/Checkout state that records a successful binding. It is not necessarily executed, completed, settled, or released.
- **Binding unit / atomicity group**: one or more accepted lines whose commercial dependencies are evaluated together. Partial success is permitted across independent units, not by silently splitting a unit.
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
| I14 | Post-bind semantics MUST state whether commercial authority survives, transfers into transaction state, or remains conditional until execution. | State drift cannot silently choose the authority model. |
| I15 | The relationship between term expiry and transaction lifetime MUST be explicit. | The rule may transfer authority at bind, continue term expiry, establish a separate deadline, or use conditional release; ambiguity is invalid. |
| I16 | Scope contraction MUST NOT be silent. | Omitted accepted scope is rejected or reported as an explicit failed binding unit. |
| I17 | Partial success MUST identify independent binding units and their results. | Artifact-wide success cannot hide failed units; artifact-wide failure need not discard successful independent units. |
| I18 | Cross-line commercial dependencies MUST have declared atomicity semantics. | A volume, bundle, minimum, freight, or threshold group binds as declared or rejects explicitly. |
| I19 | Retry MUST be idempotent at binding granularity. | Replay identity covers artifact, revision, binding unit, its lines, and target transaction; successful units are not duplicated, group membership cannot move, and a prior failure cannot become success without a new authorized transition. |
| I20 | Conditional release MUST preserve agreed commercial terms. | Intermediate drift or a failed release condition cannot silently reprice; non-release is explicit. |

I13–I20 are candidate semantics prompted by Weston's lifecycle and partial-binding review. They do not revise I1–I12 or claim current UCP requirements.

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

## Dual clocks and post-bind authority

Term expiry and transaction lifetime are different clocks. The harness does not select a universal relationship. A binding profile must explicitly choose semantics such as:

- authority transfers into the bound transaction at `bound_at`;
- original term expiry continues to constrain execution;
- a separate post-bind deadline controls execution; or
- commercial terms lock while execution/value movement waits on a release condition.

The unsafe case is not any one choice; it is leaving the choice implicit. Any execution invalidation allowed after binding must be declared, must preserve the historical bound terms, and must return an explicit non-execution result rather than a repriced transaction.

## Binding units and partial success

A binding unit is a harness abstraction, not necessarily one line. Its membership is chosen by the commercial semantics: a single independent line may be one unit, while a volume tier, minimum order, bundle, shared freight basis, or threshold discount may require several lines in one unit. The initial vectors use `all_or_nothing` within a unit. They do not prescribe one grouping strategy across implementations.

Each unit records a group id, accepted revision, included line ids, atomicity mode, result, target transaction, and replay identity. Partial success is valid only across independent units. A failed unit remains visible; its lines are not silently dropped. Replay identity is logically scoped to artifact identity + revision + binding unit membership + target transaction, without prescribing a serialized key format. Replaying a prior failure reproduces that failure; success requires a new authorized state transition rather than reuse of the same attempt identity.

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
8. During any holding period, apply the declared authority and dual-clock rule at the execution/release boundary.
9. Execute/release without changing agreed terms, or return an explicit pending, failed-release, or post-bind-invalidated result.

This order ensures a recognized Business rejection is not misreported as forgery or expiry, a firm commitment is not silently downgraded to advisory terms, and a successful bind is not mistaken for final execution.
