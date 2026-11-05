// Pack and install the actual artifacts into an isolated consumer, without publishing.
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { execFileSync } from "node:child_process";
const dir = await mkdtemp(join(tmpdir(), "foundry-consumer-"));
const run = (args, cwd = dir) =>
  execFileSync("npm", args, {
    cwd,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
try {
  const archives = [];
  for (const folder of ["packages/typescript-sdk", "packages/react-sdk"]) {
    const packed = JSON.parse(
      run(["pack", "--json", "--pack-destination", dir], resolve(folder)),
    )[0];
    archives.push(join(dir, packed.filename));
    if (
      packed.files.some(
        (f) =>
          !f.path.startsWith("dist/") &&
          !["README.md", "CHANGELOG.md", "package.json"].includes(f.path),
      )
    )
      throw new Error("Unexpected package payload");
  }
  await writeFile(
    join(dir, "package.json"),
    JSON.stringify({ private: true, type: "module" }),
  );
  run([
    "install",
    "--ignore-scripts",
    "--no-audit",
    "--no-fund",
    ...archives,
    "react@19.3.1",
    "typescript@5.9.3",
    "@types/react@19.3.0",
  ]);
  await writeFile(
    join(dir, "consumer.ts"),
    `import {createFoundryClient,type EndpointInput} from '@foundry/sdk';
import {FoundryProvider,useObjectsQuery,useExecution} from '@foundry/react';
const c=createFoundryClient({tenantId:'t',principalId:'p',sessionKey:'s',auth:{csrf:'csrf'}});
const input:EndpointInput['objects.query']={path:{ontology_id:'o',type_id:'T'},body:{object_type:'T',limit:10}};
void c.objects.query;void input;void FoundryProvider;void useObjectsQuery;void useExecution;
// @ts-expect-error Actions require the generated idempotency key.
c.actions.execute({path:{ontology_id:'o',action_id:'a'},body:{parameters:{}}});
// @ts-expect-error No arbitrary HTTP interface is public.
c.request('/internal/browser-state');
`,
  );
  execFileSync(
    process.execPath,
    [
      join(dir, "node_modules/typescript/bin/tsc"),
      "--noEmit",
      "--strict",
      "--skipLibCheck",
      "--module",
      "NodeNext",
      "--moduleResolution",
      "NodeNext",
      "--target",
      "ES2022",
      "consumer.ts",
    ],
    { cwd: dir, stdio: "pipe" },
  );
  execFileSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      "import {createFoundryClient} from '@foundry/sdk'; import {FoundryProvider} from '@foundry/react'; if(typeof createFoundryClient !== 'function'||typeof FoundryProvider !== 'function')process.exit(1)",
    ],
    { cwd: dir, stdio: "pipe" },
  );
  console.log(
    "PASS packed ESM imports, declarations, peer resolution and negative public types",
  );
} finally {
  await rm(dir, { recursive: true, force: true });
}
