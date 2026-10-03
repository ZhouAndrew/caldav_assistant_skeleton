"use strict";

(() => {
  const NAV = [
    ["tasks", "task-picker.html", "navTaskPicker"],
    ["today", "today.html", "navToday"],
    ["logs", "logs.html", "navLogs"],
    ["record", "record.html", "Record"],
    ["tools", "tools.html", "navTools"],
    ["wordpress", "wordpress.html", "navWordPress"],
    ["settings", "settings.html", "navSettings"],
  ];

  function t(key, substitutions) {
    if (!key) return "";
    const translated = browser.i18n.getMessage(key, substitutions);
    return translated || key;
  }

  function localize(root = document) {
    for (const node of root.querySelectorAll("[data-i18n]")) {
      node.textContent = t(node.dataset.i18n);
    }
    for (const node of root.querySelectorAll("[data-i18n-placeholder]")) {
      node.setAttribute(
        "placeholder",
        t(node.dataset.i18nPlaceholder)
      );
    }
    try {
      document.documentElement.lang = browser.i18n.getUILanguage();
    } catch {
      // The page remains usable without a reported UI language.
    }
  }

  function renderNav() {
    const host = document.getElementById("app-nav");
    if (!host) return;
    const active = document.body.dataset.page || "";
    host.replaceChildren();

    for (const [id, href, key] of NAV) {
      const link = document.createElement("a");
      link.href = href;
      link.textContent = key === "Record" ? "Record" : t(key);
      link.className = id === active ? "active" : "";
      if (id === active) link.setAttribute("aria-current", "page");
      host.appendChild(link);
    }
  }

  async function rpc(message) {
    return browser.runtime.sendMessage(message);
  }

  function statusText(status) {
    const map = {
      "NEEDS-ACTION": "statusNeedsAction",
      "IN-PROCESS": "statusInProgress",
      COMPLETED: "statusCompleted",
      CANCELLED: "statusCancelled",
    };
    return t(map[status] || "") || String(status || "");
  }

  function formatElapsed(milliseconds) {
    const total = Math.max(0, Math.floor(Number(milliseconds || 0) / 1000));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    return [hours, minutes, seconds]
      .map(value => String(value).padStart(2, "0"))
      .join(":");
  }

  function formatDateTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(date);
  }

  function showMessage(element, text, kind = "info") {
    if (!element) return;
    element.textContent = text || "";
    element.hidden = !text;
    element.dataset.kind = kind;
  }

  window.AppUi = Object.freeze({
    t,
    localize,
    renderNav,
    rpc,
    statusText,
    formatElapsed,
    formatDateTime,
    showMessage,
  });

  document.addEventListener("DOMContentLoaded", () => {
    localize();
    renderNav();
  });
})();
