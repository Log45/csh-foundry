# Studio lineage navigation

Open **Lineage & observability** in the authenticated workspace. Select a Project, a resource and an
immutable version, then choose upstream/downstream and **Explore lineage**. Nodes can be selected on
the graph or in the keyboard-accessible table. The evidence table distinguishes design relationships,
execution history and certainty. Graph selection is retained after request errors. Private resources
are pruned, not represented by placeholders. Pending indexing has an explicit incomplete-history state.

Use **Reconcile history batch** to advance historical indexing when you have Project write authority.
Use **Analyze downstream impact** for structured dependency reasons and bounded witness paths. A
historical consumer does not prove impact from a future change. Use **Inspect column lineage** on a
published DAG definition to inspect separate VALUE, ROW and ORDER dependencies. Unsupported historical
metadata is reported rather than inferred.

The same view provides a bounded observability summary, paged resource execution history, execution
inspection, real publication state/outputs, node timings, safe errors/metrics, dataset freshness policies
and operational events. No policy is DISABLED; no successful version is UNKNOWN when enabled. A failed
execution never removes the last successful version. No polling is needed: explicit refreshes bound
network activity. Existing Project resource views remain the canonical authoring/download surfaces.
Session/tenant changes remount this view and clear selections/results through the existing workspace
scope. The BFF remains responsible for CSRF and server-held tokens.
