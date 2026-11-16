# Query guide

Run from the installed skill directory, or use the script's absolute path.

| Operation | Example |
|---|---|
| Tags | `python scripts/kb_query.py --tags` |
| Datasets | `python scripts/kb_query.py --list` |
| Select tag | `python scripts/kb_query.py --list --tag Engineering` |
| Check settings | `python scripts/kb_query.py --check -d "Release Notes"` |
| Metadata fields | `python scripts/kb_query.py --fields -d "Release Notes"` |
| Search | `python scripts/kb_query.py "upgrade" -d "Release Notes"` |
| Filter search | `python scripts/kb_query.py "upgrade" -d "Release Notes" --filter Version is "2.0"` |
| Document names | `python scripts/kb_query.py --documents -d "Release Notes" --keyword upgrade` |
| Source segments | `python scripts/kb_query.py --read DOCUMENT_UUID -d "Release Notes" --page 1 --limit 10` |
| Local validation | `python scripts/kb_query.py "upgrade" --all --dry-run` |

Repeat `-d` or `--tag` for several datasets/tags. Selected tags form a union. `-d` and `--all` are mutually exclusive. `--all` means the selected allowed tag scope, never the entire workspace.

For `[Team]-01-Requirements`, aliases are `01` and `Requirements`. No fixed department/product aliases are included. Ambiguous aliases are rejected.

`--filter FIELD OPERATOR VALUE` supports `is` and `contains`, joined by AND. Definitions and returned metadata are checked; filters are never silently removed. Numeric/time filters are not supported in this release.

Limits: 1-250 query characters; 1-10 results per dataset; 8 filters; 20 queried datasets; 5 discovery pages per tag; 500 discovered datasets; 8 MiB per response. Source content/answers are capped at 4,000 characters and marked truncated. Document/segment pagination accepts `--page` and `--limit`.

Output is JSON with source identifiers, document names, scores, metadata, and positions. Check errors and truncation before answering. `--json` is retained for compatibility.

The client uses a fixed route allowlist, rejects redirects, ignores ambient proxies, and does not automatically retry failed queries. Adapt and verify deployments requiring a different API contract or proxy rather than weakening checks during a query.
