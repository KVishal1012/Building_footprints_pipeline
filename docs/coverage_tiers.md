# Coverage Tier Model

Coverage tiers make source gaps visible before consumers use the data.

| Tier | Coverage Level | AI Role |
| --- | --- | --- |
| Tier 1 | Authoritative source, NSI or equivalent occupancy source, and Overture footprint coverage. | Fill null authoritative fields only. |
| Tier 2 | Authoritative source plus NSI or Overture. | Suggest weak or missing fields with clear confidence flags. |
| Tier 3 | NSI plus Overture without a full authoritative source. | Primary gap filling with mandatory AI disclosure. |
| Tier 4 | Overture or OSM only. | Heavy estimation with mandatory disclosure. |

The pipeline writes a gap registry with row counts and completeness rates by city/state when `coverage_config={"write_outputs": true}` is enabled.

Recommended consumer behavior:

- Treat Tier 1 as production-grade after local validation.
- Treat Tier 2 as production-usable with source caveats.
- Treat Tier 3 and Tier 4 as planning intelligence until authoritative sources are onboarded.
- Read `AIDisclosureLevel` and `PredictionConfidence` before using any predicted field.
