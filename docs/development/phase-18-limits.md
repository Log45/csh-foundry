# Phase 18 visual pipeline limits

| Limit                       |                                                      Default | Enforcement                                                                     |
| --------------------------- | -----------------------------------------------------------: | ------------------------------------------------------------------------------- |
| Graph format                |                                               version 1 only | Pydantic request/draft/publication validation                                   |
| Nodes                       |                                                          118 | Graph contract; accommodates 16 sources, 100 operations, output and placeholder |
| Edges                       |                                                          216 | Graph contract before graph algorithms                                          |
| Serialized graph            |                               256 KiB API; 512 KiB SQL guard | Pydantic canonical JSON and PostgreSQL check                                    |
| Node configuration          |                                                       16 KiB | Graph contract                                                                  |
| Identifier                  |                                         1–80 safe characters | Graph contract                                                                  |
| Diagnostics                 |                                                          256 | Compiler accumulator and response contract                                      |
| Canonical sources           |                                                           16 | Existing Phase 14 `Definition`                                                  |
| Canonical operations        |                                                          100 | Existing Phase 14 `Definition`                                                  |
| Columns/mappings/aggregates |                                   256 per bounded collection | Existing canonical contracts                                                    |
| Expression depth            |                                                           16 | Existing canonical validator, including disconnected draft nodes                |
| Drafts                      |                  one current draft per tenant/pipeline/actor | Composite primary key                                                           |
| Draft writes                |                              exact revision compare-and-swap | Row lock, service check and SQL increment trigger                               |
| Published graph revisions   |                           one immutable graph per definition | FK/primary key and update/delete trigger                                        |
| Dataset schema/preview      | existing bounded dataset endpoints; preview at most 100 rows | Dataset API                                                                     |
| Definition/run history      |                                         at most 100 per page | Existing pagination                                                             |

Compilation is linear in the bounded node/edge document plus deterministic sorting. It uses metadata-only
empty Polars frames and does not read source bytes. Existing 1 GiB source, worker CPU/memory/disk/wall,
queue, concurrency and artifact limits are unchanged. No compilation-time setting weakens Phase 14 or
Phase 17 execution limits.
