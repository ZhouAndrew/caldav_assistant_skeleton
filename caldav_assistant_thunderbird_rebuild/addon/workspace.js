"use strict";

const stateNode = document.getElementById("state");
const retryButton = document.getElementById("retry");

function show(value) {
  stateNode.textContent = JSON.stringify(value, null, 2);
}

async function load() {
  const result = await browser.runtime.sendMessage({type: "system.state"});
  show(result);
}

retryButton.addEventListener("click", async () => {
  retryButton.disabled = true;
  try {
    const result = await browser.runtime.sendMessage({type: "system.reconcile"});
    show(result);
  } finally {
    retryButton.disabled = false;
  }
});

void load();
