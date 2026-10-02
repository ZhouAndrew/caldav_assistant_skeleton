"use strict";

var {
  ExtensionCommon: { ExtensionAPI, EventManager },
} = ChromeUtils.importESModule("resource://gre/modules/ExtensionCommon.sys.mjs");
var {
  ExtensionUtils: { ExtensionError },
} = ChromeUtils.importESModule("resource://gre/modules/ExtensionUtils.sys.mjs");
var { NetUtil } = ChromeUtils.importESModule(
  "resource://gre/modules/NetUtil.sys.mjs"
);
var { Subprocess } = ChromeUtils.importESModule(
  "resource://gre/modules/Subprocess.sys.mjs"
);
var { cal } = ChromeUtils.importESModule(
  "resource:///modules/calendar/calUtils.sys.mjs"
);
var { CalTodo } = ChromeUtils.importESModule(
  "resource:///modules/CalTodo.sys.mjs"
);
var { CalEvent } = ChromeUtils.importESModule(
  "resource:///modules/CalEvent.sys.mjs"
);

const TASK_STATUSES = new Set([
  "",
  "NEEDS-ACTION",
  "IN-PROCESS",
  "COMPLETED",
  "CANCELLED",
]);

// These are Thunderbird's own task filter identifiers from the built-in
// task sidebar / calendar-task-tree. Keep the identifiers, not a copied
// reimplementation of their semantics.
const NATIVE_TASK_FILTERS = new Set([
  "throughcurrent",
  "throughtoday",
  "throughsevendays",
  "notstarted",
  "overdue",
  "completed",
  "open",
  "all",
]);

const LOG_FILE_PREFIX = "caldav-assistant-experimental-";
const LOG_FILE_SUFFIX = ".log";
const LOG_LEGACY_FILE_NAME = "caldav-assistant-experimental.log";
const LOG_MAX_BYTES = 1024 * 1024;
let legacyDiagnosticsMigrated = false;

function profileDirectory() {
  const directoryService = Cc["@mozilla.org/file/directory_service;1"]
    .getService(Ci.nsIProperties);
  return directoryService.get("ProfD", Ci.nsIFile);
}

function profileFile(name) {
  const file = profileDirectory().clone();
  file.append(name);
  return file;
}

function localDiagnosticDateKey(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return (
    String(date.getFullYear()).padStart(4, "0") + "-" +
    String(date.getMonth() + 1).padStart(2, "0") + "-" +
    String(date.getDate()).padStart(2, "0")
  );
}

function normalizeDiagnosticDateKey(value = "") {
  const text = String(value || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(text)
    ? text
    : localDiagnosticDateKey();
}

function diagnosticFile(dateKey = "") {
  const day = normalizeDiagnosticDateKey(dateKey);
  return profileFile(LOG_FILE_PREFIX + day + LOG_FILE_SUFFIX);
}

function diagnosticBackupFile(dateKey = "") {
  const day = normalizeDiagnosticDateKey(dateKey);
  return profileFile(LOG_FILE_PREFIX + day + LOG_FILE_SUFFIX + ".1");
}

function sanitizeLogDetails(value, depth = 0) {
  if (depth > 4) return "[depth-limit]";
  if (value === null || value === undefined) return value;
  if (value instanceof Error) {
    return {
      name: String(value.name || "Error"),
      message: String(value.message || value),
    };
  }
  if (Array.isArray(value)) {
    return value.slice(0, 30).map(item => sanitizeLogDetails(item, depth + 1));
  }
  if (typeof value === "object") {
    const output = {};
    for (const [key, item] of Object.entries(value).slice(0, 40)) {
      if (/pass(word)?|secret|token|authorization|credential/i.test(key)) {
        output[key] = "[redacted]";
      } else {
        output[key] = sanitizeLogDetails(item, depth + 1);
      }
    }
    return output;
  }
  if (typeof value === "string") return value.slice(0, 1000);
  if (typeof value === "number" || typeof value === "boolean") return value;
  return String(value);
}

function readFileText(file) {
  if (!file.exists()) return "";
  const input = Cc["@mozilla.org/network/file-input-stream;1"]
    .createInstance(Ci.nsIFileInputStream);
  input.init(file, 0x01, 0, 0);
  const converter = Cc["@mozilla.org/intl/converter-input-stream;1"]
    .createInstance(Ci.nsIConverterInputStream);
  converter.init(input, "UTF-8", 0, 0);
  let output = "";
  const chunk = {};
  while (converter.readString(0xffffffff, chunk) !== 0) {
    output += chunk.value;
  }
  converter.close();
  return output;
}

function appendRawDiagnosticLine(file, line) {
  const stream = Cc["@mozilla.org/network/file-output-stream;1"]
    .createInstance(Ci.nsIFileOutputStream);
  stream.init(file, 0x02 | 0x08 | 0x10, 0o600, 0);
  const converter = Cc["@mozilla.org/intl/converter-output-stream;1"]
    .createInstance(Ci.nsIConverterOutputStream);
  converter.init(stream, "UTF-8");
  converter.writeString(String(line || "").replace(/\n?$/, "\n"));
  converter.close();
}

function migrateLegacyDiagnostics() {
  if (
    legacyDiagnosticsMigrated ||
    typeof Cc === "undefined" ||
    typeof Ci === "undefined"
  ) {
    return;
  }
  legacyDiagnosticsMigrated = true;

  try {
    const legacy = profileFile(LOG_LEGACY_FILE_NAME);
    if (!legacy.exists()) return;

    const lines = readFileText(legacy).split(/\r?\n/).filter(Boolean);
    for (const line of lines) {
      let timestamp = null;
      try {
        timestamp = JSON.parse(line)?.ts || null;
      } catch (_error) {}
      const day =
        localDiagnosticDateKey(timestamp || new Date()) ||
        localDiagnosticDateKey();
      appendRawDiagnosticLine(diagnosticFile(day), line);
    }

    legacy.remove(false);
    const oldBackup = profileFile(LOG_LEGACY_FILE_NAME + ".1");
    if (oldBackup.exists()) oldBackup.remove(false);
  } catch (error) {
    console.warn(
      "[CalDAVAssistant] legacy diagnostics migration failed",
      error
    );
  }
}

function appendDiagnosticLog(component, event, details = {}) {
  if (typeof Cc === "undefined" || typeof Ci === "undefined") return "";

  try {
    migrateLegacyDiagnostics();
    const day = localDiagnosticDateKey();
    let file = diagnosticFile(day);

    if (file.exists() && file.fileSize > LOG_MAX_BYTES) {
      const backup = diagnosticBackupFile(day);
      if (backup.exists()) backup.remove(false);
      file.moveTo(null, backup.leafName);
      file = diagnosticFile(day);
    }

    appendRawDiagnosticLine(
      file,
      JSON.stringify({
        ts: new Date().toISOString(),
        component: String(component || "unknown"),
        event: String(event || "event"),
        details: sanitizeLogDetails(details),
      })
    );
    return file.path;
  } catch (error) {
    console.warn("[CalDAVAssistant] diagnostics write failed", error);
    return "";
  }
}

async function listDiagnosticsDatesApi() {
  if (typeof Cc === "undefined" || typeof Ci === "undefined") return [];
  migrateLegacyDiagnostics();

  const dates = [];
  const entries = profileDirectory().directoryEntries;
  while (entries.hasMoreElements()) {
    const file = entries.getNext().QueryInterface(Ci.nsIFile);
    const match =
      /^caldav-assistant-experimental-(\d{4}-\d{2}-\d{2})\.log$/.exec(
        file.leafName
      );
    if (match) dates.push(match[1]);
  }
  return [...new Set(dates)].sort().reverse();
}

async function diagnosticsInfoApi(dateKey = "") {
  if (typeof Cc === "undefined" || typeof Ci === "undefined") {
    return {
      date: "",
      path: "",
      backupPath: "",
      exists: false,
      size: 0,
      maxBytes: LOG_MAX_BYTES,
    };
  }

  migrateLegacyDiagnostics();
  const day = normalizeDiagnosticDateKey(dateKey);
  const file = diagnosticFile(day);
  const backup = diagnosticBackupFile(day);
  return {
    date: day,
    path: file.path,
    backupPath: backup.path,
    exists: file.exists(),
    size: file.exists() ? Number(file.fileSize || 0) : 0,
    backupExists: backup.exists(),
    maxBytes: LOG_MAX_BYTES,
  };
}

async function readDiagnosticsApi(limit = 500, dateKey = "") {
  if (typeof Cc === "undefined" || typeof Ci === "undefined") {
    return {date: "", path: "", lines: [], text: ""};
  }

  migrateLegacyDiagnostics();
  const day = normalizeDiagnosticDateKey(dateKey);
  const file = diagnosticFile(day);
  const maxLines = Math.max(1, Math.min(5000, Number(limit) || 500));
  const lines = readFileText(file)
    .split(/\r?\n/)
    .filter(Boolean)
    .slice(-maxLines);
  return {
    date: day,
    path: file.path,
    lines,
    text: lines.join("\n"),
  };
}

async function clearDiagnosticsApi(dateKey = "") {
  if (typeof Cc === "undefined" || typeof Ci === "undefined") {
    return {ok: true, date: "", path: ""};
  }

  migrateLegacyDiagnostics();
  const day = normalizeDiagnosticDateKey(dateKey);
  const file = diagnosticFile(day);
  const backup = diagnosticBackupFile(day);
  if (file.exists()) file.remove(false);
  if (backup.exists()) backup.remove(false);

  if (day === localDiagnosticDateKey()) {
    appendDiagnosticLog("diagnostics", "cleared", {date: day});
  }
  return {ok: true, date: day, path: file.path};
}

async function writeDiagnosticApi(component, event, details = {}) {
  const path = appendDiagnosticLog(component, event, details || {});
  return {ok: true, path};
}

function decodeBase64Binary(value) {
  const alphabet =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const clean = String(value || "").replace(/\s+/g, "").replace(/=+$/, "");
  let output = "";
  let bits = 0;
  let bitCount = 0;

  for (const char of clean) {
    const index = alphabet.indexOf(char);
    if (index < 0) throw new ExtensionError("Invalid base64 data");
    bits = (bits << 6) | index;
    bitCount += 6;
    if (bitCount >= 8) {
      bitCount -= 8;
      output += String.fromCharCode((bits >> bitCount) & 0xff);
    }
  }
  return output;
}

function shouldRetryHttpConservatively(url, error) {
  if (!/^https:\/\//i.test(String(url || ""))) return false;
  const text = String(error?.message || error || "");
  return /network status 2152398868|NS_ERROR_NET_RESET|network reset/i.test(text);
}

function applyConservativeHttpMode(channel) {
  const applied = {
    allowSpdy: null,
    allowAltSvc: null,
    beConservative: null,
    allowHttp3: null,
  };

  try {
    const internal = channel.QueryInterface(Ci.nsIHttpChannelInternal);
    if ("allowSpdy" in internal) {
      internal.allowSpdy = false;
      applied.allowSpdy = false;
    }
    if ("allowAltSvc" in internal) {
      internal.allowAltSvc = false;
      applied.allowAltSvc = false;
    }
    if ("beConservative" in internal) {
      internal.beConservative = true;
      applied.beConservative = true;
    }
    if ("allowHttp3" in internal) {
      internal.allowHttp3 = false;
      applied.allowHttp3 = false;
    }
  } catch (error) {
    applied.error = String(error?.message || error);
  }

  return applied;
}

async function httpRequestAttempt({url, method, headers, details, conservative = false}) {
  const channel = NetUtil.newChannel({
    uri: url,
    loadUsingSystemPrincipal: true,
  }).QueryInterface(Ci.nsIHttpChannel);

  const conservativeState = conservative
    ? applyConservativeHttpMode(channel)
    : null;

  if (method !== "GET" && method !== "HEAD" &&
      (details.bodyBase64 || details.bodyText !== undefined && details.bodyText !== null)) {
    const stream = Cc["@mozilla.org/io/string-input-stream;1"]
      .createInstance(Ci.nsIStringInputStream);
    if (details.bodyBase64) {
      const binary = decodeBase64Binary(details.bodyBase64);
      stream.setByteStringData(binary);
    } else {
      stream.setUTF8Data(String(details.bodyText));
    }
    const contentType = Object.entries(headers)
      .find(([name]) => name.toLowerCase() === "content-type")?.[1]
      || "application/octet-stream";
    channel.QueryInterface(Ci.nsIUploadChannel2)
      .explicitSetUploadStream(stream, String(contentType), -1, method, false);
  } else {
    channel.requestMethod = method;
  }

  for (const [name, value] of Object.entries(headers)) {
    if (name.toLowerCase() === "content-length") continue;
    channel.setRequestHeader(name, value, false);
  }

  const result = await new Promise((resolve, reject) => {
    NetUtil.asyncFetch(channel, (stream, status, request) => {
      if (!Components.isSuccessCode(status)) {
        reject(new Error("network status " + status));
        return;
      }
      const http = request.QueryInterface(Ci.nsIHttpChannel);
      const count = stream.available();
      const text = count
        ? NetUtil.readInputStreamToString(stream, count, {
            charset: "UTF-8",
            replacement: 0xfffd,
          })
        : "";
      resolve({
        ok: http.responseStatus >= 200 && http.responseStatus < 300,
        status: Number(http.responseStatus || 0),
        statusText: String(http.responseStatusText || ""),
        url: String(http.URI?.spec || url),
        text,
      });
    });
  });

  return {result, conservativeState};
}

async function httpRequestApi(details = {}) {
  const url = String(details.url || "").trim();
  if (!/^https?:\/\//i.test(url)) {
    throw new ExtensionError("HTTP request URL must use http:// or https://");
  }

  const method = String(details.method || "GET").toUpperCase();
  const headers = {};
  for (const [name, value] of Object.entries(details.headers || {})) {
    headers[String(name)] = String(value);
  }

  const started = Date.now();
  appendDiagnosticLog("http", "request.start", {
    url,
    method,
    mode: "normal",
    headers,
  });

  try {
    const first = await httpRequestAttempt({
      url,
      method,
      headers,
      details,
      conservative: false,
    });
    appendDiagnosticLog("http", "request.success", {
      url,
      method,
      mode: "normal",
      status: first.result.status,
      durationMs: Date.now() - started,
    });
    return first.result;
  } catch (firstError) {
    appendDiagnosticLog("http", "request.error", {
      url,
      method,
      mode: "normal",
      durationMs: Date.now() - started,
      error: firstError,
    });

    if (!shouldRetryHttpConservatively(url, firstError)) {
      throw new ExtensionError(
        "Privileged HTTP request failed: " + String(firstError?.message || firstError)
      );
    }

    const retryStarted = Date.now();
    appendDiagnosticLog("http", "request.retry-conservative", {
      url,
      method,
      reason: String(firstError?.message || firstError),
    });

    try {
      const retry = await httpRequestAttempt({
        url,
        method,
        headers,
        details,
        conservative: true,
      });
      appendDiagnosticLog("http", "request.success", {
        url,
        method,
        mode: "conservative",
        status: retry.result.status,
        durationMs: Date.now() - retryStarted,
        conservativeState: retry.conservativeState,
      });
      return retry.result;
    } catch (retryError) {
      appendDiagnosticLog("http", "request.error", {
        url,
        method,
        mode: "conservative",
        durationMs: Date.now() - retryStarted,
        error: retryError,
      });
      throw new ExtensionError(
        "Privileged HTTP request failed after conservative retry: " +
        String(retryError?.message || retryError)
      );
    }
  }
}

async function readPipeText(pipe) {
  if (!pipe || typeof pipe.readString !== "function") return "";
  let output = "";
  let chunk;
  while ((chunk = await pipe.readString())) output += chunk;
  return output;
}

function tempFileFromBase64(filename, base64) {
  const directoryService = Cc["@mozilla.org/file/directory_service;1"]
    .getService(Ci.nsIProperties);
  const file = directoryService.get("TmpD", Ci.nsIFile);
  const safe = String(filename || "caldav-assistant-upload.bin")
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .slice(0, 120) || "caldav-assistant-upload.bin";
  file.append(safe);
  file.createUnique(Ci.nsIFile.NORMAL_FILE_TYPE, 0o600);

  const binary = decodeBase64Binary(base64);
  const stream = Cc["@mozilla.org/network/file-output-stream;1"]
    .createInstance(Ci.nsIFileOutputStream);
  stream.init(file, 0x02 | 0x08 | 0x20, 0o600, 0);
  stream.write(binary, binary.length);
  stream.close();
  return file;
}

function createTempFile(filename) {
  const directoryService = Cc["@mozilla.org/file/directory_service;1"]
    .getService(Ci.nsIProperties);
  const file = directoryService.get("TmpD", Ci.nsIFile);
  const safe = String(filename || "caldav-assistant.tmp")
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .slice(0, 120) || "caldav-assistant.tmp";
  file.append(safe);
  file.createUnique(Ci.nsIFile.NORMAL_FILE_TYPE, 0o600);
  return file;
}

function writeTempText(filename, text) {
  const file = createTempFile(filename);
  const stream = Cc["@mozilla.org/network/file-output-stream;1"]
    .createInstance(Ci.nsIFileOutputStream);
  stream.init(file, 0x02 | 0x08 | 0x20, 0o600, 0);
  const converter = Cc["@mozilla.org/intl/converter-output-stream;1"]
    .createInstance(Ci.nsIConverterOutputStream);
  converter.init(stream, "UTF-8");
  converter.writeString(String(text || ""));
  converter.close();
  return file;
}

function curlQuote(value) {
  const text = String(value ?? "");
  if (/[\r\n]/.test(text)) {
    throw new ExtensionError("curl config values must not contain newlines");
  }
  return '"' + text.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
}

function isAllowedInsecureLocalHost(hostname) {
  const host = String(hostname || "").toLowerCase();
  if (host === "localhost" || host === "::1" || host.endsWith(".local")) return true;

  const parts = host.split(".");
  if (parts.length !== 4 || parts.some(part => !/^\d+$/.test(part))) return false;
  const nums = parts.map(Number);
  if (nums.some(value => value < 0 || value > 255)) return false;
  return (
    nums[0] === 10 ||
    nums[0] === 127 ||
    (nums[0] === 169 && nums[1] === 254) ||
    (nums[0] === 172 && nums[1] >= 16 && nums[1] <= 31) ||
    (nums[0] === 192 && nums[1] === 168)
  );
}

async function curlRequestApi(details = {}) {
  const url = String(details.url || "").trim();
  let parsed;
  try {
    // This code runs in Thunderbird's privileged Experiment parent scope.
    // Use Gecko's URI service instead of the Web-page WHATWG URL global:
    // the latter is not guaranteed to exist here and caused valid local URLs
    // such as https://andrew.local/... to be reported as invalid.
    parsed = Cc["@mozilla.org/network/io-service;1"]
      .getService(Ci.nsIIOService)
      .newURI(url);
  } catch (_error) {
    throw new ExtensionError("curl request URL is invalid");
  }
  if (parsed.scheme !== "https") {
    throw new ExtensionError("Insecure TLS mode only accepts https:// URLs");
  }
  if (!details.insecureTls) {
    throw new ExtensionError("curl REST bridge requires explicit insecureTls=true");
  }
  if (!isAllowedInsecureLocalHost(parsed.host)) {
    throw new ExtensionError(
      "Insecure TLS mode is restricted to .local, localhost, loopback, and private LAN IPv4 hosts"
    );
  }

  const method = String(details.method || "GET").toUpperCase();
  if (!/^(GET|POST|PUT|PATCH|DELETE|HEAD)$/.test(method)) {
    throw new ExtensionError("Unsupported curl HTTP method: " + method);
  }

  let requestBody = null;
  let responseFile = null;
  let configFile = null;
  const started = Date.now();

  try {
    if (details.bodyBase64) {
      requestBody = tempFileFromBase64("caldav-assistant-rest-body.bin", details.bodyBase64);
    } else if (details.bodyText !== undefined && details.bodyText !== null) {
      requestBody = writeTempText("caldav-assistant-rest-body.txt", details.bodyText);
    }
    responseFile = createTempFile("caldav-assistant-rest-response.txt");

    const configLines = [
      "silent",
      "show-error",
      "location",
      "max-redirs = 3",
      "connect-timeout = 10",
      "max-time = 60",
      "insecure",
      "request = " + curlQuote(method),
      "url = " + curlQuote(url),
      "output = " + curlQuote(responseFile.path),
      'write-out = "%{http_code}"',
    ];

    for (const [name, value] of Object.entries(details.headers || {})) {
      const headerName = String(name);
      const headerValue = String(value);
      if (/[\r\n]/.test(headerName) || /[\r\n]/.test(headerValue)) {
        throw new ExtensionError("HTTP headers must not contain newlines");
      }
      configLines.push("header = " + curlQuote(headerName + ": " + headerValue));
    }

    if (requestBody) {
      configLines.push("data-binary = " + curlQuote("@" + requestBody.path));
    }

    configFile = writeTempText(
      "caldav-assistant-curl.conf",
      configLines.join("\n") + "\n"
    );

    const command = await Subprocess.pathSearch("curl");
    appendDiagnosticLog("curl-http", "request.start", {
      url,
      method,
      insecureTls: true,
    });

    const proc = await Subprocess.call({
      command,
      arguments: ["--config", configFile.path],
      stdout: "pipe",
      stderr: "pipe",
    });
    proc.stdin.close();
    const [stdout, stderr, status] = await Promise.all([
      readPipeText(proc.stdout),
      readPipeText(proc.stderr),
      proc.wait(),
    ]);
    const exitCode = Number(status?.exitCode ?? -1);
    if (exitCode !== 0) {
      throw new Error(String(stderr || stdout || "curl failed").trim());
    }

    const httpStatus = Number(String(stdout || "").trim());
    const text = readFileText(responseFile);
    const result = {
      ok: httpStatus >= 200 && httpStatus < 300,
      status: httpStatus,
      statusText: "",
      url,
      text,
    };

    appendDiagnosticLog("curl-http", "request.success", {
      url,
      method,
      insecureTls: true,
      status: httpStatus,
      durationMs: Date.now() - started,
    });
    return result;
  } catch (error) {
    appendDiagnosticLog("curl-http", "request.error", {
      url,
      method,
      insecureTls: true,
      durationMs: Date.now() - started,
      error,
    });
    throw new ExtensionError(
      "Local insecure HTTPS REST request failed: " + String(error?.message || error)
    );
  } finally {
    for (const file of [requestBody, responseFile, configFile]) {
      if (file?.exists()) {
        try {
          file.remove(false);
        } catch (_error) {}
      }
    }
  }
}

async function runWpCliApi(details = {}) {
  const executable = String(details.executable || "wp").trim() || "wp";
  const wordpressPath = String(details.wordpressPath || "").trim();
  const prefixArgs = Array.isArray(details.prefixArgs)
    ? details.prefixArgs.map(value => String(value))
    : [];
  const rawArgs = Array.isArray(details.args)
    ? details.args.map(value => String(value))
    : [];

  if (prefixArgs.length + rawArgs.length > 200) {
    throw new ExtensionError("Too many WP-CLI arguments");
  }

  let tempFile = null;
  let args = [...prefixArgs, ...rawArgs];
  if (details.tempFileBase64) {
    tempFile = tempFileFromBase64(
      details.tempFileName || "caldav-assistant-upload.bin",
      details.tempFileBase64
    );
    args = args.map(value =>
      value === "__CALDAV_ASSISTANT_TEMP_FILE__" ? tempFile.path : value
    );
  }

  if (wordpressPath) {
    args = [`--path=${wordpressPath}`, ...args];
  }

  let command = executable;
  if (!/[\\/]/.test(command)) {
    command = await Subprocess.pathSearch(command);
  }

  const started = Date.now();
  appendDiagnosticLog("wp-cli", "run.start", {
    executable: command,
    wordpressPath,
    operation: args.slice(0, 3),
  });

  try {
    const proc = await Subprocess.call({
      command,
      arguments: args,
      stdout: "pipe",
      stderr: "pipe",
    });
    proc.stdin.close();

    const [stdout, stderr, status] = await Promise.all([
      readPipeText(proc.stdout),
      readPipeText(proc.stderr),
      proc.wait(),
    ]);

    const exitCode = Number(status?.exitCode ?? -1);
    appendDiagnosticLog("wp-cli", "run.success", {
      executable: command,
      wordpressPath,
      operation: args.slice(0, 3),
      exitCode,
      durationMs: Date.now() - started,
    });

    return {exitCode, stdout, stderr};
  } catch (error) {
    appendDiagnosticLog("wp-cli", "run.error", {
      executable: command,
      wordpressPath,
      operation: args.slice(0, 3),
      durationMs: Date.now() - started,
      error,
    });
    throw new ExtensionError(
      "WP-CLI process failed: " + String(error?.message || error)
    );
  } finally {
    if (tempFile?.exists()) {
      try {
        tempFile.remove(false);
      } catch (_error) {}
    }
  }
}

async function runWordPressHelperApi(details = {}) {
  const helperDir = String(details.helperDir || "").trim();
  const helperName = String(details.helperName || "").trim();
  const allowed = new Set(["find-today-post.sh", "create-post.sh"]);

  if (!allowed.has(helperName)) {
    throw new ExtensionError("Unsupported WordPress helper script");
  }
  if (!helperDir) {
    return {available: false, exitCode: null, stdout: "", stderr: ""};
  }

  const directory = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
  let resolvedDir = helperDir;
  if (/^~\//.test(resolvedDir)) {
    const home = Cc["@mozilla.org/file/directory_service;1"]
      .getService(Ci.nsIProperties)
      .get("Home", Ci.nsIFile)
      .path;
    resolvedDir = home + resolvedDir.slice(1);
  }
  directory.initWithPath(resolvedDir);
  const file = directory.clone();
  file.append(helperName);
  if (!file.exists() || !file.isFile()) {
    return {available: false, exitCode: null, stdout: "", stderr: ""};
  }

  const started = Date.now();
  appendDiagnosticLog("wp-helper", "run.start", {
    helper: file.path,
  });

  try {
    const proc = await Subprocess.call({
      command: file.path,
      arguments: [],
      stdout: "pipe",
      stderr: "pipe",
    });
    proc.stdin.close();
    const [stdout, stderr, status] = await Promise.all([
      readPipeText(proc.stdout),
      readPipeText(proc.stderr),
      proc.wait(),
    ]);
    const exitCode = Number(status?.exitCode ?? -1);
    appendDiagnosticLog("wp-helper", "run.success", {
      helper: file.path,
      exitCode,
      durationMs: Date.now() - started,
    });
    return {available: true, exitCode, stdout, stderr};
  } catch (error) {
    appendDiagnosticLog("wp-helper", "run.error", {
      helper: file.path,
      durationMs: Date.now() - started,
      error,
    });
    throw new ExtensionError(
      "WordPress helper failed: " + String(error?.message || error)
    );
  }
}

async function loggedMutation(action, details, callback) {
  const started = Date.now();
  appendDiagnosticLog("provider", action + ".start", details);
  try {
    const result = await callback();
    appendDiagnosticLog("provider", action + ".success", {
      ...details,
      durationMs: Date.now() - started,
    });
    return result;
  } catch (error) {
    appendDiagnosticLog("provider", action + ".error", {
      ...details,
      durationMs: Date.now() - started,
      error,
    });
    throw error;
  }
}

function calendarObserver(methods = {}) {
  return Object.assign(
    {
      QueryInterface: ChromeUtils.generateQI(["calIObserver"]),
      onStartBatch() {},
      onEndBatch() {},
      onLoad() {},
      onAddItem() {},
      onModifyItem() {},
      onDeleteItem() {},
      onError() {},
      onPropertyChanged() {},
      onPropertyDeleting() {},
    },
    methods
  );
}

function allCalendars() {
  return Array.from(cal.manager.getCalendars());
}

function calendarById(id) {
  const wanted = String(id || "");
  const calendar = allCalendars().find(candidate => String(candidate.id) === wanted);
  if (!calendar) {
    throw new ExtensionError(`Thunderbird calendar not found: ${wanted}`);
  }
  return calendar;
}

function calendarSupports(calendar, kind) {
  const property =
    kind === "task"
      ? "capabilities.tasks.supported"
      : "capabilities.events.supported";
  return calendar.getProperty(property) !== false;
}

function writableCalendarById(id, kind) {
  const calendar = calendarById(id);
  if (calendar.getProperty("disabled")) {
    throw new ExtensionError("Calendar is disabled");
  }
  if (calendar.readOnly) {
    throw new ExtensionError("Calendar is read-only");
  }
  if (!calendarSupports(calendar, kind)) {
    throw new ExtensionError(
      kind === "task"
        ? "Calendar does not support tasks"
        : "Calendar does not support events"
    );
  }
  return calendar;
}

function selectedCalendars(calendarId) {
  if (calendarId) {
    return [calendarById(calendarId)];
  }
  return allCalendars().filter(calendar => !calendar.getProperty("disabled"));
}

function mainMailWindow() {
  try {
    return Cc["@mozilla.org/appshell/window-mediator;1"]
      .getService(Ci.nsIWindowMediator)
      .getMostRecentWindow("mail:3pane");
  } catch (_error) {
    return null;
  }
}

function mainCompositeCalendar() {
  const window = mainMailWindow();
  if (!window || !cal.view?.getCompositeCalendar) return null;
  return cal.view.getCompositeCalendar(window);
}

function nativeVisibleCalendars() {
  const composite = mainCompositeCalendar();
  if (!composite) {
    return allCalendars().filter(calendar => !calendar.getProperty("disabled"));
  }
  return Array.from(composite.getCalendars() || []).filter(
    calendar => !calendar.getProperty("disabled")
  );
}

function nativeTaskTree() {
  const window = mainMailWindow();
  return window?.document?.getElementById?.("calendar-task-tree") || null;
}

function createNativeTaskFilter(filterName = "open", searchText = "") {
  const name = String(filterName || "open");
  if (!NATIVE_TASK_FILTERS.has(name)) {
    throw new ExtensionError("Unsupported Thunderbird Task filter: " + name);
  }

  // Thunderbird loads calendar-filter.js into the main mail window itself.
  // Instantiate that exact native calFilter class instead of reimplementing
  // its task-date/status/recurrence rules in the add-on. This works even when
  // the built-in Tasks tab/tree is not currently open.
  const window = mainMailWindow();
  const Filter = window?.calFilter;
  if (typeof Filter !== "function") {
    throw new ExtensionError(
      "Thunderbird native calFilter is unavailable in the main mail window"
    );
  }

  const filter = new Filter();
  filter.itemType = Ci.calICalendar.ITEM_FILTER_TYPE_TODO;
  filter.selectedDate = cal.dtz.now();
  filter.filterText = String(searchText || "");
  filter.applyFilter(name);
  return {filter, tree: nativeTaskTree()};
}

async function readNativeFilteredTasks(filter, calendar) {
  const items = [];
  const stream = cal.iterate.streamValues(filter.getItems(calendar));
  for await (const chunk of stream) {
    items.push(...chunk);
  }
  return items;
}

function calendarView(calendar, composite = null) {
  const displayed = composite
    ? Boolean(composite.getCalendarById(calendar.id))
    : !calendar.getProperty("disabled");
  return {
    id: String(calendar.id || ""),
    name: String(calendar.name || ""),
    type: String(calendar.type || ""),
    readOnly: Boolean(calendar.readOnly),
    disabled: Boolean(calendar.getProperty("disabled")),
    displayed,
    supportsTasks: calendarSupports(calendar, "task"),
    supportsEvents: calendarSupports(calendar, "event"),
  };
}

function categoriesOf(item) {
  try {
    return Array.from(item.getCategories() || [], value => String(value));
  } catch (_error) {
    return [];
  }
}

function dateView(value) {
  if (!value) return null;

  // Thunderbird providers may normalize server values to UTC. The workspace
  // edits HTML datetime-local values, so expose the wall-clock value in
  // Thunderbird's configured default timezone rather than treating UTC clock
  // fields as local time.
  let displayValue = value;
  if (!value.isDate && typeof value.getInTimezone === "function") {
    try {
      displayValue = value.getInTimezone(cal.dtz.defaultTimezone);
    } catch (error) {
      console.warn("[ThunderbirdCalDAV] timezone conversion failed", error);
    }
  }

  return {
    icalString: String(displayValue.icalString || ""),
    sourceIcalString: String(value.icalString || ""),
    isDate: Boolean(displayValue.isDate),
    timezone: String(displayValue.timezone?.tzid || ""),
  };
}

function taskView(item) {
  const status = String(
    item.getProperty("STATUS") || item.status || ""
  ).toUpperCase();
  return {
    id: String(item.id || ""),
    calendarId: String(
      item.calendar?.superCalendar?.id || item.calendar?.id || ""
    ),
    calendarName: String(
      item.calendar?.superCalendar?.name || item.calendar?.name || ""
    ),
    title: String(item.title || ""),
    status,
    completed: status === "COMPLETED" || Boolean(item.isCompleted),
    percentComplete: Number(item.percentComplete || 0),
    priority: Number(item.priority || 0),
    categories: categoriesOf(item),
    due: dateView(item.dueDate),
    start: dateView(item.entryDate),
    completedDate: dateView(item.completedDate),
    description: String(item.getProperty("DESCRIPTION") || ""),
    recurring: Boolean(item.recurrenceInfo || item.recurrenceId),
    recurrenceId: String(item.recurrenceId?.icalString || ""),
    instanceKey:
      String(item.calendar?.superCalendar?.id || item.calendar?.id || "") +
      "::" + String(item.id || "") +
      "::" + String(item.recurrenceId?.icalString || ""),
    paused:
      String(item.getProperty("X-CALDAV-ASSISTANT-PAUSED") || "").toUpperCase() ===
      "TRUE",
  };
}

function eventView(item) {
  return {
    id: String(item.id || ""),
    calendarId: String(
      item.calendar?.superCalendar?.id || item.calendar?.id || ""
    ),
    calendarName: String(
      item.calendar?.superCalendar?.name || item.calendar?.name || ""
    ),
    title: String(item.title || ""),
    start: dateView(item.startDate),
    end: dateView(item.endDate),
    status: String(item.getProperty("STATUS") || item.status || ""),
    categories: categoriesOf(item),
    description: String(item.getProperty("DESCRIPTION") || ""),
    recurring: Boolean(item.recurrenceInfo || item.recurrenceId),
    taskUid: String(item.getProperty("X-CALDAV-ASSISTANT-TASK-UID") || ""),
    workSession:
      String(item.getProperty("X-CALDAV-ASSISTANT-WORK-SESSION") || "").toUpperCase() ===
      "TRUE",
    workOpen:
      String(item.getProperty("X-CALDAV-ASSISTANT-WORK-OPEN") || "").toUpperCase() ===
      "TRUE",
  };
}

function fromInputDate(value) {
  if (value === null || value === undefined || value === "") return null;
  const text = String(value).trim();

  if (/^\d{8}$/.test(text) || /^\d{8}T\d{6}Z?$/.test(text)) {
    return cal.createDateTime(text);
  }

  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (dateOnly) {
    return cal.createDateTime(
      `${dateOnly[1]}${dateOnly[2]}${dateOnly[3]}`
    );
  }

  const local =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(
      text
    );
  if (local) {
    const dt = cal.createDateTime(
      `${local[1]}${local[2]}${local[3]}T${local[4]}${local[5]}${local[6] || "00"}`
    );
    dt.timezone = cal.dtz.defaultTimezone;
    return dt;
  }

  const parsed = new Date(text);
  if (!Number.isNaN(parsed.valueOf())) {
    return cal.dtz.jsDateToDateTime(parsed, cal.dtz.UTC);
  }

  throw new ExtensionError(`Unsupported date/time: ${text}`);
}

async function readItems(calendar, filter, start = null, end = null) {
  const started = Date.now();
  try {
    const items = await calendar.getItemsAsArray(filter, 0, start, end);
    const durationMs = Date.now() - started;
    if (durationMs >= 750) {
      appendDiagnosticLog("provider", "read.slow", {
        calendarId: String(calendar.id || ""),
        calendarName: String(calendar.name || ""),
        durationMs,
        count: Number(items?.length || 0),
      });
    }
    return items;
  } catch (error) {
    appendDiagnosticLog("provider", "read.error", {
      calendarId: String(calendar.id || ""),
      calendarName: String(calendar.name || ""),
      durationMs: Date.now() - started,
      error,
    });
    console.error("[ThunderbirdCalDAV] read failed", calendar.name, error);
    throw error;
  }
}

async function findItem(calendar, itemId, kind, recurrenceId = "") {
  const id = String(itemId || "");
  const direct = await calendar.getItem(id);
  if (!direct) {
    throw new ExtensionError(`Calendar item not found: ${id}`);
  }

  if (kind === "task" && !direct.isTodo?.()) {
    throw new ExtensionError(`Item is not a task: ${id}`);
  }
  if (kind === "event" && !direct.isEvent?.()) {
    throw new ExtensionError(`Item is not an event: ${id}`);
  }

  const recurrenceText = String(recurrenceId || "").trim();
  if (!recurrenceText) {
    return direct;
  }

  if (!direct.recurrenceInfo) {
    throw new ExtensionError(
      `Recurring occurrence requested for non-recurring item: ${id}`
    );
  }

  let recurrenceDate;
  try {
    recurrenceDate = cal.createDateTime(recurrenceText);
  } catch (_error) {
    throw new ExtensionError(
      `Invalid recurrence id for ${id}: ${recurrenceText}`
    );
  }
  const occurrence = direct.recurrenceInfo.getOccurrenceFor(recurrenceDate);
  if (!occurrence) {
    throw new ExtensionError(
      `Recurring occurrence not found: ${id} @ ${recurrenceText}`
    );
  }
  return occurrence;
}

function setDescription(item, value) {
  if (value === null || value === undefined || value === "") {
    item.deleteProperty("DESCRIPTION");
  } else {
    item.setProperty("DESCRIPTION", String(value));
  }
}

function setCategories(item, values) {
  const categories = Array.isArray(values)
    ? values.map(value => String(value).trim()).filter(Boolean)
    : String(values || "")
        .split(",")
        .map(value => value.trim())
        .filter(Boolean);
  item.setCategories([...new Set(categories)]);
}

function normalizePriority(value) {
  const priority = Number(value);
  if (!Number.isInteger(priority) || priority < 0 || priority > 9) {
    throw new ExtensionError("Priority must be an integer from 0 to 9");
  }
  return priority;
}

function normalizePercent(value) {
  const percent = Number(value);
  if (!Number.isFinite(percent) || percent < 0 || percent > 100) {
    throw new ExtensionError("Percent complete must be from 0 to 100");
  }
  return Math.round(percent);
}

function normalizeTaskStatus(value) {
  const status =
    value === null || value === undefined
      ? ""
      : String(value).trim().toUpperCase();
  if (!TASK_STATUSES.has(status)) {
    throw new ExtensionError(`Unsupported VTODO status: ${status}`);
  }
  return status;
}

function applyTaskChanges(item, changes) {
  if ("title" in changes) item.title = String(changes.title || "");
  if ("description" in changes) setDescription(item, changes.description);
  if ("priority" in changes) item.priority = normalizePriority(changes.priority);
  if ("categories" in changes) setCategories(item, changes.categories);
  if ("due" in changes) item.dueDate = fromInputDate(changes.due);
  if ("start" in changes) item.entryDate = fromInputDate(changes.start);
  if ("paused" in changes) {
    if (changes.paused) {
      item.setProperty("X-CALDAV-ASSISTANT-PAUSED", "TRUE");
    } else {
      item.deleteProperty("X-CALDAV-ASSISTANT-PAUSED");
    }
  }

  if ("status" in changes) {
    const status = normalizeTaskStatus(changes.status);
    const previousPercent = Number(item.percentComplete || 0);

    if (status === "COMPLETED") {
      // CalTodo.isCompleted=true owns the standard COMPLETED trio:
      // STATUS=COMPLETED, PERCENT-COMPLETE=100 and COMPLETED timestamp.
      item.isCompleted = true;
    } else {
      // Important Thunderbird CalTodo semantic: isCompleted=false clears
      // STATUS, PERCENT-COMPLETE and COMPLETED. Clear first, then restore the
      // requested non-completed state.
      item.isCompleted = false;
      if (status) {
        item.status = status;
      }
      if (status === "IN-PROCESS" || status === "CANCELLED") {
        if (
          !("percentComplete" in changes) &&
          previousPercent > 0 &&
          previousPercent < 100
        ) {
          item.percentComplete = previousPercent;
        }
      }
    }
  }

  if ("percentComplete" in changes) {
    const value = normalizePercent(changes.percentComplete);
    // Match Thunderbird's native task progress semantics.
    item.percentComplete = value;
    switch (value) {
      case 0:
        item.isCompleted = false;
        if ("status" in changes) {
          const status = normalizeTaskStatus(changes.status);
          if (status && status !== "COMPLETED") item.status = status;
        }
        break;
      case 100:
        item.isCompleted = true;
        break;
      default: {
        const explicitStatus = "status" in changes
          ? normalizeTaskStatus(changes.status)
          : "";
        item.status =
          explicitStatus && explicitStatus !== "COMPLETED"
            ? explicitStatus
            : "IN-PROCESS";
        item.completedDate = null;
        break;
      }
    }
  }
}

function applyEventChanges(item, changes) {
  if ("title" in changes) item.title = String(changes.title || "");
  if ("description" in changes) setDescription(item, changes.description);
  if ("categories" in changes) setCategories(item, changes.categories);
  if ("start" in changes) item.startDate = fromInputDate(changes.start);
  if ("end" in changes) item.endDate = fromInputDate(changes.end);
  if ("status" in changes) {
    const status = String(changes.status || "").trim().toUpperCase();
    if (status) item.status = status;
    else item.deleteProperty("STATUS");
  }
  if ("taskUid" in changes) {
    if (changes.taskUid) {
      item.setProperty("X-CALDAV-ASSISTANT-TASK-UID", String(changes.taskUid));
    } else {
      item.deleteProperty("X-CALDAV-ASSISTANT-TASK-UID");
    }
  }
  if ("workSession" in changes) {
    if (changes.workSession) {
      item.setProperty("X-CALDAV-ASSISTANT-WORK-SESSION", "TRUE");
    } else {
      item.deleteProperty("X-CALDAV-ASSISTANT-WORK-SESSION");
    }
  }
  if ("workOpen" in changes) {
    if (changes.workOpen) {
      item.setProperty("X-CALDAV-ASSISTANT-WORK-OPEN", "TRUE");
    } else {
      item.deleteProperty("X-CALDAV-ASSISTANT-WORK-OPEN");
    }
  }
}

function validateEvent(item) {
  if (!item.startDate) {
    throw new ExtensionError("Event start is required");
  }
  // DTEND is intentionally optional. CalDAV Assistant keeps the current work
  // session open until Pause/Complete/Cancel closes it.
  if (item.endDate && item.endDate.compare(item.startDate) < 0) {
    throw new ExtensionError("Event end must not be before its start");
  }
}

async function modifyItem(calendar, oldItem, mutator) {
  if (oldItem.recurrenceId && oldItem.parentItem?.recurrenceInfo) {
    const oldParent = oldItem.parentItem;
    const newParent = oldParent.clone();
    const recurrenceInfo = newParent.recurrenceInfo;
    const occurrence = recurrenceInfo.getOccurrenceFor(oldItem.recurrenceId);
    if (!occurrence) {
      throw new ExtensionError("Recurring occurrence was not found");
    }
    mutator(occurrence);
    recurrenceInfo.modifyException(occurrence, true);
    const storedParent = await calendar.modifyItem(newParent, oldParent);
    const storedOccurrence =
      storedParent?.recurrenceInfo?.getOccurrenceFor?.(oldItem.recurrenceId);
    return storedOccurrence || occurrence;
  }

  const changed = oldItem.clone();
  mutator(changed);
  return (await calendar.modifyItem(changed, oldItem)) || changed;
}

async function listCalendarsApi() {
  const composite = mainCompositeCalendar();
  return allCalendars().map(calendar => calendarView(calendar, composite));
}

async function setCalendarDisplayedApi(calendarId, displayed) {
  const composite = mainCompositeCalendar();
  if (!composite) {
    throw new ExtensionError("Thunderbird native Calendar selector is unavailable");
  }
  const calendar = calendarById(calendarId);
  const isDisplayed = Boolean(composite.getCalendarById(calendar.id));
  if (Boolean(displayed) && !isDisplayed) {
    composite.addCalendar(calendar);
  } else if (!displayed && isDisplayed) {
    composite.removeCalendar(calendar);
  }
  return calendarView(calendar, composite);
}

async function listNativeTasksApi(options = {}) {
  const {filter, tree} = createNativeTaskFilter(
    options?.filter || "open",
    options?.searchText || ""
  );
  const batches = await Promise.all(
    nativeVisibleCalendars()
      .filter(calendar => calendarSupports(calendar, "task"))
      .map(async calendar =>
        (await readNativeFilteredTasks(filter, calendar))
          .filter(item => item?.isTodo?.())
      )
  );
  const items = batches.flat();

  // Reuse the native tree's active sort column/direction when available.
  const column = tree?.mTreeView?.selectedColumn;
  if (column && cal.unifinder?.sortItems) {
    const key = column.getAttribute("sortKey") || column.getAttribute("itemproperty");
    const modifier = tree?.mTreeView?.sortDirection === "descending" ? -1 : 1;
    cal.unifinder.sortItems(items, key, modifier);
  }
  return items.map(taskView);
}

async function listTasksApi(calendarId = "") {
  const filter =
    Ci.calICalendar.ITEM_FILTER_TYPE_TODO |
    Ci.calICalendar.ITEM_FILTER_COMPLETED_ALL;
  const batches = await Promise.all(
    selectedCalendars(calendarId)
      .filter(calendar => calendarSupports(calendar, "task"))
      .map(async calendar =>
        (await readItems(calendar, filter))
          .filter(item => item?.isTodo?.())
          .map(taskView)
      )
  );
  return batches.flat();
}

async function listEventsApi(calendarId = "", start = "", end = "") {
  const filter = Ci.calICalendar.ITEM_FILTER_TYPE_EVENT;
  const startDate = fromInputDate(start);
  const endDate = fromInputDate(end);
  const batches = await Promise.all(
    selectedCalendars(calendarId)
      .filter(calendar => calendarSupports(calendar, "event"))
      .map(async calendar =>
        (await readItems(calendar, filter, startDate, endDate))
          .filter(item => item?.isEvent?.())
          .map(eventView)
      )
  );
  return batches.flat();
}

async function getTaskApi(calendarId, itemId, recurrenceId = "") {
  const calendar = calendarById(calendarId);
  const item = await findItem(calendar, itemId, "task", recurrenceId);
  return taskView(item);
}

async function getEventApi(calendarId, itemId) {
  const calendar = calendarById(calendarId);
  const item = await findItem(calendar, itemId, "event");
  return eventView(item);
}

async function createTaskApi(calendarId, values) {
  return loggedMutation("task.create", {calendarId: String(calendarId || "")}, async () => {
    const calendar = writableCalendarById(calendarId, "task");
    const task = new CalTodo();
    task.id = cal.getUUID();
    task.calendar = calendar;
    applyTaskChanges(task, values || {});
    const added = await calendar.addItem(task);
    return taskView(added || task);
  });
}

async function updateTaskApi(calendarId, itemId, changes, recurrenceId = "") {
  return loggedMutation(
    "task.update",
    {
      calendarId: String(calendarId || ""),
      itemId: String(itemId || ""),
      recurrenceId: String(recurrenceId || ""),
    },
    async () => {
      const calendar = writableCalendarById(calendarId, "task");
      const oldItem = await findItem(calendar, itemId, "task", recurrenceId);
      const changed = await modifyItem(calendar, oldItem, item =>
        applyTaskChanges(item, changes || {})
      );
      return taskView(changed);
    }
  );
}

async function deleteTaskApi(calendarId, itemId) {
  return loggedMutation(
    "task.delete",
    {calendarId: String(calendarId || ""), itemId: String(itemId || "")},
    async () => {
      const calendar = writableCalendarById(calendarId, "task");
      const item = await findItem(calendar, itemId, "task");
      await calendar.deleteItem(item);
      return {ok: true, id: String(itemId)};
    }
  );
}

async function createEventApi(calendarId, values) {
  return loggedMutation("event.create", {calendarId: String(calendarId || "")}, async () => {
    const calendar = writableCalendarById(calendarId, "event");
    const event = new CalEvent();
    event.id = values?.id ? String(values.id) : cal.getUUID();
    event.calendar = calendar;
    applyEventChanges(event, values || {});
    validateEvent(event);
    const added = await calendar.addItem(event);
    return eventView(added || event);
  });
}

async function updateEventApi(calendarId, itemId, changes) {
  return loggedMutation(
    "event.update",
    {calendarId: String(calendarId || ""), itemId: String(itemId || "")},
    async () => {
      const calendar = writableCalendarById(calendarId, "event");
      const oldItem = await findItem(calendar, itemId, "event");
      const changed = await modifyItem(calendar, oldItem, item => {
        applyEventChanges(item, changes || {});
        validateEvent(item);
      });
      return eventView(changed);
    }
  );
}

async function deleteEventApi(calendarId, itemId) {
  return loggedMutation(
    "event.delete",
    {calendarId: String(calendarId || ""), itemId: String(itemId || "")},
    async () => {
      const calendar = writableCalendarById(calendarId, "event");
      const item = await findItem(calendar, itemId, "event");
      await calendar.deleteItem(item);
      return {ok: true, id: String(itemId)};
    }
  );
}

this.ThunderbirdCalDAV = class extends ExtensionAPI {
  getAPI(context) {
    return {
      ThunderbirdCalDAV: {
        listCalendars: listCalendarsApi,
        setCalendarDisplayed: setCalendarDisplayedApi,
        listNativeTasks: listNativeTasksApi,
        listTasks: listTasksApi,
        listEvents: listEventsApi,
        getTask: getTaskApi,
        getEvent: getEventApi,
        createTask: createTaskApi,
        updateTask: updateTaskApi,
        deleteTask: deleteTaskApi,
        createEvent: createEventApi,
        updateEvent: updateEventApi,
        deleteEvent: deleteEventApi,
        listDiagnosticsDates: listDiagnosticsDatesApi,
        diagnosticsInfo: diagnosticsInfoApi,
        readDiagnostics: readDiagnosticsApi,
        clearDiagnostics: clearDiagnosticsApi,
        writeDiagnostic: writeDiagnosticApi,
        httpRequest: httpRequestApi,
        curlRequest: curlRequestApi,
        runWpCli: runWpCliApi,
        runWordPressHelper: runWordPressHelperApi,

        onItemsChanged: new EventManager({
          context,
          name: "ThunderbirdCalDAV.onItemsChanged",
          register: fire => {
            const observer = calendarObserver({
              onLoad() {
                fire.async();
              },
              onAddItem() {
                fire.async();
              },
              onModifyItem() {
                fire.async();
              },
              onDeleteItem() {
                fire.async();
              },
            });
            cal.manager.addCalendarObserver(observer);
            return () => cal.manager.removeCalendarObserver(observer);
          },
        }).api(),
      },
    };
  }
};
