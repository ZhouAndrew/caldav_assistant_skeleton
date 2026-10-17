import {mkdir} from "node:fs/promises";
import {build} from "esbuild";

await mkdir(new URL("../addon/generated/", import.meta.url), {recursive: true});

await build({
  entryPoints: [new URL("../src/runtime/core-api.ts", import.meta.url).pathname],
  bundle: true,
  format: "iife",
  globalName: "CalDAVAssistantCore",
  platform: "browser",
  target: ["firefox153"],
  outfile: new URL("../addon/generated/core.js", import.meta.url).pathname,
  sourcemap: false,
  minify: false,
  legalComments: "none",
});

console.log("clean-room browser core build: PASS");
