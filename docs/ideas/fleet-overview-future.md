# Fleet overview — parked ideas

Ideas surfaced while designing the Status Board landing page that we're **not**
building yet, because we lack a real data source. Captured here so they aren't lost.

## Uptime KPI ("Uptime 30d")

- Concept: a headline reliability number (e.g. `99.98%`) in the fleet hero.
- Blocked on: no uptime/SLO data in maki today. Would need a source — ECS
  service health over time, an external probe (e.g. synthetic checks), or an
  SLO pipeline (CloudWatch/Datadog) aggregated per service and rolled up to a
  fleet figure.
- Open questions: window (rolling 30d?), what counts as "down" (degraded vs
  hard-down), per-service vs fleet-wide, how to weight services.

## Last incident KPI ("none in 14d")

- Concept: time since last incident, shown in the hero as a calm/at-risk signal.
- Blocked on: maki has no incident data. Would need to ingest incidents from
  wherever they live (incident.io / PagerDuty / a `.koh/incident-review/` feed /
  manual annotations) and map them to services or the fleet.
- Open questions: what's an "incident" here (sev threshold?), source of truth,
  linking an incident to specific services.

## Notes

- Both were prototyped as hero KPI pills in the Status Board and removed pending
  real data. The V2 hero currently shows only the health counts + proportion bar
  (no KPI pills) — everything there is derived from live `/api/services`.
- **Mean deploy** and **Deploys today** are also parked: derivable later from the
  metrics/activity endpoints, not from `/api/services`.
- **CPU / memory *utilization* %** is parked too — needs CloudWatch per-service
  queries (expensive). Note we DO surface CPU/mem *reservation* (from the task
  definition, free) in the V2 tile tooltip.
- When a data source lands, add KPI pills back into the V2 hero
  (`frontend/src/pages/ServicesPage.tsx`).
