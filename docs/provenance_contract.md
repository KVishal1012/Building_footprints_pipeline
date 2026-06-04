# Provenance Contract

Structure Intelligence Database is audit-ready by design. Every important value should answer four questions:

- What is the value?
- Where did it come from?
- How confident is it?
- Was it authoritative, derived, estimated, or AI-suggested?

## Hard Rules

- AI predictions never overwrite non-null authoritative or raw-source fields.
- AI cannot be written into `LoadSource` or `RawDataSource`.
- Each model suggestion must carry `PredictionKind`, model name/version, confidence, and features used.
- Every output row must have audit fields and a non-empty `CoverageTier`.
- Domain extensions are additive tables keyed by `StructureID`; they do not mutate the core table.

## Source Of Truth

The core source-of-truth fields are the canonical attributes and their source/method/confidence companions. Prediction fields are suggestions for review, gap filling, or downstream modeling. Consumers should only promote predicted values after their own governance process accepts the confidence, disclosure level, and local data context.

## Release Package

A production release should include:

- Core structure table.
- Optional delivery formats configured for the buyer.
- Coverage gap registry.
- Domain extension tables when enabled.
- `release_manifest.json`.
- These documentation files.
