# UCP #845 — architectural placement decision matrix (review package)

**Status:** candidate analysis for [UCP Enhancement Proposal #845](https://github.com/Universal-Commerce-Protocol/ucp/issues/845); **not** approved UCP language, a normative conformance suite, or a claim of independent adoption.

**Decision requested:** Should accepted/awarded commercial artifacts entering Business-authoritative Cart/Checkout use **B — fully domain-specific semantics** or **C — minimal shared invariants with extension-specific carriers**? Option C is recommended for the *observable boundary guarantees* below, not for a universal term-artifact object.

## Exact boundary

`external formation -> accepted/awarded revision -> Business binding -> transaction execution`

This package excludes unaccepted/provisional observations, negotiation strategy, quote issuance APIs, pricing algorithms, payment settlement, and vendor-specific domain fields. A quotation that is merely issued or signed is **not automatically an accepted artifact**. The author of #929/PR #930 and the author of #845 are different contributors; #929 is a possible price-only carrier, not an implementation or adoption of #845.

## Minimum cross-carrier decision matrix

| Observable question | Option B: domain-specific contract | Option C: shared minimum, domain-specific carrier | #845 recommendation / counterexample |
|---|---|---|---|
| What artifact and revision entered the binding attempt? | Each extension decides identification and revision interpretation | A carrier must preserve applicable accepted/awarded identity and revision; concrete identifiers remain domain-owned | **C.** Avoid replay silently selecting a replacement revision |
| Which commercial actor authorized the terms, and for what scope? | Each domain defines its own issuer/authorization/scope semantics | Do not infer authority merely from signature, issuer identity, reference possession, or buyer acceptance; no silent expansion beyond accepted scope | **C.** Business remains authoritative for Cart/Checkout, but must evaluate the external authorization boundary |
| Is the artifact recognized, binding, or revalidatable? | Status and expiry semantics vary independently | Distinguish recognized-but-revalidatable terms from firm commitments where that distinction changes executable behavior; validity and authorization are different predicates | **C.** See **Case A** |
| What happens when binding cannot honor the artifact? | Each extension invents its own rejection semantics | Preserve an observable difference between recognized-but-unexecutable terms and invalid/unknown/stale artifacts; no silent replacement of material commercial basis | **C**, without prescribing one cross-domain error-code enum |
| When does an accepted quote expire relative to Checkout? | Domain decides its clocks and transitions | Make issuance validity, binding, post-bind policy, withdrawal and transaction lifetime independently decidable; acceptance alone need not prolong issuance validity | **C.** See **Case B**; the accepted rules determine results |
| Can binding be retried without duplicate effects? | Each domain defines attempt/revision handling | Preserve distinction between artifact revision, binding-attempt identity and already-authoritative bound result; don't duplicate scope or reinterpret revisions on replay | **C** at semantic level; no universal idempotency field mandated |
| Must per-line price, cancellation terms or lodging entitlement use one common schema? | Domain-specific | **Domain-specific under C as well**; common rule is to preserve any material authorized basis and make changes explicit | Do **not** make #845 a shopping quote or lodging spec |
| Does C require a new core operation? | No | No. Extension-specific carriers and capability negotiation suffice if the TC selects C | No core-schema change requested |

### Decision criteria for Shopping TC

Choose **C** if independently developed carriers must communicate the same minimum outcomes to a Platform without interpreting private business logic. Choose **B** if the TC determines those guarantees have no cross-domain interoperable meaning and each domain can safely define them alone. Either answer should identify the accountable Technical Council and next review milestone. Do not infer a decision from #929's progress.

## Two candidate negative cases (existing harness; not new UCP wire cases)

Run:

```sh
python3 -m unittest discover -s tests -v
python3 tests/test_vectors.py --matrix
```

The new tests live in `tests/test_architecture_decision_845.py`. They reuse frozen vector identities instead of modifying V1–V7 or increasing the schema's vector count.

### Case A — recognized, non-binding/revalidatable quotation fails at binding

**Inputs:** V6: accepted, authentic, issuer-authorized, unexpired revision with `accepted_revalidate` commitment; Business's revalidation fails after state change.

**Expected for this harness:** `recognized=true`, `artifact_valid=true`, `bindable=false`, `recognized_rejected/business_revalidation_failed`. Contrast an altered commercial-terms request, classified as `invalid_artifact/commercial_terms_mismatch`, and a forged artifact, classified separately. V7 is the firm-commitment control: unrelated revalidation failure alone does not invalidate the firm's commitment.

**Safety requirement under consideration:** A Business may refuse a recognized revalidatable artifact, but cannot represent the refusal as successful binding or silently substitute a different authorized commercial basis. This case **does not prove** that a non-binding quotation was already buyer-accepted in AirShelf's actual implementation: AirShelf explicitly reports **no separate acceptance state** or implemented `accepted_id`. V6 is a candidate accepted-term scenario derived from existing harness semantics, not a claim about AirShelf protocol messages.

### Case B — buyer acceptance vs binding before/after original issuance expiry

**Pre-bind control V5:** Buyer accepted a firm quotation before its recorded expiry, but first **binding attempt** is after expiry. This harness classifies it `invalid_artifact/expired`. This is a candidate expiry policy, **not** a universal rule that buyer acceptance never extends binding authorization: a future carrier could explicitly authorize a different lifetime.

**Post-bind V9:** Buyer accepted and the Business **bound** the commercial terms before the recorded issuance expiry; the downstream conditional-release evaluation occurs after issuance expiry but before the Checkout transaction lifetime ends. The accepted `transaction_lifetime` policy governs that stage; the release condition fails, the transaction does not execute, and already-bound terms remain preserved. **Do not call this successful Checkout completion:** it is a post-bind release failure, included to isolate the clock boundary. Re-scheduling binding itself to after issuance expiry fails the pre-binding gate.

**Safety requirement under consideration:** Accepted-but-not-bound, bound-but-not-executed, and executed are distinct states. The issuance-expiry timestamp cannot silently override an independently authorized post-bind policy, nor should buyer acceptance alone be interpreted as a binding effect.

## Source and evidence discipline

- [#845](https://github.com/Universal-Commerce-Protocol/ucp/issues/845) was opened September 19, 2026 by `arjun2075`. The narrower [#929](https://github.com/Universal-Commerce-Protocol/ucp/issues/929) and [draft PR #930](https://github.com/Universal-Commerce-Protocol/ucp/pull/930) were opened October 11, 2026 by `isparsh510` and explicitly reference #845 as architectural context.
- [AirShelf's November 1 feedback on #929](https://github.com/Universal-Commerce-Protocol/ucp/issues/929#issuecomment-6554965470) describes **internal tests and demos**, not production quote deployment or an accepted-term carrier. It provides independent boundary-design feedback but does not establish adoption of #845.
- [Lodging #991](https://github.com/Universal-Commerce-Protocol/ucp/issues/991) provides a related domain example: changing rate plans may change cancellation terms independently of subtotal. It does not cite or implement #845.
- The harness model codes, policies, names and `recognized_rejected` labels are **illustrative**. A UCP-native carrier and conformance cases require a Technical Council architecture decision, normative text and independent implementation review.

## Review and follow-up

1. Review the four minimum shared guarantees: **identity/authority/scope, commitment/validity, binding outcomes/material basis, retry/lifecycle**.
2. Resolve **Option B vs Option C** on #845, expressly without making #929 the default shared model.
3. If **C**, translate these two negative cases into carrier-specific UCP conformance vectors only after adopting field semantics and a capability identifier.
4. Preserve existing V1–V14 and the open PR #1 lifecycle/retry review; this package is intended as a stacked, isolated review diff.
