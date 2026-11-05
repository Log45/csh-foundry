// Test-only fetch adapter bridges the actual SDK to FastAPI TestClient over JSON lines.
import { createInterface } from "node:readline";
import assert from "node:assert/strict";
import { createFoundryClient } from "../../packages/typescript-sdk/dist/index.js";
const lines = createInterface({ input: process.stdin });
const input = lines[Symbol.asyncIterator]();
async function rpc(message) {
  process.stdout.write(JSON.stringify(message) + "\n");
  return JSON.parse((await input.next()).value);
}
const cfg = JSON.parse((await input.next()).value);
function client(actor = "admin", tenant = cfg.tenant) {
  return createFoundryClient({
    tenantId: tenant,
    principalId: actor,
    sessionKey: "test-session",
    auth: { csrf: "test-csrf" },
    readRetries: 0,
    fetch: async (_url, init) => {
      const r = await rpc({
        actor,
        headers: init.headers,
        envelope: JSON.parse(init.body),
      });
      return Response.json(r.body, { status: r.status });
    },
  });
}
const c = client();
if (cfg.scenario === "governed-processing") {
  const fn = await c.functions.create({
    path: { project_id: cfg.project },
    body: { name: "SDK function" },
  });
  const path = { function_id: fn.id };
  const version = await c.functions.publish({
    path,
    body: {
      implementation: "text.normalize.v1",
      input_schema: { text: { type: "string" } },
      output_schema: { result: { type: "string" } },
    },
  });
  const body = {
    definition_id: version.id,
    inputs: { text: " SDK " },
    idempotency_key: "sdk-run",
  };
  const run = await c.functions.invoke({ path, body });
  assert.equal((await c.functions.invoke({ path, body })).id, run.id);
  await rpc({ work: true });
  assert.equal(
    (await c.execution.get({ path: { job_id: run.id } })).state,
    "SUCCEEDED",
  );
  assert.deepEqual(
    (await c.functions.result({ path: { job_id: run.id } })).values,
    { result: "sdk" },
  );
  const auto = await c.automations.create({
    path: { project_id: cfg.project },
    body: { name: "SDK automation" },
  });
  const autoPath = { automation_id: auto.id };
  const published = await c.automations.publish({
    path: autoPath,
    body: {
      trigger: { kind: "manual" },
      function_id: fn.id,
      function_definition_id: version.id,
      inputs: { text: " AUTO " },
    },
  });
  await c.automations.activate({
    path: autoPath,
    body: { definition_id: published.id, enabled: true },
  });
  const receipt = await c.automations.trigger({
    path: autoPath,
    body: { idempotency_key: "once" },
  });
  assert.equal(
    (
      await c.automations.trigger({
        path: autoPath,
        body: { idempotency_key: "once" },
      })
    ).id,
    receipt.id,
  );
  await rpc({ work: true });
  assert.deepEqual(
    (await c.functions.result({ path: { job_id: receipt.job_id } })).values,
    { result: "auto" },
  );
  const set = await c.mediaSets.create({
    path: { project_id: cfg.project },
    body: { name: "SDK media" },
  });
  const setPath = { set_id: set.id };
  const item = await c.mediaSets.attach({
    path: setPath,
    body: {
      artifact_id: cfg.artifact,
      artifact_version_id: cfg.version,
      media_type: "image/png",
    },
  });
  const snapshot = await c.mediaSets.publish({
    path: setPath,
    body: { items: [item.id] },
  });
  assert.equal(
    (
      await c.mediaSets.items({
        path: setPath,
        query: { version_id: snapshot.id },
      })
    )[0].id,
    item.id,
  );
  assert.equal(
    (await c.mediaSets.lineage({ path: { ...setPath, item_id: item.id } }))
      .checksum,
    cfg.checksum,
  );
} else if (cfg.scenario === "partial") {
  const run = await c.execution.get({ path: { job_id: cfg.job } });
  assert.equal(run.state, "CANCELLED");
  assert.equal(run.metrics.created, 100);
  const records = await c.mappings.provenance({
    path: { run_id: cfg.job },
    query: { limit: 100 },
  });
  assert.equal(records.length, 100);
  const visible = await c.objects.query({
    path: { ontology_id: "manufacturing", type_id: "Factory" },
    body: { object_type: "Factory", limit: 200 },
  });
  assert.equal(visible.items.length, 100);
  assert.deepEqual(
    new Set(visible.items.map((item) => item.object_id)),
    new Set(records.map((record) => record.target.id)),
  );
  const identity = records[0].target;
  assert.equal(
    (
      await c.objects.get({
        path: { ontology_id: "manufacturing", type_id: identity.type },
        query: { object_id: identity.id },
      })
    ).object_id,
    identity.id,
  );
} else if (cfg.scenario === "actions") {
  const path = {
    ontology_id: "manufacturing",
    action_id: "UpdateMachineStatus",
  };
  const body = {
    idempotency_key: "sdk-action",
    parameters: {
      machineId: "MCH-001",
      newStatus: "STOPPED",
      expectedRevision: 1,
    },
  };
  const preview = await c.actions.preview({
    path,
    body: { parameters: body.parameters },
  });
  assert.equal(preview.advisory, true);
  const result = await c.actions.execute({ path, body });
  const replay = await c.actions.execute({ path, body });
  assert.equal(replay.execution_id, result.execution_id);
  const audit = await c.actions.audit({
    path: { ontology_id: "manufacturing", execution_id: result.execution_id },
  });
  assert.ok(audit.length);
  const object = await c.objects.get({
    path: { ontology_id: "manufacturing", type_id: "Machine" },
    query: { object_id: "MCH-001" },
  });
  assert.equal(object.properties.operationalStatus, "STOPPED");
} else {
  const source = { path: { dataset_id: cfg.dataset, version_id: cfg.version } };
  assert.equal(
    (await c.datasets.get({ path: { dataset_id: cfg.dataset } })).id,
    cfg.dataset,
  );
  assert.ok(
    (await c.datasets.versions({ path: { dataset_id: cfg.dataset } })).length,
  );
  assert.equal((await c.datasets.schema(source))[0].name, "id");
  assert.equal(
    (await c.datasets.preview({ ...source, query: { limit: 1 } })).rows.length,
    1,
  );
  assert.ok(
    (await c.projects.resources({ path: { project_id: cfg.project } })).some(
      (r) => r.id === cfg.mapping,
    ),
  );
  const path = { ontology_id: "manufacturing", type_id: "Factory" };
  const created = await c.objects.create({
    path,
    body: {
      object_id: "SDK-CREATE",
      properties: {
        factoryId: "SDK-CREATE",
        factoryName: "SDK",
        location: "North",
      },
    },
  });
  assert.equal(created.version, 1);
  assert.equal(
    (
      await c.objects.update({
        path,
        query: { object_id: "SDK-CREATE" },
        body: { expected_version: 1, properties: { factoryName: "Updated" } },
      })
    ).version,
    2,
  );
  await assert.rejects(
    () =>
      c.objects.update({
        path,
        query: { object_id: "SDK-CREATE" },
        body: { expected_version: 1, properties: {} },
      }),
    (e) => e.status === 409,
  );
  const page = await c.objects.query({
    path,
    body: { object_type: "Factory", limit: 1 },
  });
  assert.equal(page.items.length, 1);
  assert.ok(page.next_cursor);
  const next = await c.objects.query({
    path,
    body: { object_type: "Factory", limit: 1, cursor: page.next_cursor },
  });
  assert.notEqual(page.items[0].object_id, next.items[0].object_id);
  const run = await c.pipelines.start({
    path: { pipeline_id: cfg.pipeline },
    body: cfg.pipelineBody,
  });
  await rpc({ work: true });
  const status = await c.execution.get({ path: { job_id: run.id } });
  assert.equal(status.state, "SUCCEEDED");
  assert.ok(
    (
      await c.datasets.lineage({
        path: {
          dataset_id: status.output_dataset_id,
          version_id: status.output_version_id,
        },
      })
    ).length,
  );
  const preview = await c.mappings.preview({
    path: { mapping_id: cfg.mapping },
    body: cfg.mappingBody,
  });
  assert.equal(preview.validation, "sample-only");
  const materialization = await c.mappings.start({
    path: { mapping_id: cfg.mapping },
    body: cfg.mappingBody,
  });
  await rpc({ work: true });
  const result = await c.execution.get({
    path: { job_id: materialization.id },
  });
  assert.equal(result.state, "SUCCEEDED");
  assert.equal(result.metrics.created, 2);
  assert.equal(
    (await c.mappings.provenance({ path: { run_id: materialization.id } }))
      .length,
    2,
  );
  const other = client("admin", "00000000-0000-0000-0000-000000000001");
  await assert.rejects(
    () => other.datasets.get({ path: { dataset_id: cfg.dataset } }),
    (e) => e.status === 403,
  );
  const reader = client("alice");
  assert.equal(
    (await reader.datasets.get({ path: { dataset_id: cfg.dataset } })).id,
    cfg.dataset,
  );
  await assert.rejects(
    () =>
      reader.mappings.start({
        path: { mapping_id: cfg.mapping },
        body: cfg.mappingBody,
      }),
    (e) => [403, 404].includes(e.status),
  );
}
await rpc({ done: true });

lines.close();
process.stdin.destroy();
