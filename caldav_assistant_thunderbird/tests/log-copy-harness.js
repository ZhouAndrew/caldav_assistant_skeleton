"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const nodes={};
let copied;
const c=vm.createContext({document:{getElementById:id=>nodes[id] ||= {value:"",textContent:"",addEventListener(){}}},navigator:{clipboard:{async writeText(t){copied=t;}}},AssistantStorage:{localDateKey:()=>"2026-10-11"}});
vm.runInContext(fs.readFileSync("addon/logs.js","utf8").replace(/load\(\);\s*loadDiagnostics\(\);\s*$/,""),c);
c.sample={timestamp:"2026-10-11T03:00:00Z",scope:"workflow",success:false,action:"stop",details:{id:"receipt-1",outcome:"uncertain",verified:false,target:{id:"task-1"},expected:{status:"NEEDS-ACTION"},actual:null,error:"Read-back timed out",steps:[{operation:"write task",success:true}]}};
(async()=>{
const text=vm.runInContext("visibleText([sample])",c);
for(const value of ["结果待核实","receipt-1","task-1","NEEDS-ACTION","actual: null","verified: false","Read-back timed out","write task","2026-10-11T03:00:00Z"])assert.ok(text.includes(value),value);
assert.equal(vm.runInContext("resultText({...sample,details:{reconciled:true}})",c),"ℹ 已同步；请求操作未执行");
await vm.runInContext('copyText("diagnostic","copied")',c);assert.equal(copied,"diagnostic");
c.navigator.clipboard.writeText=async()=>{throw Error("clipboard denied");};
await vm.runInContext('copyText("diagnostic","copied")',c);assert.ok(nodes["log-status"].textContent.includes("clipboard denied"));
await vm.runInContext('copyText("","copied")',c);assert.equal(nodes["log-status"].textContent,"没有可复制的日志。");
vm.runInContext('records=[sample,{...sample,scope:"system"}]',c);nodes.scope.value="workflow";assert.equal(vm.runInContext("filteredRecords().length",c),1);
console.log("Log copy evidence/filter/clipboard tests: PASS");
})().catch(e=>{console.error(e);process.exitCode=1;});
