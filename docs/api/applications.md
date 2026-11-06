# Applications API v1

All operations require the current authenticated tenant. Project write and owner-Project edit role
are cumulative for authoring. Discovery uses existing paginated Project `resources` endpoints with
`resource_type=APPLICATION` in each result; no duplicate resource discovery authority is added.

| Method | Path under /api/v1 | Result |
| --- | --- | --- |
| POST | /projects/{project_id}/applications | Registry ResourceView; name/description/folder |
| GET | /applications/{application_id} | Registry metadata |
| GET, PUT | /applications/{application_id}/draft | Private draft; save requires expected_revision and document |
| POST | /applications/{application_id}/validate | Strict document and structured diagnostics |
| GET, POST | /applications/{application_id}/versions | Paginated publications / publish saved expected_revision |
| GET | /applications/{application_id}/versions/{version_id} | Immutable document, digest, actor and dependency manifest |
| GET | /applications/{application_id}/versions/{version_id}/runtime | Currently authorized, compatible manifest |
| POST | /applications/{application_id}/versions/{version_id}/query | source_id, bounded state, cursor and optional order_by |
| POST | /applications/{application_id}/versions/{version_id}/actions/{binding_id}/preview | Canonical advisory ActionResult |
| POST | /applications/{application_id}/versions/{version_id}/actions/{binding_id}/execute | Canonical audited ActionResult |

Runtime action bodies use the existing ExecuteRequest contract (parameters, idempotency_key).
Gateways verify application/dependencies and delegate to QueryService/ActionExecutionService using
the same principal and PostgreSQL transaction. They do not implement alternate query or action logic.
Unsupported JSON constructs return existing structured 422 errors. Incomplete references yield
bounded diagnostics; invalid publication returns application_invalid. CAS conflicts return
409 draft_conflict. Unavailable registry identities retain non-enumerating not_found responses;
unavailable/incompatible manifests use fixed dependency_unavailable messages.

SDK endpoints and React hooks are generated from the actual OpenAPI contract:

```typescript
const app = await client.applications.create({
  path: { project_id: projectId }, body: { name: "Operations" },
});
const saved = await client.applications.saveDraft({
  path: { application_id: app.id },
  body: { expected_revision: 0, document },
});
const validation = await client.applications.validate({
  path: { application_id: app.id }, body: document,
});
if (validation.valid) {
  const version = await client.applications.publish({
    path: { application_id: app.id }, body: { expected_revision: saved.revision },
  });
  const manifest = await client.applications.runtime({
    path: { application_id: app.id, version_id: version.id },
  });
}
```

Generated hooks include useApplicationsDraft, useApplicationsSaveDraft, useApplicationsValidate,
useApplicationsPublish, useApplicationsVersions, useApplicationsRuntime and useApplicationsQuery.
Mount them in the existing FoundryProvider with a fresh SDK client per session/tenant generation.
Mutation hooks retain no automatic retries and invalidate that provider's isolated cache. Studio's
renderer uses the same generated core SDK with cancellation, bounded source concurrency and immediate
private-view teardown when the client is invalidated. No application credentials are introduced.
