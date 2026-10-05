"use strict";
const {spawnSync}=require("node:child_process");
const {readdirSync}=require("node:fs");
for (const name of readdirSync("tests").filter(n=>n.endsWith("-harness.js")).sort()) {
 const result=spawnSync(process.execPath,["tests/"+name],{stdio:"inherit"});
 if(result.status!==0)process.exit(result.status || 1);
}
console.log("All Thunderbird plugin tests: PASS");
