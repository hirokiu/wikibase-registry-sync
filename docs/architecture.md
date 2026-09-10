# Architecture and implementation status

jp-medical-registry → versioned JSON bundle → wikibase-registry-sync → backend.

The producer owns medical normalization, matching and administrative events. The consumer owns target-specific mappings, validation and transport. Hosting remains in the separate Custom Wikibase / federation platform project.

Version 0.1 implements an offline vertical slice. No production import is supported yet. Standard Wikibase API and Custom Wikibase batch transport are planned; no claim of API compatibility has been made without testing the target implementation.

Before write support: define stable keys across code changes; inspect Custom API; confirm property datatypes; implement target-scoped identity ledger, optimistic concurrency, statement ownership, resumable writes, reference/qualifier preservation and backups. Compare standard API throughput with a proposed asynchronous batch endpoint using identical input. A new batch endpoint must enforce the same validation, authorization and revision semantics. Direct database writes are not an accepted shortcut.

Bundle 0.1 fields: schema_version, dataset, entities[]. Each entity has a stable key within dataset, labels, statements and optional confirmed wikidata_qid. Statements contain a Wikidata property identifier, datatype, typed value, qualifiers and reference groups. The registry maps these to target-local identifiers. Current types: string, external-id, url, monolingualtext, wikibase-item. Other types, event relations, full provenance manifests and native custom properties require a future schema version. Unknown types fail validation.

Raw data and processing state are excluded from Git. MIT applies to original program code, not downloaded government or Wikidata data. Retain source-specific terms and attribution. No legacy WikibaseSync code has been copied in this version.
