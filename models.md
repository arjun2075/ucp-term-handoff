# Handoff model comparison

## Model A — opaque reference

Cart/Checkout receives a stable artifact reference. The Business resolves it in an authoritative system and evaluates the resolved revision, scope, acceptance, expiry, authority, and commitment.

Strengths: the Business controls resolution and authenticity; sensitive terms need not cross implementation boundaries; revocation and current-revision lookup are natural. Weaknesses: the Platform cannot inspect scope or commitment before binding; portability depends on a common binding response; replay safety depends entirely on resolver behavior; origin unavailability can make a valid artifact unbindable.

An opaque reference is not intrinsically safe. Safety requires the resolver to bind the reference to the authenticated buyer and expose a current revision, exact scope, issuer authorization, commitment type, and classified result. A lookup that merely returns a price silently delegates price-setting authority to the referenced system.

After binding, the reference alone does not establish whether authority transferred into the transaction, whether the origin must remain reachable, or which clock governs execution. The Business can retain these facts internally, but interoperability requires them in the authoritative transaction lifecycle/result contract. Partial binding similarly requires the Business response to expose stable binding-unit membership and replay identity; a single artifact-wide status is insufficient.

## Model B — minimal portable accepted-term artifact

A normalized artifact carries identity, revision, parties, scope, commercial values, validity window, acceptance provenance, and commitment semantics into binding. The Business compares it with the request and returns authoritative transaction state.

Strengths: scope and commitment are inspectable; intermediary implementations can preserve and log the same semantics; origin downtime need not prevent structural checks. Weaknesses: portable values are dangerous without content-bound issuer authentication and a current-revision/revocation source; normalization can lose mechanism-specific meaning; copied values can be mistaken for authoritative transaction state.

The Business may rely on portable values only to the extent authorized by verifiable provenance and commitment semantics. Under `accepted_revalidate`, they are an assertion to check, not a command to set a price. Under `business_firm`, verified Business-issued values are binding within their scope and validity window, except for declared invalidation conditions. In neither case may the holder directly mutate Cart/Checkout.

Portable post-bind rules can make authority, clocks, release conditions, and atomic groups inspectable, but visibility is not enforcement. Execution still needs an authoritative transaction state machine, and binding-unit retries still need server-side deduplication. A portable group declaration is unsafe unless issuer authorization covers the exact group membership and cross-line commercial conditions.

## Equivalent comparison

| Dimension | Model A: opaque reference | Model B: portable artifact |
|---|---|---|
| interoperability | Low without shared resolver/binding-result contract | Higher semantic portability; normalization contract required |
| integrity | Strong when resolved inside the Business trust boundary | Requires content-bound signature/MAC or authoritative introspection |
| replay/staleness | Resolver can enforce current revision/revocation | Needs current-revision or revocation semantics beyond a static document |
| scope verification | Business can verify; Platform cannot preflight | Both can compare visible scope; Business remains final evaluator |
| modification detection | Reference integrity plus protected server record | Cryptographic/content-bound verification required |
| authority ambiguity | Hidden unless resolver returns provenance and commitment | Visible fields help, but declarations are not trustworthy by themselves |
| portability | Usually Business/origin specific | Designed to cross implementations |
| origin unavailable | Binding normally fails closed; cached resolution needs freshness rules | Local structural evaluation continues, but authority/currentness may remain indeterminate |
| data minimization | Strong | More commercial/customer data crosses boundaries |
| semantic loss | Resolver retains native detail | Normalization risks omitting conditions or pricing basis |
| post-bind authority | Can remain Business-internal, but is ambiguous to other participants without transaction semantics | Can be declared portably, but the transaction must enforce it |
| dual clocks | Resolver can apply a rule, but a bare reference does not reveal it | Can carry a rule; still needs authoritative clock evaluation |
| origin dependency at release | Natural if release re-resolves; origin outage can block execution | Can support offline inspection, but authority/currentness may still depend on origin or verifier availability |
| partial binding | Requires explicit grouped results from the Business | Can carry group membership and results; the Business remains authoritative |
| atomicity | Native dependencies are available to the resolver | Cross-line dependencies must survive normalization and be integrity-bound |
| retry recognition | Server can deduplicate, but artifact-level identity is too coarse | Unit replay identity can travel, but deduplication remains server-side |

## Derived hybrid

The vectors suggest—but do not require—a hybrid: portable, inspectable semantics plus a Business-authoritative reference/introspection path. The portable portion enables preflight, preservation, audit, cross-implementation transport, post-bind rule visibility, and atomic-group visibility. The Business reference supplies issuer authorization, current revision/revocation, and native conditions. Binding compares both and fails closed on disagreement.

The hybrid inherits a synchronization problem: it needs an explicit rule for which facts are authoritative and what mismatch means. V8–V14 add further requirements rather than making the hybrid an automatic winner: an authoritative post-bind state machine, explicit deadline-source and independent release semantics, integrity-bound unit membership, and unit-granular idempotency. A reasonable experimental rule is that portable semantics are a content-bound snapshot, the Business record decides currentness and declared invalidation state, and any mismatch is a classified non-binding result rather than silent repair.

## Origin-unavailable behavior

- Opaque model: `unavailable`, not `unknown` or `invalid`; retry may succeed. Cached resolution is safe only with explicit freshness and revocation rules.
- Portable model: structural validity and scope can still be checked, but authority/current-revision status is `indeterminate` unless self-verification and offline-valid commitment rules were declared.
- Hybrid: may honor an offline-verifiable firm commitment only if the Business deliberately accepted that availability tradeoff; otherwise fail closed as `authority_indeterminate`.

At release, origin unavailability is governed by the declared post-bind model. Authority transferred at bind may permit execution from authoritative transaction state. Continued-origin or continued-term validation must fail closed or remain pending. Conditional release may depend on a release authority rather than the quote origin; that dependency must be explicit.

## New-case assessment

| Question | Opaque reference | Portable artifact | Hybrid |
|---|---|---|---|
| represent post-bind authority | Only through added transaction response semantics | Can declare it, but cannot enforce it alone | Can align visible rule with Business state; still needs lifecycle protocol |
| establish continued origin dependence | Resolver behavior can establish it but may not expose it | Can declare dependency; proof of currentness remains external | Reference makes dependency explicit at the cost of availability |
| represent partial binding | Added Business unit-result contract required | Unit semantics can travel; authoritative results still required | Portable groups plus Business results are useful but not sufficient by themselves |
| declare atomicity | Native resolver model | Integrity-bound portable group | Both views can be compared; disagreement must fail closed |
| recognize already-bound units | Business-side unit deduplication required | Replay identity can travel but does not deduplicate itself | Same server-side requirement; reference helps locate prior state |

No model handles V8–V10 without additional transaction-lifecycle or binding-operation semantics. Both can express V11 once the grouping is authoritative. The new cases narrow the experiment but do not select a universal carrier.

## Second-review requirements across carriers

| Concern | Opaque reference | Portable artifact | Derived hybrid |
|---|---|---|---|
| Deadline authority | Authoritative resolver/transaction retains selected clock | Bound policy must be authenticated, then enforced | Compare projection with authoritative policy; no automatic enforcement |
| Release evaluator and deadline disposition | Business needs explicit event authority and economic disposition | Condition, event authority and disposition must survive normalization | Combines visibility and introspection but still requires release evidence |
| Cross-unit adjustment | Resolver retains accepted rule | Rule and exact scope must be covered by issuer authorization | Can compare portable rule with native rule; disagreement rejects |
| Pricing/freight normalization | Native semantics remain available | A lossy normalized rule must fail closed | Does not eliminate semantic loss; supported rule vocabulary still needed |
| Attempt history | Business store can retain results | Portable attempt identity cannot replace a durable store | Reference can locate history; still needs atomic deduplication |
| Origin unavailable on retry | Pending/fail closed if history or authorization cannot be established | Local artifact does not prove no previous success | Cached authoritative history needs explicit freshness guarantees |

The scored model verdicts are representational assessments under declared capability
assumptions, not measurements of separate production adapters. The same semantic
evaluator is used throughout. A hybrid combines reference and portable strengths
but all three need lifecycle policy, adjustment authorization, and durable attempt
history. It is not uniquely preferred by V12–V14.
