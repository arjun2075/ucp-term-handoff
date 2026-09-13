# Accepted commercial terms → binding → execution

This repository is a review artifact for [UCP Discussion #812](https://github.com/Universal-Commerce-Protocol/ucp/discussions/812). It asks two connected questions: what must survive when accepted terms formed outside Cart/Checkout are presented to a Business for binding into authoritative UCP transaction state, and what semantics govern the interval from binding through execution or release?

This is an analysis harness, not a proposed UCP schema or capability. Its JSON Schema describes test cases only. Field names, result codes, and model names are deliberately non-normative.

## Contents

- `invariants.md` — candidate invariants, lifecycle concepts, binding units, and data classification.
- `models.md` — opaque-reference and portable-artifact comparison, plus a derived hybrid.
- `analysis.md` — vector/model matrix, findings, maturity assessment, and proposed #812 update.
- `schema/test-vector.schema.json` — schema for this test harness.
- `models/model-capabilities.json` — declared capabilities used by the model scorer.
- `vectors/*.json` — eleven executable scenarios; V1–V7 cover handoff and V8–V11 cover post-bind lifecycle and grouped partial binding.
- `tests/test_vectors.py` — schema validation, semantic evaluator, model scorer, and consistency audits.

## Run

Python 3.9+ and the `jsonschema` package are required.

```sh
python3 -m unittest discover -s tests -v
python3 tests/test_vectors.py --matrix
```

The first command validates every vector and runs the semantic and cross-vector audits. The second prints the review matrix used in `analysis.md`.

## Source boundary and attribution

Implementation facts are taken from Juan Fernández's Shopware evidence in [#812](https://github.com/Universal-Commerce-Protocol/ucp/discussions/812), the public [`com.shopware.quote` prose specification](https://sw-ag.dev/.well-known/ucp/specs/quote.html), and [Shopware B2B Quote Management documentation](https://docs.shopware.com/en/shopware-6-en/commercial-features/b2b-components). Negotiation context comes from [#502](https://github.com/Universal-Commerce-Protocol/ucp/discussions/502). Weston's reviews in #812 identify the authority direction problem, validate I7–I11 and the `issuer`/`authorized_by` split, and identify the post-bind and partial-binding gaps. The generalized invariants, binding-unit synthesis, harness design, and vectors are Arjun Garg's derived proposal for review.

The evidence is paraphrased rather than copying Shopware's schema. Current UCP facts are limited to documented behavior: the Business response is authoritative for Checkout transaction state, quantity changes may not be silently reinterpreted, and Checkout may omit payment for quote-generation use cases. Those facts do not make the candidate handoff invariants UCP requirements.

## Non-goals

This artifact does not define negotiation, RFQ, identity, payment-term, supplier-selection, pricing, auction, settlement, or procurement protocols. It does not introduce a `dev.ucp.*` capability and does not modify upstream UCP code. Its post-bind and binding-unit vocabulary is harness-level and is not a claim about current UCP behavior.
