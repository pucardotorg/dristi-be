# 0012 — Redis Caching (Low-Investment Rollout)

## Status

Proposed

## Context

Dristi already uses Redis in the stack (Dramatiq broker + health checks), and Django cache settings already point to Redis via `CACHE_URL`.

We want application caching with **minimal engineering investment** while reducing repeated DB load on read-heavy APIs.

## Decision summary

Adopt **`django-cachalot` backed by Redis** as the default caching strategy.

- Keep Redis as the shared cache backend via Django `CACHES["default"]`.
- Let cachalot automatically cache ORM query results and automatically invalidate on table writes.
- Keep explicit per-view/manual cache as optional, only for endpoints that need custom behavior.

This gives low-code adoption with stronger invalidation behavior than TTL-only manual caching.

## Why this approach

### Options considered

1. **Django built-in cache + manual per-view/low-level keys**
   - Pros: explicit control, predictable scope.
   - Cons: manual key design/invalidation work in every feature.

2. **django-cachalot + Redis (selected)**
   - Pros: automatic QuerySet caching, automatic invalidation on model/table writes, works with shared Redis backend, low code changes for broad impact.
   - Cons: less explicit control of what gets cached; requires careful exclusions for volatile/sensitive paths.

3. **diskcache**
   - Pros: simple and fast local disk cache.
   - Cons: not Redis-native, node-local (poor fit for multi-container deployment), not ideal for shared cache consistency.

4. **Custom cache abstraction**
   - Pros: maximum control.
   - Cons: high upfront investment and maintenance.

Given the requirement for low effort and Redis usage, `django-cachalot` is the best fit.

### Focused comparison: `django-cachalot` vs `diskcache`

| Criterion | django-cachalot | diskcache |
| --- | --- | --- |
| Primary model | Automatic ORM/QuerySet cache | Local filesystem-backed general cache |
| Redis compatibility | Yes (via Django cache backend) | No native shared Redis model |
| Multi-instance fit | Strong with shared Redis | Weak (cache isolated per instance) |
| Invalidation | Automatic on writes | Manual/TTL-driven |
| Best fit for Dristi | High | Low |

## Scope

### In scope (Phase 1)

- Use Redis-backed Django cache (`CACHE_URL`) as cachalot storage.
- Add and configure `django-cachalot`.
- Start with allow-listed read-heavy, low-churn apps/tables, then expand scope gradually.
- Add tests validating query caching + invalidation on writes.
- Add basic observability (query count deltas and cache behavior logs).

### Out of scope (Phase 1)

- Full custom key-management framework.
- Site-wide cache middleware.
- Caching user-private responses outside ORM-level safe boundaries.
- Complex cache warming/preloading pipelines.

## Technical design

### 1) Backend and configuration

Keep existing Redis cache backend:

- `CACHES["default"]` from `CACHE_URL`.
- Redis DB separation remains:
  - `0` general Redis use
  - `1` Django cache
  - `2` Dramatiq

Add `django-cachalot` dependency and app registration.

Recommended environment/settings additions:

- `CACHE_ENABLED=True`
- `CACHE_KEY_PREFIX=dristi`
- `CACHALOT_ENABLED=True`
- `CACHALOT_TIMEOUT=120`
- `CACHALOT_CACHE=default`

Recommended behavior:

- If `CACHE_ENABLED=False` or in explicit debug scenarios, disable cachalot (`CACHALOT_ENABLED=False`) and/or switch to `DummyCache`.
- Use environment-specific key prefixes (`dristi-dev`, `dristi-prod`).

#### 1.1) Model-level control (via app/table configuration)

`django-cachalot` does not toggle caching per model class directly; control is done by **app labels** and **DB table names** (which map to models).

Recommended knobs:

- `CACHALOT_UNCACHABLE_APPS` — block entire apps.
- `CACHALOT_UNCACHABLE_TABLES` — block specific model tables.
- `CACHALOT_ONLY_CACHABLE_APPS` — allow-list apps.
- `CACHALOT_ONLY_CACHABLE_TABLES` — allow-list specific tables.

Example:

```python
CACHALOT_UNCACHABLE_TABLES = (
    "users_user",
    "authtoken_token",
    "django_session",
)
```

Model-to-table mapping reference:

```python
MyModel._meta.db_table
```

Policy for Dristi Phase 1:

- Start with allow-listing low-churn apps/tables (for example `locations_*`).
- Exclude auth/session/token and high-churn transactional tables.
- Expand cached scope gradually based on query-count and correctness checks.

### 2) What to cache first

Cachalot works at ORM query level, so initial focus is app/table scope.

Prioritize read-heavy, low-churn domains (for example):

- locations reference data,
- read-mostly catalog/config tables,
- dashboard reads that repeatedly hit the same filtered querysets.

Exclude volatile or sensitive tables early if needed.

### 3) Caching strategy

#### 3.1 ORM caching via cachalot (primary)

- Let cachalot cache eligible QuerySet results automatically.
- Use cachalot settings to include/exclude apps/tables as needed.
- Keep timeout moderate (`~120s`) for memory/safety balance.

#### 3.2 Manual/per-view caching (secondary, optional)

Use explicit `cache_page` or `cache.get/set` only when:

- endpoint output is not query-cache friendly,
- we need explicit response-level control,
- we need longer/shorter TTL than global cachalot policy.

### 4) Invalidation approach

Primary invalidation is automatic via cachalot table invalidation on writes.

Additional safeguards:

- Short to moderate timeout for high-churn environments.
- Targeted table/app exclusions when invalidation churn is too high.
- Optional manual key deletion only for special endpoint-level caches.

### 5) Safety and correctness rules

- Validate no cross-user data leakage for endpoints combining permissions + cached querysets.
- Exclude highly volatile or security-sensitive query paths where needed.
- Do not rely on cachalot for non-ORM dynamic content.
- Keep authenticated endpoint testing mandatory before rollout expansion.

### 6) Testing requirements

Add tests covering:

1. repeated identical queryset/API reads reduce DB query count,
2. write operations invalidate affected cached querysets,
3. excluded tables/apps are not cached,
4. cache-disabled mode behaves correctly.

### 7) Observability

- Track query count differences before/after cachalot on target endpoints.
- Add debug logging for cache-enabled mode and excluded scopes.
- Monitor Redis memory usage and key churn during rollout.
- In development, when Django Debug Toolbar and cachalot are enabled, add `"cachalot.panels.CachalotPanel"` to `DEBUG_TOOLBAR_PANELS` so cache behavior is visible during request profiling.

## Rollout plan

1. Add dependency + settings wiring for cachalot with Redis backend.
2. Enable in local/test with conservative timeout and limited scope.
3. Benchmark query count and latency on selected endpoints.
4. Tune exclusions/includes based on correctness and performance.
5. Enable in production with monitoring and rollback flag (`CACHALOT_ENABLED`).

## Acceptance criteria

- `django-cachalot` is installed and configured against Redis cache backend.
- Query count drops on repeated reads for selected endpoints.
- Writes invalidate cached querysets correctly.
- Sensitive/volatile scopes are excluded where necessary.
- Feature can be disabled quickly via settings/env toggle.

## Risks and mitigations

- **Unexpected stale reads**: mitigate with automatic write invalidation + moderate timeout.
- **Redis memory growth**: mitigate with scope exclusions and timeout tuning.
- **Hard-to-debug cache behavior**: mitigate with explicit toggle and focused logging.

## Future enhancements (optional)

- Add selective per-view caching for non-ORM heavy responses.
- Add cache observability dashboards (hit ratio, memory, evictions).
- Introduce resource-level cache versioning only if needed for stricter control.
