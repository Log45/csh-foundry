"""Deterministically bind the reviewed SDK surface to actual OpenAPI operations."""

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
schema = json.loads((ROOT / "apps/studio/lib/openapi.json").read_text())
# Explicit public capability selection; never expose security administration/internal operations.
manifest = {
    "ontologies": [
        ("list", "get", "/ontologies"),
        ("get", "get", "/ontologies/{ontology_id}"),
        ("objectTypes", "get", "/ontologies/{ontology_id}/object-types"),
        ("version", "get", "/ontologies/{ontology_id}/versions/{version}"),
    ],
    "objects": [
        ("query", "post", "/ontologies/{ontology_id}/objects/{type_id}/query"),
        ("get", "get", "/ontologies/{ontology_id}/objects/{type_id}"),
        ("create", "post", "/ontologies/{ontology_id}/objects/{type_id}"),
        ("update", "patch", "/ontologies/{ontology_id}/objects/{type_id}"),
        ("links", "get", "/ontologies/{ontology_id}/objects/{type_id}/links/{link_id}"),
    ],
    "actions": [
        ("preview", "post", "/ontologies/{ontology_id}/actions/{action_id}/preview"),
        ("execute", "post", "/ontologies/{ontology_id}/actions/{action_id}/execute"),
        ("history", "get", "/ontologies/{ontology_id}/actions/executions"),
        ("execution", "get", "/ontologies/{ontology_id}/actions/executions/{execution_id}"),
        ("audit", "get", "/ontologies/{ontology_id}/actions/executions/{execution_id}/audit"),
    ],
    "projects": [
        ("list", "get", "/projects"),
        ("resources", "get", "/projects/{project_id}/resources"),
    ],
    "datasets": [
        ("get", "get", "/datasets/{dataset_id}"),
        ("versions", "get", "/datasets/{dataset_id}/versions"),
        ("version", "get", "/datasets/{dataset_id}/versions/{version_id}"),
        ("schema", "get", "/datasets/{dataset_id}/versions/{version_id}/schema"),
        ("preview", "get", "/datasets/{dataset_id}/versions/{version_id}/preview"),
        ("lineage", "get", "/datasets/{dataset_id}/versions/{version_id}/lineage"),
        (
            "materializations",
            "get",
            "/datasets/{dataset_id}/versions/{version_id}/materializations",
        ),
    ],
    "execution": [
        ("get", "get", "/execution/jobs/{job_id}"),
        ("cancel", "post", "/execution/jobs/{job_id}/cancel"),
        ("retry", "post", "/execution/jobs/{job_id}/retry"),
    ],
    "mappings": [
        ("provenance", "get", "/materialization/runs/{run_id}/provenance"),
        (
            "objectSources",
            "get",
            "/ontologies/{ontology_id}/objects/{type_id}/{object_id}/materializations",
        ),
        ("linkSources", "get", "/ontologies/{ontology_id}/links/{link_type}/materializations"),
    ],
    "pipelines": [],
}
for family, ident in [("pipelines", "pipeline_id"), ("mappings", "mapping_id")]:
    base = "/" + family + "/{" + ident + "}"
    manifest[family] += [
        ("get", "get", base),
        ("validate", "post", base + "/validate"),
        ("publish", "post", base + "/definitions"),
        ("definitions", "get", base + "/definitions"),
        ("definition", "get", base + "/definitions/{definition_id}"),
        ("start", "post", base + "/runs"),
        ("history", "get", base + "/runs"),
    ]
for family, ident, group in [
    ("functions", "function_id", "functions"),
    ("automations", "automation_id", "automations"),
    ("media-sets", "set_id", "mediaSets"),
]:
    base = "/" + family + "/{" + ident + "}"
    manifest[group] = [
        ("create", "post", "/projects/{project_id}/" + family),
        ("get", "get", base),
        ("validate", "post", base + "/validate"),
        ("publish", "post", base + "/definitions"),
        ("definitions", "get", base + "/definitions"),
        ("definition", "get", base + "/definitions/{definition_id}"),
    ]
    if family == "functions":
        manifest[group] += [
            ("invoke", "post", base + "/runs"),
            ("history", "get", base + "/runs"),
            ("result", "get", "/function-runs/{job_id}/result"),
            ("provenance", "get", "/function-runs/{job_id}/provenance"),
        ]
    elif family == "automations":
        manifest[group] += [
            ("activate", "put", base + "/activation"),
            ("schedule", "get", base + "/schedule"),
            ("trigger", "post", base + "/trigger"),
            ("history", "get", base + "/runs"),
        ]
    else:
        manifest[group] += [
            ("attach", "post", base + "/items"),
            ("items", "get", base + "/items"),
            ("item", "get", base + "/items/{item_id}"),
            ("lineage", "get", base + "/items/{item_id}/lineage"),
        ]
manifest["mappings"].append(("preview", "post", "/mappings/{mapping_id}/preview"))
read_posts = {
    ("objects", "query"),
    ("actions", "preview"),
    ("pipelines", "validate"),
    ("mappings", "validate"),
    ("mappings", "preview"),
    ("functions", "validate"),
    ("automations", "validate"),
    ("mediaSets", "validate"),
}
lines = [
    "// Generated by scripts/generate_platform_sdk.py; do not edit.",
    'import type { operations } from "./schema.js";',
    'import type { Transport, RequestOptions } from "./transport.js";',
    """type Params<O> = O extends { parameters: infer P } ?
 (P extends { path: infer X } ? { path: X } : { path?: never }) &
 (P extends { query: infer Q } ? { query: Q } :
 P extends { query?: infer Q } ? { query?: Q } : { query?: never }) : never;
type Body<O> = O extends { requestBody: { content: { "application/json": infer B } } }
 ? { body: B } : { body?: never };
type Input<O> = Params<O> & Body<O>;
type Json<C> = C extends { content: { "application/json": infer J } } ? J : never;
type Output<O> = O extends { responses: infer R }
 ? Json<R[Extract<keyof R, 200 | 201 | 202>]> : never;""",
]
hooks = [
    "// Generated by scripts/generate_platform_sdk.py; do not edit.",
    'import type { EndpointInput, EndpointOutput } from "@foundry/sdk";',
    'import { useFoundryQuery, useFoundryMutation, type QueryOptions } from "./runtime.js";',
]
entries = []
for group, ops in manifest.items():
    for name, method, path in ops:
        full = "/api/v1" + path
        operation = schema["paths"][full][method]
        key = group + "." + name
        read = method == "get" or (group, name) in read_posts
        entries.append((group, name, key, method.upper(), full, operation["operationId"], read))
lines += (
    ["export interface EndpointInput {"]
    + [f'  "{k}": Input<operations["{op}"]>;' for _, _, k, _, _, op, _ in entries]
    + ["}", "export interface EndpointOutput {"]
    + [f'  "{k}": Output<operations["{op}"]>;' for _, _, k, _, _, op, _ in entries]
    + ["}"]
)
lines += ["export function endpoints(send: Transport) {", "return {"]
for group in manifest:
    lines += [group + ": {"]
    for g, name, key, method, path, _, read in entries:
        if group != g:
            continue
        lines += [
            f'{name}: (input: EndpointInput["{key}"], options?: RequestOptions): '
            f'Promise<EndpointOutput["{key}"]> => '
            f'send("{method}", "{path}", input, {str(read).lower()}, options),'
        ]
        hook = group[0].upper() + group[1:] + name[0].upper() + name[1:]
        if read:
            hooks += [
                f'export function use{hook}(input: EndpointInput["{key}"], '
                f'options?: QueryOptions) {{ return useFoundryQuery("{key}", input, '
                f"(c, signal) => c.{group}.{name}(input, {{signal}}), options); }}"
            ]
        else:
            hooks += [
                f'export function use{hook}() {{ return useFoundryMutation<EndpointInput["{key}"], '
                f'EndpointOutput["{key}"]>((c, input) => c.{group}.{name}(input)); }}'
            ]
    lines += ["},"]
lines += ["};", "}"]
# Run the installed formatter so generation checks compare final checked-in bytes.

for path, content in [
    ("packages/typescript-sdk/src/endpoints.ts", "\n".join(lines) + "\n"),
    ("packages/react-sdk/src/hooks.ts", "\n".join(hooks) + "\n"),
]:
    formatted = subprocess.run(
        [str(ROOT / "node_modules/.bin/prettier"), "--parser", "typescript"],
        input=content,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    target = ROOT / path
    if args.check:
        if not target.exists() or target.read_text() != formatted:
            raise SystemExit("Generated contract drift: " + path)
    else:
        target.write_text(formatted)
