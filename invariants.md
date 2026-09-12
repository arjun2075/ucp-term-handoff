# Boundary model and candidate invariants

## Status and terminology

The statements below are **candidate invariants derived from current implementation evidence**. Uppercase key words express the behavior tested by this artifact; they are not normative UCP requirements.

- **Term artifact**: durable output of a quote, RFQ, negotiation, award, or other term-formation mechanism.
- **Binding**: the Business evaluates that artifact and returns authoritative Cart/Checkout state or a classified rejection.
- **Recognized**: the Business can resolve or authenticate the artifact. Recognition does not imply that it is valid, executable, or authoritative.
- **Transaction authority**: the Business remains authoritative for creation and mutation of its UCP Cart/Checkout. A term artifact only carries its declared commercial authority within its accepted scope.

## Four independent questions

1. **Integrity / preservation** — Did the same artifact, revision, parties, scope, terms, acceptance, and validity window arrive?
2. **Authority provenance** — Who issued or authorized those commercial terms, and can the Business verify that fact?
3. **Commitment semantics** — Is this a proposal, mutual acceptance subject to revalidation, or a Business-issued firm commitment?
4. **Revalidation / invalidation** — Which binding-time checks are allowed, and how is a recognized-but-non-executable artifact distinguished from an invalid one?

Passing one question does not answer another. In particular, a byte-perfect portable artifact can be unauthorized, and an authentic unexpired artifact can be non-executable when its declared commitment permits revalidation.

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

## Evaluation order

1. Resolve/recognize and authenticate.
2. Verify issuer authorization and internal coherence.
3. Verify current revision, acceptance, and expiry.
4. Compare buyer, item, quantity, currency, and requested terms to accepted scope.
5. Apply commitment semantics:
   - `accepted_revalidate`: run declared/current Business checks; a failure is `recognized_rejected`.
   - `business_firm`: honor unless a declared invalidation condition is present.
6. Return authoritative Cart/Checkout state or a classified non-binding result, correlated to artifact id and revision.

This order ensures a recognized Business rejection is not misreported as forgery or expiry, and a firm commitment is not silently downgraded to advisory terms.
