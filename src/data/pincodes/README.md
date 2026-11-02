# Pincode data

`python manage.py import_pincodes` reads its files
from this folder when no path is given. The repository ships no pincode data:
whoever sets up an environment adds the CSV here and runs the import once.

| File | Committed? | What it is |
|------|------------|------------|
| `all_india_pincode_directory.csv` | No (git- and docker-ignored) | India Post's *All India Pincode Directory*, one row per post office |
| `aliases.json` | Yes, when added | Maps CSV spellings to our location codes (optional) |

## Loading pincodes

1. **Get the CSV** from
   https://www.data.gov.in/catalog/all-india-pincode-directory and save it here
   as `all_india_pincode_directory.csv`.
2. **Dry run**, then import. On an empty database, `--create-districts` also
   creates every state and district the CSV names (about 36 states/UTs and 750
   districts, under India):

   ```bash
   docker compose --env-file .env -f docker/docker-compose.yml exec web python manage.py import_pincodes --create-districts --dry-run
   docker compose --env-file .env -f docker/docker-compose.yml exec web python manage.py import_pincodes --create-districts
   ```

   Without `--create-districts`, pincodes go only under districts that already
   exist, and every other district is reported as unmatched. A district or
   state an admin has deactivated is never created again; its pincodes are
   reported and skipped until it is reactivated.
3. **Created names and codes.** States and districts get the CSV's name (in
   title case when the CSV writes it in capitals, e.g. `MYSURU` → `Mysuru`)
   and a generated code such as `IN_KARNATAKA_MYSURU`; codes too long for the
   field end in a short hash. Rename them in the admin if needed; matching is
   by `name` or `short_name`, so keep one of them close to the CSV spelling or
   add an alias.
4. **Unmatched names** (without `--create-districts`). The dry run lists CSV
   state and district names that match no district. Map them in
   `aliases.json` and run it again:

   ```json
   {
     "JAMMU AND KASHMIR": "IN_JK",
     "KARNATAKA / BANGALORE": "IN_KA_BLR_URBAN"
   }
   ```

   A key with no `/` maps a CSV state to a state code; `"STATE / DISTRICT"`
   maps one district to a district code.

Re-running is safe: existing pincodes are left as they are unless `--update`
is passed. See spec 0007 section 7 for the full behaviour.

## Without Docker, or on a server

Pass the path instead of using this folder:

```bash
python manage.py import_pincodes /path/to/all_india_pincode_directory.csv
```

On a production container, which does not include this folder's CSV, copy the
file in first:

```bash
docker compose -f docker/docker-compose.prod.yml cp all_india_pincode_directory.csv web:/tmp/pincodes.csv
docker compose -f docker/docker-compose.prod.yml exec web python manage.py import_pincodes /tmp/pincodes.csv
```
