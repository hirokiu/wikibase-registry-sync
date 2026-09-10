# Custom Wikibase integration assessment

Inspection date: 2026-09-10. Source commit: `4cb9044dc995ed75c521280dbd786390bd8255c4` in [hirokiu/custom-wikibase](https://github.com/hirokiu/custom-wikibase/tree/4cb9044dc995ed75c521280dbd786390bd8255c4). This assessment is not a server compatibility qualification. That repository was inspected without modifications.

## Confirmed boundaries

Custom Wikibase retains MediaWiki/Wikibase as its authoritative entity store. Query backends are derived indexes; supported profiles documented in this revision include none, Virtuoso, Fuseki/TDB2 and Oxigraph. Product fixture scripts use the standard Action API, including `wbeditentity`. Accordingly, the default writer should be shared with Wikibase Suite. The choice of RDF backend must not change how authoritative entities are written. Do not write imported entities directly to SPARQL update endpoints or database tables.

A core-only profile can accept entities but cannot satisfy the medical project's SPARQL search requirements. API-write success and query visibility are distinct outcomes; report both. No assumption is made that a rebuild of a derived RDF generation creates medical change events or replaces entity revision history.

Discovery exists at `GET /.well-known/japan-wikibase-runtime`, contract `jwb-runtime-v1`. It reports instance identity, distribution version, Action API endpoint and optional query state. For enabled query services, the logical query endpoint, serving generation and freshness distinguish source activity from synchronization lag. The importer should use the logical endpoint, not a physical generation address.

## Parallel development agreement proposed

- Pin the inspected source commit and record the runtime contract/distribution version for each tested target. A moving default branch is not evidence that compatibility still holds.
- Bind an import ledger to stable instance UUID + dataset namespace. Keep Suite targets explicitly configured if they do not implement Custom discovery. Missing discovery must not silently select a different target.
- Verify configured target identity before credentials or writes are sent. Discovery URLs are information, not permission to send credentials to arbitrary hosts.
- Additive compatible discovery fields may be ignored. Unsupported contract versions and required capability changes stop writes with a clear diagnostic.
- Maintain contract fixtures and integration tests independently of the deployment controller. Track tested distribution versions in the README, rather than promising all future versions.
- The orchestration project owns lifecycle, tenant authorization, operation scheduling, backup and RDF rebuild. This project owns bundle validation, entity mapping, import plans, submission and item-level outcomes.
- Coordinate long imports with stop/restart/rebuild operations through an agreed instance operation policy. Do not assume the lifecycle driver's mutation lease already covers entity API writes.

## Standard API first; batch entry point as a measured extension

First qualify item/property creation, readback, updates, reference/qualifier/rank preservation, supported datatypes, authentication, revision conflict behavior and resumability against disposable Suite and Custom instances. Then measure the same medical bundle at increasing size. Record entity/statement counts, request count, write throughput, error rates, query lag, memory and storage growth.

Only add a server-side import entry point when measured constraints or cloud-client needs justify it. Proposed requirements, NOT existing endpoints:

- authenticated instance-scoped submission with bundle version/hash, request idempotency key and size/concurrency limits;
- asynchronous operation identifier and bounded polling; validation-only mode;
- per-entity stable key, outcome, resulting local ID/revision and conflict details;
- durable partial progress and recovery after disconnect; repeat submission does not duplicate entities;
- explicit conflict and statement-ownership rules; existing human/other-source data is preserved;
- the same domain validation, permissions, revision and source-reference semantics as the standard API;
- separate accepted, entity-written and query-visible states;
- integration with controller lifecycle policy, without providing Kubernetes/admin capabilities to the importer.

Whether the queue belongs in an optional instance service or in the orchestration layer remains open. A lightweight core need not acquire a mandatory heavy batch service. Do not invent a batch URL or claim batch support from the RDF worker's internal batch processing.

## Current qualifications and next shared decisions

The inspected release describes local ARM64 qualification and separately lists incomplete AMD64, Kubernetes/controller integration, large-scale sizing and production backup/restore work. Its release status is not interchangeable with the WBS8 fullRebuild harness status in another task. Deployment readiness requires the relevant project's newer evidence.

Next shared decisions: supported API/version floor; discovery extension policy; import/lifecycle concurrency; standard API benchmark criteria; optional batch ownership and response contract; test target and representative medical workload. Changes to Custom Wikibase should be separate reviewed changes coordinated with its active development work, not unrelated edits from this importer checkout.

## Sources and attribution

Architecture and contract facts above are summarized from Custom Wikibase project documentation at the pinned revision: [README](https://github.com/hirokiu/custom-wikibase/blob/4cb9044dc995ed75c521280dbd786390bd8255c4/README.ja.md), [runtime contract](https://github.com/hirokiu/custom-wikibase/blob/4cb9044dc995ed75c521280dbd786390bd8255c4/docs/japan-wikibase/runtime-contract.md), [controller boundary](https://github.com/hirokiu/custom-wikibase/blob/4cb9044dc995ed75c521280dbd786390bd8255c4/docs/architecture/k3-controller-integration-boundary.md), and [limitations](https://github.com/hirokiu/custom-wikibase/blob/4cb9044dc995ed75c521280dbd786390bd8255c4/docs/japan-wikibase/known-limitations.ja.md). Original documentation is credited to the Custom Wikibase project, under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); this integration note paraphrases those facts and adds proposed importer requirements. No upstream source code was copied. This attributed note is CC BY 4.0; the repository's original software remains MIT.
