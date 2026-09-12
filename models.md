# Handoff model comparison

## Model A — opaque reference

Cart/Checkout receives a stable artifact reference. The Business resolves it in an authoritative system and evaluates the resolved revision, scope, acceptance, expiry, authority, and commitment.

Strengths: the Business controls resolution and authenticity; sensitive terms need not cross implementation boundaries; revocation and current-revision lookup are natural. Weaknesses: the Platform cannot inspect scope or commitment before binding; portability depends on a common binding response; replay safety depends entirely on resolver behavior; origin unavailability can make a valid artifact unbindable.

An opaque reference is not intrinsically safe. Safety requires the resolver to bind the reference to the authenticated buyer and expose a current revision, exact scope, issuer authorization, commitment type, and classified result. A lookup that merely returns a price silently delegates price-setting authority to the referenced system.

## Model B — minimal portable accepted-term artifact

A normalized artifact carries identity, revision, parties, scope, commercial values, validity window, acceptance provenance, and commitment semantics into binding. The Business compares it with the request and returns authoritative transaction state.

Strengths: scope and commitment are inspectable; intermediary implementations can preserve and log the same semantics; origin downtime need not prevent structural checks. Weaknesses: portable values are dangerous without content-bound issuer authentication and a current-revision/revocation source; normalization can lose mechanism-specific meaning; copied values can be mistaken for authoritative transaction state.

The Business may rely on portable values only to the extent authorized by verifiable provenance and commitment semantics. Under `accepted_revalidate`, they are an assertion to check, not a command to set a price. Under `business_firm`, verified Business-issued values are binding within their scope and validity window, except for declared invalidation conditions. In neither case may the holder directly mutate Cart/Checkout.

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

## Derived hybrid

The vectors suggest—but do not require—a hybrid: portable, inspectable semantics plus a Business-authoritative reference/introspection path. The portable portion enables preflight, preservation, audit, and cross-implementation transport. The Business reference supplies issuer authorization, current revision/revocation, and native conditions. Binding compares both and fails closed on disagreement.

The hybrid inherits a synchronization problem: it needs an explicit rule for which facts are authoritative and what mismatch means. A reasonable experimental rule is that portable semantics are a content-bound snapshot, the Business record decides currentness and declared invalidation state, and any mismatch is a classified non-binding result rather than silent repair.

## Origin-unavailable behavior

- Opaque model: `unavailable`, not `unknown` or `invalid`; retry may succeed. Cached resolution is safe only with explicit freshness and revocation rules.
- Portable model: structural validity and scope can still be checked, but authority/current-revision status is `indeterminate` unless self-verification and offline-valid commitment rules were declared.
- Hybrid: may honor an offline-verifiable firm commitment only if the Business deliberately accepted that availability tradeoff; otherwise fail closed as `authority_indeterminate`.
