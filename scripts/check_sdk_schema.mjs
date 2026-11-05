import { readFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
const generated = execFileSync(
  process.execPath,
  [
    "node_modules/openapi-typescript/bin/cli.js",
    "apps/studio/lib/openapi.json",
    "--default-non-nullable",
    "false",
  ],
  { encoding: "utf8" },
);
const current = await readFile(
  new URL("../packages/typescript-sdk/src/schema.ts", import.meta.url),
  "utf8",
);
if (current !== generated)
  throw new Error("SDK OpenAPI schema drift; run npm run generate");
console.log("PASS generated schema drift");
