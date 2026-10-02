"use strict";

const fs = require("fs");
const vm = require("vm");

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

class XulNode {
  constructor(name, id = null) {
    this.localName = name;
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.attributes = new Map();
    this.parentNode = null;
    this.hidden = false;
    this.collapsed = false;
    this.classList = { contains: () => false };
  }
  setAttribute(k, v) { this.attributes.set(k, String(v)); }
  getAttribute(k) { return this.attributes.get(k) ?? null; }
  hasAttribute(k) { return this.attributes.has(k); }
  toggleAttribute(k, force) {
    if (force === false) this.attributes.delete(k);
    else this.attributes.set(k, "");
  }
  appendChild(n) { n.parentNode = this; this.children.push(n); return n; }
  insertBefore(n, before) {
    n.parentNode = this;
    const i = this.children.indexOf(before);
    if (i < 0) this.children.push(n); else this.children.splice(i, 0, n);
    return n;
  }
  replaceChildren(...nodes) {
    this.children = [];
    for (const n of nodes) this.appendChild(n);
  }
  addEventListener() {}
  removeEventListener() {}
  querySelectorAll() { return []; }
  closest() { return null; }
  getBoundingClientRect() { return { width: 100, height: 100 }; }
}

function makeStandalone(id, calendarId = "cal") {
  const task = {
    id,
    calendar: { id: calendarId, getProperty: () => null },
    recurrenceId: null,
    parentItem: null,
    percentComplete: 0,
    isCompleted: false,
    completedDate: null,
    status: null,
    priority: 0,
    categories: [],
    clone() {
      const c = makeStandalone(this.id, this.calendar.id);
      c.percentComplete = this.percentComplete;
      c.isCompleted = this.isCompleted;
      c.completedDate = this.completedDate;
      c.status = this.status;
      c.priority = this.priority;
      c.categories = [...this.categories];
      return c;
    },
    QueryInterface() { return this; },
    getProperty(name) {
      if (name === "STATUS") return this.status;
      return null;
    },
    deleteProperty(name) {
      if (name === "STATUS") this.status = null;
    },
    getCategories() { return [...this.categories]; },
    setCategories(v) { this.categories = [...v]; },
  };
  task.parentItem = task;
  return task;
}

function makeRecurringParent(id, occurrenceIds, calendarId = "cal") {
  const originals = new Map();
  const parent = {
    id,
    calendar: { id: calendarId, getProperty: () => null },
    recurrenceInfo: {},
    clone() {
      const modified = [];
      const clonedOccurrences = new Map();
      for (const [rid, occ] of originals) {
        const clone = makeStandalone(occ.id, calendarId);
        clone.recurrenceId = rid;
        clone.parentItem = this;
        clone.percentComplete = occ.percentComplete;
        clone.priority = occ.priority;
        clone.status = occ.status;
        clonedOccurrences.set(rid, clone);
      }
      const p = {
        id: this.id,
        calendar: this.calendar,
        recurrenceInfo: {
          modified,
          getOccurrenceFor(rid) { return clonedOccurrences.get(rid); },
          modifyException(occ) { modified.push(occ); },
        },
        QueryInterface() { return this; },
      };
      return p;
    },
    QueryInterface() { return this; },
  };
  for (const rid of occurrenceIds) {
    const occ = makeStandalone(id + "-" + rid, calendarId);
    occ.recurrenceId = rid;
    occ.parentItem = parent;
    originals.set(rid, occ);
  }
  parent.recurrenceInfo.getOccurrenceFor = rid => originals.get(rid);
  return { parent, occurrences: [...originals.values()] };
}

const toolbar = new XulNode("hbox", "task-actions-toolbar");
const completed = new XulNode("toolbarbutton", "task-actions-markcompleted");
toolbar.appendChild(completed);

const tree = new XulNode("tree", "calendar-task-tree");
tree.classList = { contains: name => name === "calendar-task-tree" };
tree.selectedTasks = [];

const elements = new Map([
  ["task-actions-toolbar", toolbar],
  ["task-actions-markcompleted", completed],
  ["calendar-task-tree", tree],
]);

global.document = {
  activeElement: null,
  getElementById(id) { return elements.get(id) ?? null; },
  createXULElement(name) {
    const n = new XulNode(name);
    Object.defineProperty(n, "id", {
      get() { return this._id ?? null; },
      set(v) { this._id = v; if (v) elements.set(v, this); },
      configurable: true,
    });
    return n;
  },
  querySelector() { return null; },
};

global.Ci = { calITodo: Symbol("calITodo") };
global.cal = {
  category: { fromPrefs: () => [] },
  view: { formatStringForCSSRule: x => x.replace(/\W+/g, "-") },
};
global.gTabmail = null;
global.editToDoStatus = () => { throw new Error("editor path should not be used"); };
global.editConfigState = () => { throw new Error("editor path should not be used"); };

let batchStarts = 0;
let batchEnds = 0;
let tx = [];
global.startBatchTransaction = () => { batchStarts++; };
global.endBatchTransaction = () => { batchEnds++; };
global.doTransaction = (...args) => { tx.push(args); };

const originalProgress = function originalProgress() {};
const originalPriority = function originalPriority() {};
global.contextChangeTaskProgress = originalProgress;
global.contextChangeTaskPriority = originalPriority;

global.taskDetailsView = {
  loadCategories() {},
  saveCategories() {},
  categoryTextboxKeypress() {},
};

const code = fs.readFileSync("addon/content/taskfix-window.js", "utf8");
vm.runInThisContext(code, { filename: "taskfix-window.js" });

assert(global.contextChangeTaskProgress !== originalProgress, "progress handler was not patched");
assert(global.contextChangeTaskPriority !== originalPriority, "priority handler was not patched");

tree.selectedTasks = [makeStandalone("a"), makeStandalone("b"), makeStandalone("c")];
tx = [];
global.contextChangeTaskProgress(100);
assert(tx.length === 3, "completion must modify all three selected ordinary tasks");
assert(tx.every(x => x[1].isCompleted === true && x[1].percentComplete === 100),
  "every selected ordinary task must be completed");

tx = [];
global.contextChangeTaskPriority(1);
assert(tx.length === 3, "priority must modify all selected ordinary tasks");
assert(tx.every(x => x[1].priority === 1), "priority value must apply to all selected tasks");

tx = [];
tree.selectedTasks = [makeStandalone("status")];
tree.selectedTasks[0].status = "CANCELLED";
tree.selectedTasks[0].percentComplete = 75;
global.contextChangeTaskStatus(null);
assert(tx.length === 1, "status clear must modify selected task");
assert(tx[0][1].status === null, "Not specified must remove STATUS");
assert(tx[0][1].percentComplete === 0, "Not specified must reset progress");

const recurring = makeRecurringParent("series", ["r1", "r2"]);
tree.selectedTasks = recurring.occurrences;
tx = [];
global.contextChangeTaskProgress(100);
assert(tx.length === 1, "two occurrences of the same recurring parent must use one parent transaction");
const modifiedParent = tx[0][1];
assert(modifiedParent.recurrenceInfo.modified.length === 2,
  "both selected recurring occurrences must become exceptions");
assert(modifiedParent.recurrenceInfo.modified.every(x => x.isCompleted === true),
  "every selected recurring occurrence must be completed");

global.__taskfixAddonCleanup();
assert(global.contextChangeTaskProgress === originalProgress, "cleanup must restore original progress handler");
assert(global.contextChangeTaskPriority === originalPriority, "cleanup must restore original priority handler");

assert(batchStarts === batchEnds, "batch transactions must be balanced");
console.log("taskfix-addon-harness: PASS");
