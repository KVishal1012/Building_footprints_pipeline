# Structure Passport

The Structure Passport is the audit view for one `StructureID`. It answers what is
known, where each value came from, when it was refreshed, what changed, and what
remains unresolved.

## Contract

The passport contains:

- current authoritative identity, location, geometry, and coverage tier
- value, datasource, confidence, and method for every core attribute
- source vintage, last refresh, and pipeline refresh timestamp
- the latest 100 geometry versions and change events
- conflicting source values and resolution state
- AI suggestions from `public.structure_ai_suggestions`, never blended into current values
- QA status, open warnings, and resolved issues
- active parcel, ward, hazard, and infrastructure relationships

Database clients call:

```sql
select public.get_structure_passport('STRUCTURE_ID');
```

Backend applications may use:

```python
passport = store.structure_passport("STRUCTURE_ID")
```

The function is service-role only by default. A later consumer API may expose a
restricted view, but browser clients must never receive the service role key.

## Truth Boundary

The `current` and `attributes` sections represent canonical data. The
`ai_suggestions` section is advisory. Accepting a suggestion requires an explicit,
audited workflow and must not rewrite an authoritative non-null value.

## History And Limits

Geometry and canonical versions are stored in `history.structure_versions`,
partitioned by city and source run. Passport arrays are bounded to the latest 100
history/change events so one problematic structure cannot create an unbounded API
response. Full history remains queryable by authorized backend services.
