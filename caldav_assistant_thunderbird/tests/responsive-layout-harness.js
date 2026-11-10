"use strict";
// No browser/Thunderbird dependency: keep essential small-window CSS invariants
// visible to CI. Real resize/zoom acceptance is a separate manual release gate.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../addon");
const css = fs.readFileSync(path.join(root, "workspace.css"), "utf8");
for (const page of ["workspace", "today", "record", "logs", "wordpress", "tools"]) {
  const html = fs.readFileSync(path.join(root, page + ".html"), "utf8");
  assert.match(html, /href="workspace\.css"/, page + " must share responsive styles");
  assert.match(html, /<main>/, page + " must have a scrollable document layout");
}

assert.match(css, /\.tool-nav\s*\{[^}]*flex-wrap:\s*wrap/s);
assert.match(css, /\.tool-grid\s*\{[^}]*minmax\(0,\s*1fr\)/s);
assert.match(css, /@media\s*\(max-width:\s*820px\)/);
assert.match(css, /@media\s*\(max-width:\s*480px\)/);
assert.match(css, /@media\s*\(max-width:\s*320px\)/);
assert.match(css, /@media\s*\(max-height:\s*480px\)/);
assert.match(css, /\[hidden\]\s*\{\s*display:\s*none\s*!important;/);
assert.match(css, /\.form-grid label\.checkbox-row\s*\{\s*display:\s*flex/);
assert.match(css, /\.inline-confirm\s*>\s*button\s*\{\s*flex:\s*1\s+1\s+42%/);
assert.match(css, /table\s*\{[^}]*overflow-x:\s*auto/s);
assert.match(css, /#current-title\s*\{\s*overflow-wrap:\s*anywhere;/);
assert.match(css, /#post-preview\s*\{[^}]*height:\s*40vh/s);
assert.doesNotMatch(css, /main\s*\{[^}]*min-width:\s*[3-9]\d\dpx/s);

let balance = 0;
for (const char of css) {
  if (char === "{") balance++;
  if (char === "}") balance--;
  assert.ok(balance >= 0, "unmatched closing CSS brace");
}
assert.equal(balance, 0, "unclosed CSS block");
console.log("Responsive Thunderbird layout static regression: PASS");
