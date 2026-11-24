# CMS scenarios

Scenario IDs for the CMS API tests (spec 0037 §15). Each table row maps to a
test tagged `@pytest.mark.scenario("<ID>-<#>")` — row 2 of `CMS-PAGES` is
`CMS-PAGES-2`. IDs are assigned manually; once a test carries one it is never
renumbered or reused.

```bash
cd src
pytest --scenario CMS-PAGES-2                          # run one scenario
pytest apps/cms --scenario-report scenario-map.json    # regenerate the ID → test map
```

## Pages API — list & fetch seeded pages

ID: CMS-PAGES
Endpoints: `GET /api/v1/cms/pages/` · `GET /api/v1/cms/pages/slug/{slug}/`

| # | Given | When | Then |
|---|-------|------|------|
| 1 | 3 pages from the `cms.0002` migration + 3 pages seeded via `manage.py seed` | list pages | 200, `count`=6, results contain exactly those 6 slugs, paginated envelope with `meta` |
| 2 | a page seeded from TOML with every field set | fetch it by slug | 200, `slug`/`title`/`sub_title`/`main_image_url`/`content_type`/`content` returned verbatim from the TOML, `id`/`created_at`/`updated_at`/`meta` present (3 pages, parametrized) |
| 3 | `fee-refund-policy` seeded with `categories = ["guides", "policies"]` | fetch it by slug | both categories nested as `{id, name, slug}`, ordered by name |
| 4 | `kerala-courts-overview` seeded with no `categories` key | fetch it by slug | 200, `categories` is `[]` |
| 5 | no page with slug `seeded-nowhere` | fetch it by slug | 404 with standard error envelope, code `E00105`, no `field` |

Notes:

- State is seeded **once per module** through `manage.py seed` from
  `apps/cms/tests/data/{categories,pages}.toml` — the product's own
  reference-data path (spec 0025), not factories or ORM writes. The TOML files
  are the single source of truth for every expected value in the table.
- Seed is insert-only, so fixture slugs must never collide with the
  migration-seeded `terms` / `privacy` / `support` — a collision would
  silently keep the existing row and the tests would validate migration data.
- Tests: `apps/cms/tests/integration/test_seeded_pages_api.py`
  (`pytest apps/cms -m integration`).

