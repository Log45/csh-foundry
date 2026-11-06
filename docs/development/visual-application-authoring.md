# Visual application authoring

In Studio, open Projects, choose an owned Project and open **Create application**. Supply a name.
The registry creates an APPLICATION UUID independent of its name or folder. Use normal resource
rename, folder move, share and archive controls. Shared viewers can open published versions;
only owner-Project editors can author. Each actor has a private current draft.

Open **Open application builder**. Add pages; choose a widget in the palette and insert it. Select
components in the tree to configure labels, text, container parent, row/column/grid layout, spacing,
source, state, columns, options, navigation target, visibility or action. Move up/down and delete are
keyboard-accessible buttons. Dangling references after deletion remain visible validation errors;
publication never silently repairs them. Preview uses the same document and renderer.

Register a published ontology version in the Project first, or explicitly share a registered asset
from another Project. Select it under **Registered ontology resource**. Add an object query, metric,
or published action binding. Source inspectors configure projection, sorting, page size, relationship
traversal and filter bindings. Bind source results to a table/list and bind its selection state to a
detail/property/status widget. Inputs update their state; binding filters to that state refreshes the
server query. Related-object queries can filter the starting object by selected `$id`, then traverse.
No browser filtering substitutes for server queries.

Action bindings expose exact published parameters and types. Choose literal, input state or selected
object properties; `$id` and `$version` provide stable object identity and optimistic revision. Attach
the binding to an action widget. Preview is advisory; execution rechecks all permissions, preconditions
and current versions. Confirmation is explicit. Successful actions clear selections and refresh data.
Failures show structured codes. An ambiguous failure retains the idempotency key for an explicit retry.

Save, validate, resolve diagnostics, then publish. Revision conflicts require recovering local edits
against a reopened draft; there is no silent overwrite or automatic merge. Publication only reads the
saved revision. Identical content returns its existing publication. Version links open the runtime
without mounting the editor. Historical versions remain immutable and addressable. Version history is
bounded to the initial 50 entries in this editor; the API supports pagination.

## Manufacturing walkthrough

Use disposable test data or an existing authorized manufacturing ontology with `Machine` properties
`machineId`, `machineName`, `operationalStatus`, `temperatureCelsius`, and the published
`UpdateMachineStatus` action from `ontologies/examples/manufacturing-actions.json`. Register its
published ontology version through normal Project controls. The schema must be active.

Select that resource and click **Insert manufacturing dashboard**. This creates two pages, a status
filter, machine table, selection detail, factory traversal where `locatedInFactory` exists, canonical
count aggregate, status input and governed action binding. Review the component tree and inspectors,
save, validate and preview. Publish and open version
1. Filter machines, select one, choose a new status, preview and confirm the action. The resulting
execution ID identifies canonical audit history. Refresh reads live values. Reopen the publication
link; newer drafts and publications do not change its configuration.

## Compatibility and permissions

Dependencies use exact registered ontology version identity. Runtime requires that version to remain
active; rebinding and republishing is explicit after schema activation. Old drafts remain recoverable
when their registered dependency is still authorized and published. Old publication documents remain
stored even when incompatible; runtime retrieval fails closed until compatible access is restored.
Use each dependency inspector to select a new exact registered version; unused dependency references can be removed after their sources/action bindings are removed. Publication revalidates all contracts. Live object values are not immutable snapshots. App sharing never shares its dependencies. Sharing
those dependencies never grants object/property/action permissions. No private names or schemas are
included in unavailable-dependency diagnostics. Browser sessions and CSRF remain the existing BFF.
No public hosting, arbitrary JavaScript, OAuth clients, CRDT collaboration or application bundle builds.
