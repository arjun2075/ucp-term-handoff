# Results and review recommendation

## Result summary

The vectors support neither “accepted always means executable” nor “the Business may always revalidate.” The decisive semantic is the declared commitment:

- `accepted_revalidate` permits a valid, recognized artifact to be rejected because current Business conditions fail (V6).
- Under this harness's modeled `business_firm` semantics, the Business is obligated during the validity window unless an explicitly declared invalidation condition applies (V7). This is not asserted as current UCP behavior.

Both bare handoff representations need more than a carrier. An opaque reference needs a portable binding-result contract and hides preflight semantics. A portable artifact needs content-bound authenticity, issuer authorization, and revision freshness. This points to a hybrid as a useful experiment, but the evidence does not yet establish that a hybrid is the only acceptable protocol shape.

## Executed model matrix

`PASS` means the bare model's declared mechanisms are sufficient for the property exercised. `AMBIGUOUS` means additional semantics are required. `FAIL` would mean the model contradicts the scenario; none of the seven scenarios proves such a contradiction.

| Vector | Opaque reference | Portable artifact | Semantic outcome |
|---|---|---|---|
| V1 normal accepted RFQ | PASS | AMBIGUOUS | bound |
| V2 async counter / stale revision | PASS | AMBIGUOUS | invalid: stale revision |
| V3 human approval | PASS | PASS | bound |
| V4 scope mutation | PASS | PASS | invalid: scope expansion |
| V5 expiry | PASS | PASS | invalid: expired |
| V6 Business rejects at binding | AMBIGUOUS | AMBIGUOUS | valid + recognized, but rejected |
| V7 firm Business commitment | PASS | AMBIGUOUS | bound despite unrelated state drift |

The scorer produces this matrix from `models/model-capabilities.json` and each vector's explicit requirements. It does not choose a preferred winner.

## Invariant coverage matrix

| Candidate | V1 | V2 | V3 | V4 | V5 | V6 | V7 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| I1 identity survives | ✓ | ✓ | ✓ |  |  |  |  |
| I2 stale revision cannot bind | ✓ | ✓ |  |  |  |  |  |
| I3 scope cannot silently expand | ✓ |  |  | ✓ |  |  |  |
| I4 expired terms cannot bind | ✓ | ✓ |  |  | ✓ |  |  |
| I5 acceptance provenance survives | ✓ | ✓ | ✓ |  |  |  |  |
| I6 validity differs from executability |  |  |  |  |  | ✓ | ✓ |
| I7 authority provenance is explicit | ✓ |  | ✓ |  |  | ✓ | ✓ |
| I8 commitment type is explicit | ✓ |  |  |  | ✓ | ✓ | ✓ |
| I9 transaction gains no extra authority | ✓ |  |  | ✓ |  | ✓ | ✓ |
| I10 revalidation rejection is representable |  |  |  |  |  | ✓ |  |
| I11 firm commitment is not arbitrarily invalidated |  |  |  |  | ✓ |  | ✓ |
| I12 fixed inputs bind deterministically | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

## Equivalent comparison dimensions

| Dimension | Opaque reference | Portable artifact |
|---|---|---|
| interoperability | Low without a shared resolver and result contract | Higher semantic visibility, but only if normalization is shared |
| integrity | Strong when resolved from a Business-controlled store | Requires content-bound signature/MAC or equivalent trust mechanism |
| replay/staleness | Natural current-revision lookup; must be mandatory | Revision is visible, but supersession requires online status, short lifetime, or revocation semantics |
| scope verification | Business can verify; Platform cannot preflight | Both parties can inspect; Business still makes the authoritative comparison |
| modification detection | Resolver avoids client-side mutation; reference substitution remains a threat | Cryptographic or channel binding is required for every relied-upon field |
| authority ambiguity | Hidden unless resolution states issuer and commitment | Visible fields help, but self-asserted authority is not proof |
| portability | Low across unrelated Business systems | Higher across implementations if identifiers and term meaning remain comparable |
| origin unavailable | Binding normally fails closed or is deferred | Structural checks remain possible; freshness/authenticity may still fail closed |

## Derived hybrid option

A reviewable experiment could carry:

1. an authoritative Business-resolvable reference and revision;
2. a portable, integrity-bound projection of buyer, item/quantity scope, currency, accepted commercial semantics, expiry, acceptance provenance, and commitment type; and
3. a classified Business binding result.

The portable projection enables inspection and cross-system consistency; the reference enables current-revision, revocation, and Business authorization checks. If the two disagree, binding fails closed. The returned Cart/Checkout remains authoritative transaction state; the projection never becomes a direct mutation command.

## Unresolved questions

1. What trust mechanism proves issuer authorization for portable artifacts: Business signature, dereference-and-compare, trusted intermediary attestation, or a negotiated combination?
2. Must supersession be checked online, or can bounded lifetime and signed no-later-than semantics be sufficient in some profiles?
3. What is the smallest shared result taxonomy? At minimum this harness needs malformed, unknown, forged, unauthorized issuer, stale, expired, scope mismatch, and recognized-but-rejected.
4. How are item identity and quantity sale basis compared across systems without defining a universal catalog or B2B identity model?
5. Are commitment/invalidation semantics discoverable as a profile, carried per artifact, or both?
6. Where should binding occur: Cart create/update, Checkout create/update, or a separately addressable pre-Checkout operation?
7. How is idempotency scoped across artifact revision and target transaction so a retry cannot bind twice or bind a different revision?
8. Which commercial terms need normalized machine semantics versus an integrity-bound opaque term set plus Business restatement?

## Maturity assessment

| Next artifact | Ready? | Basis |
|---|---|---|
| another #812 discussion comment | **Yes** | Seven vectors expose the authority distinction and concrete gaps without proposing schema. |
| vendor-namespaced experiment | **Yes, narrowly** | A hybrid binding experiment can test trust, freshness, and result taxonomy while staying outside `dev.ucp.*`. |
| UCP proposal | **Not yet** | Trust/freshness, result taxonomy, identifier comparison, and placement remain unresolved. |
| upstream PR | **No** | There is no agreed protocol shape or maintainer direction, and this artifact intentionally avoids upstream changes. |

## Recommended next step for #812

Post the matrix and ask reviewers to validate two things before any schema work: (1) whether the three commitment levels capture real implementation semantics, especially firm commitment versus revalidation; and (2) whether the minimum binding-result distinctions are sufficient. In parallel, implement a vendor-namespaced hybrid proof of concept against one Business resolver, using these exact vectors unchanged. That experiment should measure which portable fields are actually necessary rather than assuming the whole quote must travel.

## Proposed #812 update (do not post)

> I turned the Shopware flows and Weston's authority observation into seven protocol-level test vectors covering revision, async/human pauses, scope mutation, expiry, recognized-but-rejected binding, and a firm Business commitment. The main result is that preservation and authority are separate: an accepted artifact may be valid but non-executable when it explicitly requires Business revalidation, while under the test harness's proposed `business_firm` semantics, a Business-issued commitment cannot be arbitrarily repriced during its validity window. That is a candidate semantic for review, not a claim about current UCP requirements.
>
> The opaque-reference model handles Business resolution, freshness, and authorization well, but needs a shared binding-result taxonomy and gives the Platform little scope/commitment visibility. A portable artifact makes those semantics inspectable, but is unsafe without content-bound issuer authorization and a supersession/freshness mechanism. A hybrid—portable semantics plus an authoritative Business reference—looks worth a vendor-namespaced experiment, though the vectors do not establish it as the only viable design.
>
> Before drafting a UCP schema, I suggest reviewing the candidate invariants and agreeing on the minimum distinctions at binding: invalid/unknown/forged/stale/expired/out-of-scope versus recognized-but-rejected, plus an explicit difference between revalidation-required terms and a firm Business commitment. If that holds up, the next step would be to run the same vectors against a small vendor-namespaced binding prototype.
