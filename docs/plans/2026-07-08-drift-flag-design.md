# Drift flag (live ECS vs deploy-events store) — design

**Date:** 2026-07-08
**Status:** Design spike complete. No code written (per plan 010 — this is a spike, not a build).
**Plan:** `plans/010-drift-flag-spike.md`

---

## Context

`docs/ARCHITECTURE.md` §11 lists the drift flag as work the deploy-events store "now unblocks",
and §9 cites "drift live-vs-ledger joins" as a reason Postgres was chosen over DynamoDB/S3-snapshot.
The feature: flag a service whose **live** ECS state disagrees with its **recorded** deploy
history — the signature of an out-of-band change (manual task-def edit, console rollback, deploy
pipeline bypass). Both data sides exist today; what's missing is a precise definition of "drift"
that survives the store's ingest lag without false-positiving on every legitimate deploy.

This doc answers the six questions in the plan, each with evidence gathered by reading
`aws/ecs_registry.py`, `db/models.py`, `db/repository.py`, `ingest/service.py`,
`aws/ecs_history.py` end to end (Step 1), and by probing the real dev environment (Step 2 — see
below; both the DB probe and, unexpectedly, a live backend were available).

**Drift check on the plan's stated commit range:** `git diff --stat dd53886..HEAD -- backend/src/maki/db/ backend/src/maki/inventory/ backend/src/maki/ingest/` is empty — none of the three directories changed since the plan was written. (`backend/src/maki/schemas.py` picked up one comment-only edit, unrelated to drift.) No STOP condition triggered.

---

## Step 2 probe — what actually happened

The plan expected the backend to be down and AWS creds absent (live curl skipped, DB probe only).
In practice the backend came up mid-investigation (a separate terminal session; `lsof` showed
`uvicorn`/`maki.server` listening on `:8787`, started minutes earlier), so **both** probes ran:

- `docker exec -i maki-postgres psql -U maki -d maki -c "SELECT service, revision, sha, registered_at, finished_at, status FROM deploy_events ORDER BY registered_at DESC LIMIT 25;"` — 22,654 rows across 40 services.
- `curl -s localhost:8787/api/services` — live ECS state for the same 40 services.

Joining the two (live `git_sha` vs. the store's newest row per service, `DISTINCT ON (service) ...
ORDER BY service, registered_at DESC`) gives real, not hypothetical, examples of both a matching
case and a mismatching case:

| Service | Live sha (curl) | Live deployed_at | Store's newest sha | Store `registered_at` |
|---|---|---|---|---|
| `prod-schedule-versioning` | `3fccf8f0…` | 2026-07-08 12:06 local | `3fccf8f0…` | 2026-07-08 11:02 UTC | match |
| `webhooks-web` | `3fccf8f0…` | 2026-07-08 12:06 local | `3fccf8f0…` | 2026-07-08 11:01 UTC | match |
| `public-api` | `18b57723…` | 2026-07-08 09:24 local | `18b57723…` | 2026-07-08 08:22 UTC | match |
| `inventory` | `6f4d0c19…` | 2026-07-08 10:18 local | `b05cf577…` | **2026-06-19** 12:55 UTC | **mismatch, ~3 weeks** |
| `auth` | `18b57723…` | 2026-07-08 09:24 local | `673cdad2…` | **2026-06-19** 13:10 UTC | **mismatch, ~3 weeks** |
| `newsfeed`, `wfm-service`, `middleware`, `inventory-insights-refresh-worker`, `inventory-report-preload`, `inventory-scripts-worker`, `inventory-reconciliation-item-mapping-worker`, `prod-scheduling-assistant-create/-web/-optimistic-scheduling`, `prod-workforce-payroll-common/-employee-sync-batch/-shift-sweep/-timecard-sync` | (various, all recent) | recent | (various, all June 19) | **2026-06-19** | **mismatch, ~3 weeks** |

Roughly half the 40 services are caught up to the minute; the other half are stuck ~3 weeks stale
in the store despite the live side showing deploys as recent as the same hour. I did not debug why
(out of scope for a read-only spike, and plan 010 forbids source changes) — the ingester
isolates per-service failures (`ingest/service.py:132-134`, `:148-150`: `except Exception:
session.rollback()`, logged, loop continues), so a subset of services silently falling behind for
an extended period while others stay current is architecturally possible without any alarm firing
today.

**This is the single most important finding of the spike.** It is direct, observed evidence that
ingest lag is **not** bounded by `settings.ingest_interval_seconds` (300s) in practice — it can be
orders of magnitude larger for a subset of services, for reasons the store gives no visibility
into. Any drift definition that assumes "lag ≈ one 5-minute cycle" will misclassify these stuck
services as three-week-old manual drift when the real cause is (most likely) ingestion falling
behind, not an out-of-band change. This shapes the recommendation in Q2 below.

> **Addendum (same day, ~2h later) — root cause identified, recommendation unchanged.** The
> "stuck" services were a **mid-backfill snapshot**, not a persistent ingester fault: maki hadn't
> run at all since ~2026-06-19, and the probe above executed minutes after the backend started —
> mid-way through the first catch-up cycle (3 weeks × 40 services + GitHub enrichment is slow).
> Re-probing at 13:2x UTC shows the watermark backfill (`ingest/service.py::_since_for`) completed:
> every actively-deploying service is current (`auth`/`newsfeed`/`public-api` events from 13:07
> written 13:17-13:20); the only old `newest_event` values left are services that genuinely
> haven't deployed in weeks, plus `web-app`, whose single Amplify row has an immutable
> `registered_at` by upsert design. Two real lessons survive: (a) lag is unbounded **while maki is
> off or catching up**, so the Q2 freshness-gating recommendation stands exactly as written; (b) a
> gap longer than ECS's ~90-day retention would lose `finishedAt` data permanently — restart maki
> at least every couple of months if the history matters.

---

## Q1 — What exactly is compared?

**Options:**

| Option | Precision | Coverage | Cost |
|---|---|---|---|
| Task-def revision number | Exact (ECS's own identity for a deploy) | ECS only — Amplify has no revision concept (`models.py:35`, comment: "Amplify has none") | Requires exposing revision on `DeployedService` — not currently plumbed. `ecs_registry.py:64` reads `td_arn` off the primary deployment but only extracts the image (`:66-68`); the revision suffix on that same ARN (`…:task-definition/family:REV`) is discarded. The parser already exists (`ECSDeployHistory._revision_from_arn`, `ecs_history.py:94-97`) and is a static method — trivially reusable from `ecs_registry.py` without new AWS calls. |
| Image sha | Already on both sides: live via `sha_from_image(image)` (`ecs_registry.py:72`, `aws/images.py`), stored in `DeployEvent.sha` (`models.py:36`) | Both platforms — Amplify rows carry sha too (`ingest/service.py:236`, `web.git_sha`) | Zero new plumbing |
| Both | Belt-and-braces | Same as revision (Amplify-blind on the revision half) | Sum of both costs |

Sha is tag-mutation-blind: if someone re-pushes a tag to point at a different image without
registering a new task-def revision, sha-based comparison misses it. In practice this repo's
tagging convention is immutable git-sha tags (`sha_from_image` explicitly rejects `:latest` and
untagged refs — `images.py:9`), so the blind spot is theoretical for this fleet unless the release
pipeline changes. Revision is the exact ECS-native identity but is Amplify-blind (no revision
concept at all) and requires new plumbing.

**Recommend: sha.** It costs nothing to wire (both sides already carry it), it is the field the
rest of the UI already keys off (fleet board, deploy history, deep links all use sha as the public
identity — `db/repository.py:179-199`'s `get_by_service_and_sha`), and it covers Amplify, which
revision cannot. The tag-mutation blind spot is a known, accepted limitation given the fleet's
tagging convention — call it out in the UI copy ("drift compares deployed image, not task-def
revision") rather than solving for a threat that isn't how this fleet deploys today.

**Rejected — revision-only:** exact but Amplify-blind, and the "exactness" over sha buys nothing
against this fleet's actual tagging discipline while costing new plumbing.
**Rejected — both:** the incremental precision doesn't clear the bar of the added complexity (two
mismatch states to reconcile, still Amplify-gap on the revision half) for a v1.

---

## Q2 — What absorbs ingest lag?

**Options considered:**

1. **Fixed grace window** — flag only if the live/store mismatch persists **and** the live deploy
   is older than `N × ingest_interval_seconds` (e.g. N=2, 10 minutes).
2. **Compare-on-read against `registered_at`** — no fixed window; just compare live `deployed_at`
   to the store's `registered_at`/`finished_at` for that sha, flag if store has no matching sha at
   all within some lookback.
3. **Store-freshness gate** — before evaluating drift, check how current the store's own view of
   that specific service is (e.g. `max(ingested_at)` for that service, or a per-service watermark).
   If the store's own last-touch for the service is itself older than a threshold, suppress the
   drift flag (or downgrade it to a distinct "stale data" signal) rather than asserting drift.

**False-positive analysis, using the Step 2 data:**

- Option 1 (fixed grace window) fails against the observed data. A 2×interval (10 min) or even a
  generous 6×interval (30 min) window does **not** absorb the `inventory`/`auth`/`newsfeed`/etc.
  gap — those services are ~3 **weeks** behind, not minutes. Any fixed multiplier small enough to
  be a useful drift signal for the fast-moving services (`webhooks-web`, `prod-schedule-versioning`
  deploy every ~90 min) is trivially blown through by the slow ones, producing a permanent false
  "drift" flag on roughly half the fleet — worse than no flag at all, because an incident
  responder who sees 20 of 40 services permanently flagged learns to ignore the flag entirely.
- Option 2 (compare-on-read, no window) has the same failure mode: it still can't distinguish "no
  matching sha because of an out-of-band change 3 weeks ago" from "no matching sha because the
  store hasn't ingested this service's real deploys for 3 weeks."
- Option 3 (store-freshness gate) is the only option the observed data supports. The store already
  has the ingredient: `ingested_at` (`models.py:55-57`, `server_default=func.now()` — set once per
  row, at first insert). `max(ingested_at)` **per service** approximates "when did the ingester
  last successfully touch this service" (it doesn't get bumped on no-op re-upserts, since
  `ingested_at` is deliberately excluded from `_UPSERTABLE_COLUMNS`/`update_cols` in
  `db/repository.py:16-32,56-60` — so this signal degrades gracefully rather than lying "fresh").
  Concretely: only evaluate drift for a service if the store's per-service freshness is itself
  recent (say, within 3× the ingest interval); otherwise surface "deploy history may be stale for
  this service" instead of "drift detected." This turns the store's known weak point into an
  explicit, honest signal instead of a silent false positive.

**Recommend: Option 3, store-freshness gate**, layered under a small grace window for the
genuinely-fresh case (Option 1's N=2 is fine as a secondary check once freshness is established —
it correctly absorbs the ordinary "brand-new deploy, store hasn't caught up yet" case for services
that *are* current). Concretely:

```
is_stale_store(service)   = max(ingested_at) for service  <  now - 3 * ingest_interval_seconds
in_grace(service)         = live.deployed_at              >  now - 2 * ingest_interval_seconds
drift = not is_stale_store(service)
        and not in_grace(service)
        and live.sha != store.newest_row(service).sha
```

`is_stale_store` needs one new query (`MAX(ingested_at) WHERE service = ?`, or a fleet-wide
`GROUP BY service` for the batch endpoint — see Q3) — no schema change, since `ingested_at` already
exists per row.

**Rejected — fixed grace window alone:** demonstrated false-positive-prone against real data above.
**Rejected — compare-on-read alone:** same failure mode, no freshness signal to distinguish stale
ingestion from real drift.

---

## Q3 — Where does the comparison run?

**Options:**

(a) **Field on `DeployedService`, computed in `InventoryService._compute`**
(`inventory/service.py:30-42`). Today `InventoryService` has zero DB dependency — it's
constructed from `ecs_client()`/`amplify_client()`/`GitHubEnricher` only
(`inventory/routes.py:17-38`), and its result is SWR-cached
(`inventory/service.py:25,28`, `cache.py`'s `SwrCache`) purely from AWS/GitHub reads. Adding drift
here means injecting a `DeployEventRepository` + `session_factory` into `InventoryService`,
coupling the one dependency-free, AWS-only service in the codebase to Postgres, and making every
`/api/services` call (the fleet board's primary poll) pay a DB round-trip even when nobody looks at
drift.

(b) **Separate `GET /api/services/{name}/drift` endpoint.** Clean dependency-wise (mirrors
`activity/routes.py:29-36`'s `ActivityService(repository=DeployEventRepository(),
session_factory=get_session, ...)` pattern exactly), but the fleet board needs drift status for
*all* services at once to render a badge per row — this shape forces N+1 calls from the frontend on
every board load.

(c) **Fleet-wide `GET /api/drift`, computed from one store query + one live inventory read.**
Same DB-access pattern as (b) (new `DriftService` alongside `ActivityService`, same
`DeployEventRepository`/`get_session` wiring), but returns `{service: DriftStatus}` for the whole
fleet in one call: one `GROUP BY service` query for `(newest sha, newest registered_at, max
ingested_at)` per service (extending `DeployEventRepository` with a batch version of the
`DISTINCT ON (service) ... ORDER BY service, registered_at DESC` query used for the Step 2 probe),
joined in Python against one `InventoryService.get_inventory()` call (already SWR-cached, so this
adds no new AWS load).

**Recommend: (c).** It's the only option that gives the fleet board a badge per row without N+1,
and it keeps `InventoryService` DB-free — the new `DriftService` composes the two existing services
(`InventoryService` for live, `DeployEventRepository` for stored) rather than merging their
concerns. Wiring sketch: a new `backend/src/maki/drift/` package (`service.py` + `routes.py`)
following the `activity/` package's shape exactly — `DriftService(inventory=InventoryService,
repository=DeployEventRepository, session_factory=get_session, ingest_interval_seconds=...)`, one
route `GET /api/drift` behind its own `@cache`-wrapped factory, same as
`activity/routes.py:29-36` / `inventory/routes.py:16-28`.

**Rejected — (a):** couples the one AWS-only service to Postgres and taxes every board poll with a
DB round-trip nobody asked for.
**Rejected — (b) alone:** forces N+1 from the frontend for a fleet-wide badge; fine as an
*additional* per-service detail endpoint later (e.g. to back a "why is this flagged" expansion on
the service detail page) but not as the primary shape.

---

## Q4 — What about Amplify?

The store has an Amplify row with `revision = NULL` (`models.py:60-63`'s comment: "Amplify has no
revision (nullable)"; `ingest/service.py:245`: `"revision": None` in `_amplify_event`). The live
side has `git_sha` only (`AmplifyDeployRegistry` surfaces no revision-equivalent — Amplify's unit
of deploy is a "job", not a task-def revision). Since Q1 recommends comparing **sha**, not
revision, Amplify is not actually blocked from participating: `web-app`'s live sha and the store's
Amplify row's sha are directly comparable, same as any ECS service.

The real gap is different: Amplify has exactly one row per service in the store (`UniqueConstraint
(service, revision, ..., postgresql_nulls_not_distinct=True)` — `models.py:63-68` — the ingester
upserts the single Amplify row in place every cycle rather than keeping history). That means there
is no "newest N Amplify deploys" to reason about lag against — only ever the current one. The
store-freshness gate in Q2 still works unmodified (`ingested_at` exists on the Amplify row too), so
the drift check itself needs no Amplify-specific branch.

**Recommend: in scope for v1**, no special-casing needed beyond what Q1's sha-based comparison
already buys — the only asymmetry (single row vs. history) doesn't affect a live-vs-newest-stored
comparison.

**Rejected — Amplify out of v1:** would need a real reason (there isn't one) given sha comparison
already covers it "for free"; carving it out would just be extra code (an `if platform == "ecs"`
branch) for no benefit.

---

## Q5 — UI surface

**Options:**

- **Badge on the fleet board row.** Matches the board's existing per-service status vocabulary
  (rollout state chips already live there per `DeployedService.status`/`rollout_reason`,
  `schemas.py:16,20`) — a drift badge slots in as one more state, visible fleet-wide without
  navigating away, which is exactly the incident-response use case ("what changed out of band,
  across the whole fleet, right now").
- **Banner on the service detail page.** Higher-context (room for "live sha X vs. last known-good
  deploy Y, drifted since Z"), but requires drilling into each service to discover it — the
  opposite of the fleet-wide "what's wrong right now" scan this feature exists for.

**Recommend: both, not either/or** — badge on the fleet board (the entry point: "13 of 40 services
show unexplained state"), which links into a banner on that service's detail page (the follow-up:
"here's exactly what's different and since when"). This mirrors the existing pattern where the
board's rollout chips already deep-link into more detail on the service page.

**Dismissal:** given `/api/drift` is a live compute over two read-only sources (no drift-events
table, no write path — matching the CLAUDE.md safety invariant that maki's actions stay
side-effect-free), there is nothing to "dismiss" server-side; the badge simply reflects current
truth on the next fetch. Recommend the badge does **not** persist a dismissal at all for v1 — it's
not an alert queue, it's a status like the rollout chips. If the underlying live-vs-store gap
resolves (the real deploy catches up, or the store re-syncs), the badge clears on its own next
poll. Revisit if the fleet-wide false-positive rate in practice argues for a mute, but don't build
persistence speculatively.

**Rejected — banner-only:** buries a fleet-wide signal behind per-service navigation, defeating the
"incident responder scanning the whole fleet" use case from the plan's motivation.
**Rejected — persisted dismissal:** no state to persist against (no drift-events table by design);
speculative complexity for a v1 with no evidence yet that operators will want to mute it.

---

## Q6 — Effort estimate

**Estimate: M.**

Build-plan sketch:

1. **Backend — plumbing (S):** expose task-def revision on `DeployedService` is *not* needed given
   the Q1 recommendation (sha-only) — this shrinks the plumbing to zero new AWS fields. Add
   `DeployEventRepository.latest_by_service(session) -> dict[str, LatestDeployRow]` (one
   `DISTINCT ON (service)` query, same shape as the ad-hoc query used in the Step 2 probe) plus a
   freshness variant (`MAX(ingested_at) GROUP BY service`) — these can likely be one query returning
   `(service, sha, registered_at, ingested_at)` per service.
2. **Backend — `DriftService` + `GET /api/drift` (S–M):** new `drift/` package mirroring
   `activity/`'s shape; the comparison logic from Q2 (freshness gate → grace window → sha compare);
   unit tests per state (fresh+match, fresh+mismatch=drift, stale-store=suppressed, in-grace=not
   yet drift).
3. **Frontend — badge + banner (S–M):** fleet board row badge keyed off `/api/drift`'s per-service
   map; service-detail banner with the "live sha vs. stored sha, since when" detail. No new routing
   (surfaces on existing pages).
4. **No migration.** Q1–Q4 all land on existing columns (`sha`, `ingested_at`, `registered_at`) —
   this is the main reason the estimate is M rather than L.

**Test plan sketch:**
- `DeployEventRepository.latest_by_service`: multi-service fixture, asserts newest-per-service by
  `registered_at`, correct under the `NULLS NOT DISTINCT` Amplify row.
- `DriftService` state machine: table-driven tests over the four combinations
  (fresh/stale-store × match/mismatch), using injected clocks (matching the existing
  `now: Callable[[], datetime]` pattern already used in `DeployEventIngester.__init__`,
  `ingest/service.py:82`) rather than real time — the false-positive analysis in Q2 is exactly the
  kind of edge case that needs deterministic fixtures, not a live clock.
- Route test: `GET /api/drift` shape, one flagged + one clean + one Amplify service in the fixture.
- No AWS/GitHub call changes — `DriftService` composes `InventoryService`'s existing cached read, so
  no new mocking surface beyond what `inventory/service.py` tests already use.

---

## Summary of recommendations

| Question | Recommendation |
|---|---|
| Q1 comparison key | **Image sha** (both sides already carry it; zero new plumbing; Amplify-compatible) |
| Q2 lag handling | **Store-freshness gate** (`max(ingested_at)` per service) + a small grace window under it — a fixed grace window alone is demonstrably insufficient against observed data |
| Q3 API placement | **Fleet-wide `GET /api/drift`**, new `drift/` package composing `InventoryService` + `DeployEventRepository`; keeps `InventoryService` DB-free |
| Q4 Amplify | **In scope for v1** — sha comparison covers it with no special-casing |
| Q5 UI | **Badge on fleet board** deep-linking to a **banner on service detail**; no persisted dismissal |
| Q6 effort | **M** — no migration needed; existing columns cover every recommendation above |

The Step 2 live probe surfaced a finding worth flagging to whoever picks up the build plan: roughly
half of the 40 tracked services show a store that's ~3 weeks behind live ECS state, likely
ingestion falling behind for that subset rather than genuine drift (unconfirmed — out of scope to
diagnose here). Building the drift flag on top of a store with this behavior, without the
freshness gate in Q2, would ship a feature that's wrong for half the fleet on day one.
