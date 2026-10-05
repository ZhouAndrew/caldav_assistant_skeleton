"use strict";

(() => {
  let autoWpCliFallback = false;

  function errorText(error) {
    return String(error?.message || error || "Unknown error");
  }

  function trimSlash(value) {
    return String(value || "").trim().replace(/\/+$/, "");
  }

  function normalizeConfig(config) {
    const requested = String(config?.transport || "auto").trim().toLowerCase();
    const transport = ["auto", "application-password", "wp-cli"].includes(requested)
      ? requested
      : "auto";
    const hasExistingWordPressConfig = Boolean(
      config && (
        config.baseUrl ||
        config.username ||
        config.applicationPassword ||
        config.wordpressPath ||
        config.wpCliCommand ||
        config.wpCliExecutable ||
        config.transport
      )
    );
    return {
      transport,
      baseUrl: trimSlash(config?.baseUrl),
      username: String(config?.username || "").trim(),
      applicationPassword: String(config?.applicationPassword || "").replace(/\s+/g, ""),
      wordpressPath: String(config?.wordpressPath || "/var/www/html/wordpress").trim(),
      wpCliCommand: String(
        config?.wpCliCommand || config?.wpCliExecutable || "wp"
      ).trim() || "wp",
      legacyHelperDir: String(config?.legacyHelperDir || "~/bin").trim(),
      allowUntrustedTls: Boolean(config?.allowUntrustedTls),
      authorizedTlsOrigin: String(config?.authorizedTlsOrigin || ""),
      dailyWorkLogEnabled:
        typeof config?.dailyWorkLogEnabled === "boolean"
          ? config.dailyWorkLogEnabled
          : hasExistingWordPressConfig,
    };
  }

  function selectedTransport(config) {
    if (config.transport === "application-password" || config.transport === "wp-cli") {
      return config.transport;
    }
    return config.baseUrl && config.username && config.applicationPassword
      ? "application-password"
      : "wp-cli";
  }

  function effectiveTransport(config) {
    if (config.transport === "auto" && autoWpCliFallback) return "wp-cli";
    return selectedTransport(config);
  }

  function isRestNetworkFailure(error) {
    const text = errorText(error);
    if (/^WordPress HTTP \d+:/i.test(text)) return false;
    return /Privileged HTTP request failed|network status|NS_ERROR_|NetworkError|Failed to fetch/i.test(text);
  }

  function canAutoFallbackToWpCli(config, error) {
    return (
      config.transport === "auto" &&
      selectedTransport(config) === "application-password" &&
      Boolean(config.wordpressPath) &&
      isRestNetworkFailure(error)
    );
  }

  async function recordTransportFallback(error) {
    try {
      await browser.ThunderbirdCalDAV?.writeDiagnostic?.(
        "wordpress",
        "transport.fallback",
        {
          from: "application-password",
          to: "wp-cli",
          reason: errorText(error),
        }
      );
    } catch (_error) {}
  }

  async function getConfig() {
    const settings = await AssistantStorage.getSettings();
    return normalizeConfig(settings.wordpress || {});
  }

  async function saveConfig(config) {
    const normalized = normalizeConfig(config);
    autoWpCliFallback = false;
    if (normalized.allowUntrustedTls) {
      normalized.authorizedTlsOrigin = assertLocalInsecureTlsUrl(normalized.baseUrl).origin;
    } else normalized.authorizedTlsOrigin = "";
    await AssistantStorage.saveSettings({wordpress: normalized});
    return normalized;
  }

  function permissionOrigin(baseUrl) {
    const normalized = trimSlash(baseUrl);
    if (!normalized) throw new Error("WordPress URL is not configured.");
    let parsed;
    try {
      parsed = new URL(normalized);
    } catch (_error) {
      throw new Error("WordPress URL is invalid.");
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      throw new Error("WordPress URL must use http:// or https://.");
    }
    return parsed.origin + "/*";
  }

  function isPrivateIpv4(hostname) {
    const parts = String(hostname || "").split(".");
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

  function assertLocalInsecureTlsUrl(baseUrl) {
    let parsed;
    try {
      parsed = new URL(trimSlash(baseUrl));
    } catch (_error) {
      throw new Error("WordPress URL is invalid.");
    }
    if (parsed.protocol !== "https:") {
      throw new Error("忽略证书校验仅适用于本地 HTTPS URL。");
    }
    const host = String(parsed.hostname || "").toLowerCase();
    const local =
      host === "localhost" ||
      host === "::1" ||
      host.endsWith(".local") ||
      isPrivateIpv4(host);
    if (!local) {
      throw new Error("为安全起见，忽略 HTTPS 证书校验只允许 .local、localhost、回环地址或私有局域网 IP。");
    }
    return parsed;
  }

  function basicAuth(username, password) {
    const bytes = new TextEncoder().encode(`${username}:${password}`);
    let binary = "";
    for (const value of bytes) binary += String.fromCharCode(value);
    return "Basic " + btoa(binary);
  }

  function bytesToBase64(bytes) {
    let binary = "";
    const chunk = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunk) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk));
    }
    return btoa(binary);
  }

  async function restRequest(config, path, options = {}) {
    if (!config.baseUrl || !config.username || !config.applicationPassword) {
      throw new Error("WordPress Application Password connection is not configured.");
    }

    permissionOrigin(config.baseUrl);
    const url = config.baseUrl + "/wp-json/wp/v2" + path;
    const headers = {...(options.headers || {})};
    headers.Authorization = basicAuth(config.username, config.applicationPassword);

    let bodyText = null;
    let bodyBase64 = null;
    if (options.json !== undefined) {
      headers["Content-Type"] = "application/json";
      bodyText = JSON.stringify(options.json);
    } else if (options.body instanceof Blob) {
      const bytes = new Uint8Array(await options.body.arrayBuffer());
      bodyBase64 = bytesToBase64(bytes);
    } else if (options.body !== undefined && options.body !== null) {
      bodyText = String(options.body);
    }

    const useUntrustedLocalTls = Boolean(config.allowUntrustedTls);
    if (useUntrustedLocalTls) {
      const origin = assertLocalInsecureTlsUrl(config.baseUrl).origin;
      if (config.authorizedTlsOrigin !== origin) throw new Error("请为当前 HTTPS 地址重新保存 TLS 授权。");
    }

    const bridge = useUntrustedLocalTls
      ? browser.ThunderbirdCalDAV?.curlRequest
      : browser.ThunderbirdCalDAV?.httpRequest;
    if (typeof bridge !== "function") {
      throw new Error(
        useUntrustedLocalTls
          ? "Local insecure HTTPS REST bridge is unavailable."
          : "Thunderbird privileged HTTP bridge is unavailable."
      );
    }

    const response = await bridge({
      url,
      method: options.method || "GET",
      headers,
      bodyText,
      bodyBase64,
      insecureTls: useUntrustedLocalTls,
    });

    const text = String(response?.text || "");
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (_error) {
        data = text;
      }
    }
    if (!response?.ok) {
      const error = new Error(`WordPress HTTP ${response?.status || 0}: ${typeof data === "string" ? data : data?.message || response?.statusText || "request failed"}`);
      error.code = data?.code || "HTTP_FAILURE";
      throw error;
    }
    return data;
  }

  function splitCommandLine(value) {
    const text = String(value || "").trim();
    if (!text) return ["wp"];

    const parts = [];
    let current = "";
    let quote = "";
    let escaped = false;

    for (const char of text) {
      if (escaped) {
        current += char;
        escaped = false;
        continue;
      }
      if (char === "\\") {
        escaped = true;
        continue;
      }
      if (quote) {
        if (char === quote) quote = "";
        else current += char;
        continue;
      }
      if (char === "'" || char === '"') {
        quote = char;
        continue;
      }
      if (/\s/.test(char)) {
        if (current) {
          parts.push(current);
          current = "";
        }
        continue;
      }
      current += char;
    }

    if (escaped || quote) {
      throw new Error("WP-CLI command has an unfinished escape or quote.");
    }
    if (current) parts.push(current);
    if (!parts.length) throw new Error("WP-CLI command is empty.");
    return parts;
  }

  async function wpCliRun(config, args, {blob = null, filename = ""} = {}) {
    const bridge = browser.ThunderbirdCalDAV?.runWpCli;
    if (typeof bridge !== "function") {
      throw new Error("Thunderbird WP-CLI bridge is unavailable.");
    }

    let tempFileBase64 = null;
    if (blob instanceof Blob) {
      const bytes = new Uint8Array(await blob.arrayBuffer());
      tempFileBase64 = bytesToBase64(bytes);
    }

    const command = splitCommandLine(config.wpCliCommand);
    const result = await bridge({
      executable: command[0],
      prefixArgs: command.slice(1),
      wordpressPath: config.wordpressPath,
      args,
      tempFileName: filename,
      tempFileBase64,
    });
    if (Number(result?.exitCode ?? -1) !== 0) {
      throw new Error(
        "WP-CLI failed: " +
        String(result?.stderr || result?.stdout || "unknown WP-CLI error").trim()
      );
    }
    return String(result?.stdout || "").trim();
  }


  async function runLegacyHelper(config, helperName) {
    const bridge = browser.ThunderbirdCalDAV?.runWordPressHelper;
    if (typeof bridge !== "function" || !config.legacyHelperDir) {
      return {available: false, exitCode: null, stdout: "", stderr: ""};
    }
    return bridge({
      helperDir: config.legacyHelperDir,
      helperName,
    });
  }

  function helperPostId(text, {strictLine = false} = {}) {
    const source = String(text || "");
    if (strictLine) {
      const line = source.split(/\r?\n/).map(x => x.trim()).find(x => /^\d+$/.test(x));
      return line ? Number(line) : 0;
    }
    const matches = [...source.matchAll(/(?:^|\D)(\d+)(?=\D|$)/g)];
    return matches.length ? Number(matches[matches.length - 1][1]) : 0;
  }

  function wpCliPostView(record) {
    const id = Number(record?.ID ?? record?.id ?? 0);
    const title = String(record?.post_title ?? record?.title ?? "");
    const content = String(record?.post_content ?? record?.content ?? "");
    const status = String(record?.post_status ?? record?.status ?? "");
    const guid = String(record?.guid ?? record?.source_url ?? "");
    const parent = Number(record?.post_parent ?? record?.post ?? 0);
    const mime = String(record?.post_mime_type ?? record?.mime_type ?? "");
    return {
      id,
      title: {raw: title, rendered: title},
      content: {raw: content, rendered: content},
      status,
      link: guid,
      source_url: guid,
      post: parent,
      mime_type: mime,
    };
  }

  async function wpCliGetPost(config, id) {
    const stdout = await wpCliRun(config, [
      "post", "get", String(id),
      "--fields=ID,post_title,post_content,post_status,guid,post_parent,post_mime_type",
      "--format=json",
    ]);
    return wpCliPostView(JSON.parse(stdout || "{}"));
  }

  function wpCliFieldArgs(values = {}) {
    const map = {
      title: "post_title",
      content: "post_content",
      status: "post_status",
      type: "post_type",
      post: "post_parent",
    };
    const args = [];
    for (const [key, value] of Object.entries(values || {})) {
      const field = map[key] || key;
      args.push(`--${field}=${value ?? ""}`);
    }
    return args;
  }

  function headerValue(headers, wanted) {
    const target = String(wanted).toLowerCase();
    for (const [key, value] of Object.entries(headers || {})) {
      if (String(key).toLowerCase() === target) return String(value);
    }
    return "";
  }

  async function wpCliRequest(config, path, options = {}) {
    if (!config.wordpressPath) {
      throw new Error("WordPress path is not configured for WP-CLI.");
    }

    const parsed = new URL(path, "http://wp-cli.local");
    const route = parsed.pathname;
    const method = String(options.method || "GET").toUpperCase();

    if (route === "/users/me" && method === "GET") {
      await wpCliRun(config, ["core", "is-installed"]);
      let name = "WP-CLI";
      try {
        const blog = await wpCliRun(config, ["option", "get", "blogname"]);
        if (blog) name += " · " + blog;
      } catch (_error) {}
      return {id: 0, name, slug: "wp-cli"};
    }

    if (route === "/posts" && method === "GET") {
      const args = [
        "post", "list",
        "--post_type=post",
        "--post_status=any",
        "--fields=ID,post_title,post_status,guid",
        "--format=json",
      ];
      const search = parsed.searchParams.get("search");
      if (search) args.push("--search=" + search);
      const stdout = await wpCliRun(config, args);
      const rows = JSON.parse(stdout || "[]");
      return (Array.isArray(rows) ? rows : []).map(wpCliPostView);
    }

    if (route === "/posts" && method === "POST") {
      const values = options.json || {};
      const stdout = await wpCliRun(config, [
        "post", "create",
        ...wpCliFieldArgs(values),
        "--porcelain",
      ]);
      const id = Number(stdout.split(/\s+/).filter(Boolean).pop());
      if (!id) throw new Error("WP-CLI returned no post id.");
      return wpCliGetPost(config, id);
    }

    let match = /^\/posts\/(\d+)$/.exec(route);
    if (match) {
      const id = Number(match[1]);
      if (method === "GET") return wpCliGetPost(config, id);
      if (method === "POST") {
        await wpCliRun(config, [
          "post", "update", String(id),
          ...wpCliFieldArgs(options.json || {}),
          "--quiet",
        ]);
        return wpCliGetPost(config, id);
      }
      if (method === "DELETE") {
        const previous = await wpCliGetPost(config, id);
        await wpCliRun(config, ["post", "delete", String(id), "--force"]);
        return {deleted: true, previous};
      }
    }

    if (route === "/media" && method === "POST") {
      const disposition = headerValue(options.headers, "Content-Disposition");
      const filenameMatch = /filename="?([^";]+)"?/i.exec(disposition);
      const filename = filenameMatch?.[1] || "caldav-assistant-upload.bin";
      const stdout = await wpCliRun(
        config,
        ["media", "import", "__CALDAV_ASSISTANT_TEMP_FILE__", "--porcelain"],
        {blob: options.body, filename}
      );
      const id = Number(stdout.split(/\s+/).filter(Boolean).pop());
      if (!id) throw new Error("WP-CLI returned no media id.");
      return wpCliGetPost(config, id);
    }

    match = /^\/media\/(\d+)$/.exec(route);
    if (match) {
      const id = Number(match[1]);
      if (method === "GET") return wpCliGetPost(config, id);
      if (method === "POST") {
        const parent = Number(options.json?.post || 0);
        await wpCliRun(config, [
          "post", "update", String(id),
          "--post_parent=" + parent,
          "--quiet",
        ]);
        return wpCliGetPost(config, id);
      }
      if (method === "DELETE") {
        const previous = await wpCliGetPost(config, id);
        await wpCliRun(config, ["post", "delete", String(id), "--force"]);
        return {deleted: true, previous};
      }
    }

    throw new Error(`Unsupported WP-CLI WordPress request: ${method} ${route}`);
  }

  async function request(path, options = {}, override = null) {
    const config = override || await getConfig();
    if (effectiveTransport(config) === "wp-cli") {
      return wpCliRequest(config, path, options);
    }

    try {
      return await restRequest(config, path, options);
    } catch (error) {
      if (!canAutoFallbackToWpCli(config, error)) throw error;

      try {
        const result = await wpCliRequest(config, path, options);
        autoWpCliFallback = true;
        await recordTransportFallback(error);
        return result;
      } catch (fallbackError) {
        throw new Error(
          "WordPress REST failed (" + errorText(error) +
          "); WP-CLI fallback failed (" + errorText(fallbackError) + ")"
        );
      }
    }
  }

  async function validateTransportConfig() {
    const config = await getConfig();
    const transport = selectedTransport(config);
    if (transport === "application-password") {
      if (!config.baseUrl || !config.username || !config.applicationPassword) {
        throw new Error("WordPress Application Password connection is not configured.");
      }
      permissionOrigin(config.baseUrl);
    } else if (!config.wordpressPath) {
      throw new Error("WordPress path is not configured for WP-CLI.");
    }
    return true;
  }

  async function diagnosticTraceSince(startedAt) {
    try {
      if (typeof browser.ThunderbirdCalDAV?.readDiagnostics !== "function") return [];
      const data = await browser.ThunderbirdCalDAV.readDiagnostics(5000);
      const floor = new Date(startedAt).getTime() - 100;
      const allowed = new Set(["http", "curl-http", "wp-cli", "wordpress", "wp-helper"]);
      return (data?.lines || [])
        .map(line => {
          try {
            return JSON.parse(line);
          } catch (_error) {
            return null;
          }
        })
        .filter(Boolean)
        .filter(item => allowed.has(item.component))
        .filter(item => new Date(item.ts).getTime() >= floor)
        .map(item => ({
          timestamp: item.ts,
          component: item.component,
          event: item.event,
          success: !/error/i.test(String(item.event || "")),
          details: item.details || {},
        }));
    } catch (_error) {
      return [];
    }
  }

  async function quickTest() {
    const result = {
      action: "connection.wordpress-quick",
      success: false,
      startedAt: new Date().toISOString(),
      steps: [],
      summary: "",
    };
    try {
      await validateTransportConfig();
      const started = performance.now();
      const user = await request("/users/me?context=edit");
      result.steps.push({
        name: "authenticate + read users/me",
        success: true,
        latencyMs: Math.round(performance.now() - started),
        userId: user?.id,
        userName: user?.name,
      });
      result.success = true;
      const config = await getConfig();
      const transport = effectiveTransport(config);
      result.transport = transport;
      result.tlsVerification =
        transport === "application-password" && config.allowUntrustedTls
          ? "disabled-local"
          : "enabled";
      result.summary = transport === "wp-cli"
        ? `WordPress WP-CLI connected: ${user?.name || "WP-CLI"}.`
        : config.allowUntrustedTls
          ? `WordPress REST connected with certificate verification disabled for local HTTPS: ${user?.name || user?.slug || "user"}.`
          : `WordPress authenticated as ${user?.name || user?.slug || "user"}.`;
    } catch (error) {
      result.summary = `WordPress quick test failed: ${errorText(error)}`;
      result.steps.push({name: "WordPress read", success: false, error: errorText(error)});
    }
    result.trace = await diagnosticTraceSince(result.startedAt);
    result.completedAt = new Date().toISOString();
    return AssistantStorage.persistResult(result, "connection");
  }

  function pngBlob() {
    const base64 =
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII=";
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], {type: "image/png"});
  }

  async function uploadMedia(blob, filename, parent = 0, override = null) {
    const media = await request("/media", {
      method: "POST",
      headers: {
        "Content-Disposition": `attachment; filename="${filename}"`,
        "Content-Type": blob.type || "application/octet-stream",
      },
      body: blob,
    }, override);
    if (parent && media?.id) {
      return request(`/media/${media.id}`, {
        method: "POST",
        json: {post: parent},
      }, override);
    }
    return media;
  }

  async function fullWriteTest(override = null) {
    const testRequest = (path, options = {}) => request(path, options, override);
    const result = {
      action: "connection.wordpress-full-write",
      success: false,
      startedAt: new Date().toISOString(),
      steps: [],
      summary: "",
      postId: null,
      mediaId: null,
    };
    let postId = null;
    let mediaId = null;
    try {
      await validateTransportConfig();
      const marker = `CALDAV-ASSISTANT-TEST-${Date.now()}`;
      const post = await testRequest("/posts", {
        method: "POST",
        json: {
          title: marker,
          content: "Temporary CalDAV Assistant connector test.",
          status: "draft",
        },
      });
      postId = post.id;
      result.postId = postId;
      result.steps.push({name: "create TEST draft post", success: true, postId});

      const read = await testRequest(`/posts/${postId}?context=edit`);
      if (read?.id !== postId || rawTitle(read) !== marker || rawContent(read) !== "Temporary CalDAV Assistant connector test." || read.status !== "draft") throw new Error("WordPress post read-back failed.");
      result.steps.push({name: "read TEST post", success: true, postId});

      const updated = await testRequest(`/posts/${postId}`, {
        method: "POST",
        json: {content: "Temporary CalDAV Assistant connector test. UPDATED."},
      });
      if (updated?.id !== postId) throw new Error("WordPress post update failed.");
      const reread = await testRequest(`/posts/${postId}?context=edit`);
      const contentRead = reread?.content?.raw || reread?.content?.rendered || "";
      if (contentRead !== "Temporary CalDAV Assistant connector test. UPDATED." || reread.id !== postId || rawTitle(reread) !== marker || reread.status !== "draft") {
        throw new Error("WordPress post update read-back mismatch.");
      }
      result.steps.push({name: "update + read-back TEST post", success: true, postId});

      const media = await uploadMedia(
        pngBlob(),
        "caldav-assistant-connector-test.png",
        postId,
        override
      );
      mediaId = media.id;
      result.mediaId = mediaId;
      result.steps.push({name: "upload TEST media", success: true, mediaId});

      const mediaRead = await testRequest(`/media/${mediaId}?context=edit`);
      if (mediaRead?.id !== mediaId || mediaRead.post !== postId) throw new Error("WordPress media read-back failed.");
      result.steps.push({name: "read TEST media", success: true, mediaId});

      await testRequest(`/media/${mediaId}?force=true`, {method: "DELETE"});
      mediaId = null;
      result.steps.push({name: "delete TEST media", success: true});

      await testRequest(`/posts/${postId}?force=true`, {method: "DELETE"});
      postId = null;
      result.steps.push({name: "delete TEST post", success: true});

      result.success = true;
      result.summary = "WordPress read/write/update/media/delete verification passed.";
    } catch (error) {
      result.summary = `WordPress full write test failed: ${errorText(error)}`;
      result.steps.push({name: "failure", success: false, error: errorText(error)});
    } finally {
      if (mediaId) {
        try {
          await testRequest(`/media/${mediaId}?force=true`, {method: "DELETE"});
          result.steps.push({name: "cleanup TEST media", success: true, mediaId});
        } catch (error) {
          result.steps.push({name: "cleanup TEST media", success: false, error: errorText(error)});
        }
      }
      if (postId) {
        try {
          await testRequest(`/posts/${postId}?force=true`, {method: "DELETE"});
          result.steps.push({name: "cleanup TEST post", success: true, postId});
        } catch (error) {
          result.steps.push({name: "cleanup TEST post", success: false, error: errorText(error)});
        }
      }
    }

    result.trace = await diagnosticTraceSince(result.startedAt);
    result.completedAt = new Date().toISOString();
    return AssistantStorage.persistResult(result, "connection");
  }

  async function dualWriteTest() {
    const config = await getConfig();
    const results = [];
    for (const transport of ["wp-cli", "application-password"]) {
      const result = await fullWriteTest({...config, transport});
      results.push({...result, transport});
    }
    return AssistantStorage.persistResult({action: "connection.wordpress-dual-write", success: results.every(result => result.success), summary: "WP-CLI 与 REST 双路径验收：" + results.filter(result => result.success).length + "/2 通过", steps: results.flatMap(result => result.steps.map(step => ({...step, name: result.transport + " · " + step.name}))), results, startedAt: results[0].startedAt, completedAt: new Date().toISOString()}, "connection");
  }

  const MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ];
  const WEEKDAY_NAMES = [
    "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
  ];

  function dailyLogTitle(date = new Date()) {
    // Match the long-standing WP-CLI helper title shape.
    // Existing posts with extra spaces are still matched by matchesDailyLogTitle().
    return (
      MONTH_NAMES[date.getMonth()] + " " +
      date.getDate() + " " +
      WEEKDAY_NAMES[date.getDay()] + " " +
      date.getFullYear()
    );
  }

  function dailyLogSearchText(date = new Date()) {
    // A short month token lets the REST search find both "October" and "Oct"
    // titles. The exact day/weekday/year check is done locally below.
    return MONTH_NAMES[date.getMonth()].slice(0, 3);
  }

  function matchesDailyLogTitle(title, date = new Date()) {
    const text = String(title || "").toLowerCase().replace(/\s+/g, " ").trim();
    const canonical = dailyLogTitle(date).toLowerCase();
    const tokens = value => value.split(" ").sort().join(" ");
    return tokens(text) === tokens(canonical) || tokens(text) === tokens(canonical.replace(MONTH_NAMES[date.getMonth()].toLowerCase(), MONTH_NAMES[date.getMonth()].slice(0, 3).toLowerCase())) || text === AssistantStorage.localDateKey(date);
  }

  function rawTitle(post) {
    return String(post?.title?.raw || post?.title?.rendered || "").trim();
  }

  function rawContent(post) {
    return String(post?.content?.raw || post?.content?.rendered || "");
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function logMarker() {
    if (globalThis.crypto?.randomUUID) {
      return "caldav-assistant-log-" + crypto.randomUUID();
    }
    return "caldav-assistant-log-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  }

  async function dailyCandidates(date) {
    // Enumerate every page. Never silently select the first of multiple matches.
    const candidates = [];
    for (let page = 1; ; page++) {
      let rows;
      try {rows = await request("/posts?context=edit&status=publish,draft,pending,private,future&per_page=100&page=" + page);}
      catch (error) {if (page > 1 && error.code === "rest_post_invalid_page") break; throw error;}
      if (!Array.isArray(rows)) throw new Error("Invalid WordPress post listing");
      candidates.push(...rows.filter(post => matchesDailyLogTitle(rawTitle(post), date)));
      if (rows.length < 100 || effectiveTransport(await getConfig()) === "wp-cli" || autoWpCliFallback) break;
    }
    return candidates;
  }

  async function selectDailyPost(day, postId) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isSafeInteger(Number(postId)) || Number(postId) < 1) throw new Error("Invalid daily target");
    const date = new Date(day + "T12:00:00");
    const post = await request(`/posts/${Number(postId)}?context=edit`);
    if (!matchesDailyLogTitle(rawTitle(post), date) || post.status === "trash") throw new Error("Selected post does not match log date");
    const settings = await AssistantStorage.getSettings();
    const scope = (await getConfig()).baseUrl || (await getConfig()).wordpressPath;
    const targets = {...settings.wordpressDailyTargets, [scope + "|" + day]: Number(postId)};
    await AssistantStorage.saveSettings({wordpressDailyTargets: targets});
    return {success: true, day, postId: Number(postId), steps: ["selection write", "read back", "compare"]};
  }

  async function ensureDailyLogPost(date = new Date()) {
    const title = dailyLogTitle(date);
    const candidates = await dailyCandidates(date);
    const config = await getConfig();
    const settings = await AssistantStorage.getSettings();
    const key = (config.baseUrl || config.wordpressPath) + "|" + AssistantStorage.localDateKey(date);
    const chosen = settings.wordpressDailyTargets?.[key];
    let post;
    if (chosen) {
      post = candidates.find(row => row.id === chosen);
      if (!post) throw new Error("Selected daily post no longer matches; Outbox retained");
    } else if (candidates.length > 1) {
      const error = new Error("Ambiguous: multiple daily posts; Outbox retained");
      error.candidates = candidates.map(post => ({id: post.id, title: rawTitle(post), status: post.status}));
      error.day = AssistantStorage.localDateKey(date);
      throw error;
    } else post = candidates[0];
    if (post) return {post, title: rawTitle(post), created: false};
    post = await request("/posts", {method: "POST", json: {title, content: "", status: "publish"}});
    const read = await request(`/posts/${post.id}?context=edit`);
    if (read?.id !== post.id || rawTitle(read) !== title || rawContent(read) !== "" || read.status !== "publish") throw new Error("WordPress daily log create read-back mismatch.");
    return {post: read, title, created: true};
  }

  function currentTimeText(date = new Date()) {
    return (
      String(date.getHours()).padStart(2, "0") + ":" +
      String(date.getMinutes()).padStart(2, "0")
    );
  }

  function mediaBlock(item) {
    const id = Number(item.id || 0);
    const url = escapeHtml(item.sourceUrl || "");
    const filename = escapeHtml(item.filename || "附件");
    const mime = String(item.mimeType || "").toLocaleLowerCase();

    if (mime.startsWith("image/")) {
      return (
        '<!-- wp:image {"id":' + id + ',"sizeSlug":"large"} -->\n' +
        '<figure class="wp-block-image size-large"><img src="' + url +
        '" alt="' + filename + '" class="wp-image-' + id + '"/></figure>\n' +
        '<!-- /wp:image -->'
      );
    }
    if (mime.startsWith("video/")) {
      return (
        '<!-- wp:video {"id":' + id + '} -->\n' +
        '<figure class="wp-block-video"><video controls src="' + url +
        '"></video></figure>\n<!-- /wp:video -->'
      );
    }
    if (mime.startsWith("audio/")) {
      return (
        '<!-- wp:audio {"id":' + id + '} -->\n' +
        '<figure class="wp-block-audio"><audio controls src="' + url +
        '"></audio></figure>\n<!-- /wp:audio -->'
      );
    }
    return (
      '<!-- wp:file {"id":' + id + ',"href":"' + url + '"} -->\n' +
      '<div class="wp-block-file"><a href="' + url + '">' + filename +
      '</a></div>\n<!-- /wp:file -->'
    );
  }

  function safeLogMarker(value) {
    const text = String(value || "")
      .replace(/[^A-Za-z0-9_.:-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 180);
    return text || logMarker();
  }

  function buildLogAppend(content, media, marker, date = new Date(), prefixTime = true) {
    const blocks = [`<!-- ${marker} -->`];
    const text = String(content || "").trim();
    if (text) {
      blocks.push(
        "<!-- wp:paragraph -->\n<p>" +
        (prefixTime ? currentTimeText(date) + " " : "") +
        escapeHtml(text).replace(/\n/g, "<br>") +
        "</p>\n<!-- /wp:paragraph -->"
      );
    }
    for (const item of media || []) {
      blocks.push(mediaBlock(item));
    }
    return blocks.join("\n");
  }

  async function executeLog({
    content,
    files = [],
    date = new Date(),
    prefixTime = true,
    marker = "",
    pendingId = "",
    savedMedia = [],
  }) {
    const logDate = date instanceof Date ? date : new Date(date);
    const result = {
      action: "wordpress.append-log",
      success: false,
      startedAt: new Date().toISOString(),
      steps: [],
      summary: "",
      post: null,
      media: [],
      marker: safeLogMarker(marker),
      deduplicated: false,
    };

    try {
      const text = String(content || "").trim();
      if (!text && !(files || []).length) {
        throw new Error("日志内容或附件不能为空。");
      }
      if (Number.isNaN(logDate.getTime())) {
        throw new Error("日志日期无效。");
      }

      await validateTransportConfig();
      const daily = await ensureDailyLogPost(logDate);
      const postId = daily.post.id;
      result.post = {
        id: postId,
        title: daily.title,
        status: daily.post.status || "publish",
        link: daily.post.link || "",
        createdToday: daily.created,
      };
      result.steps.push({
        name: daily.created
          ? "create daily WordPress log post"
          : "reuse daily WordPress log post",
        success: true,
        postId,
        title: daily.title,
      });

      const before = await request(`/posts/${postId}?context=edit`);
      const previous = rawContent(before);
      if (!matchesDailyLogTitle(rawTitle(before), logDate)) throw new Error("Daily post changed during read");
      if (previous.includes(`<!-- ${result.marker} -->`)) {
        const expectedBlock = buildLogAppend(text, savedMedia, result.marker, logDate, prefixTime);
        if ((files || []).length !== savedMedia.length || !previous.includes(expectedBlock)) throw new Error("Conflict: marker exists with different content");
        if (previous.split(`<!-- ${result.marker} -->`).length !== 2) throw new Error("Conflict: duplicate marker");
        result.success = true;
        result.deduplicated = true;
        result.steps.push({
          name: "deduplicate existing WordPress log marker",
          success: true,
          postId,
          marker: result.marker,
        });
        result.summary =
          `日志已经存在于 ${daily.title}（Post ${postId}），未重复写入。`;
        result.completedAt = new Date().toISOString();
        return AssistantStorage.persistResult(result, "wordpress");
      }

      if (savedMedia.some(item => item.parent !== postId)) throw new Error("Uploaded attachments belong to another selected daily post; Outbox retained");
      result.media = [...savedMedia];
      for (const file of (files || []).slice(savedMedia.length)) {
        const uploaded = await uploadMedia(
          file,
          file.name || "attachment",
          postId
        );
        const item = {
          id: uploaded.id,
          filename: file.name || "attachment",
          sourceUrl: uploaded.source_url || "",
          mimeType:
            file.type || uploaded.mime_type || "application/octet-stream",
          parent: postId,
        };
        const mediaRead = await request(`/media/${item.id}?context=edit`);
        if (mediaRead.id !== item.id || mediaRead.post !== postId || mediaRead.source_url !== item.sourceUrl) throw new Error("WordPress media read-back mismatch");
        result.media.push(item);
        if (pendingId) {
          const pending = (await AssistantStorage.listWordPressOutbox()).find(row => row.id === pendingId);
          if (!pending) throw new Error("Missing durable Outbox record");
          await AssistantStorage.updateWordPressOutbox(pendingId, {payload: {...pending.payload, media: result.media}});
        }
        result.steps.push({
          name: "upload WordPress media",
          success: true,
          mediaId: item.id,
          filename: item.filename,
          parentPostId: postId,
        });
      }

      const append = buildLogAppend(
        text,
        result.media,
        result.marker,
        logDate,
        prefixTime
      );
      const next = previous
        ? previous + "\n\n" + append
        : append;

      await request(`/posts/${postId}`, {
        method: "POST",
        json: {content: next},
      });

      const read = await request(`/posts/${postId}?context=edit`);
      const verified = rawContent(read);
      if (verified !== next || read.id !== postId || rawTitle(read) !== rawTitle(before) || read.status !== before.status) {
        throw new Error("WordPress log append read-back mismatch.");
      }

      result.steps.push({
        name: "append + read-back daily WordPress log",
        success: true,
        postId,
        marker: result.marker,
      });
      result.success = true;
      result.summary =
        `已追加到 ${daily.title}（Post ${postId}），并完成回读验证。`;
    } catch (error) {
      result.summary = `WordPress log append failed: ${errorText(error)}`;
      if (error.candidates) {result.candidates = error.candidates; result.day = error.day;}
      result.steps.push({
        name: "failure",
        success: false,
        error: errorText(error),
      });
    }

    result.completedAt = new Date().toISOString();
    return AssistantStorage.persistResult(result, "wordpress");
  }

  let writeTail = Promise.resolve();
  function exclusive(fn) {
    if (globalThis.navigator?.locks) return navigator.locks.request("caldav-assistant-wordpress-write", fn);
    const next = writeTail.then(fn, fn); writeTail = next.catch(() => {}); return next;
  }

  async function pendingCandidates() {
    const records = await AssistantStorage.listWordPressOutbox();
    const days = [...new Set(records.map(row => row.payload.dateKey || AssistantStorage.localDateKey(row.payload.startIso || row.payload.date)))];
    const result = [];
    for (const day of days) result.push({day, candidates: (await dailyCandidates(new Date(day + "T12:00:00"))).map(post => ({id: post.id, title: rawTitle(post), status: post.status}))});
    return result;
  }

  function createLog(options) {
    return exclusive(async () => {
      const marker = safeLogMarker(options.marker);
      let pending = (await AssistantStorage.listWordPressOutbox()).find(row => row.payload.marker === marker);
      if (!pending) {
        const files = [];
        for (const file of options.files || []) files.push({name: file.name || "attachment", type: file.type, base64: bytesToBase64(new Uint8Array(await file.arrayBuffer()))});
        const date = options.date || new Date();
        pending = await AssistantStorage.enqueueWordPressOutbox({payload: {type: "manual-log", content: options.content, startIso: date.toISOString(), dateKey: AssistantStorage.localDateKey(date), timeText: currentTimeText(date), timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone, prefixTime: options.prefixTime !== false, marker, files}});
      }
      const payload = pending.payload;
      const files = (payload.files || []).map(file => {
        const blob = new Blob([Uint8Array.from(atob(file.base64), char => char.charCodeAt(0))], {type: file.type});
        blob.name = file.name; return blob;
      });
      const result = await executeLog({content: payload.content, date: payload.dateKey ? new Date(payload.dateKey + "T" + (payload.timeText || "12:00") + ":00") : new Date(payload.startIso), prefixTime: payload.prefixTime === true, marker: payload.marker, files, pendingId: pending.id, savedMedia: payload.media || []});
      if (result.success) await AssistantStorage.removeWordPressOutbox(pending.id);
      else await AssistantStorage.updateWordPressOutbox(pending.id, {attempts: Number(pending.attempts || 0) + 1, lastError: result.summary});
      return {...result, queued: !result.success, outboxId: pending.id};
    });
  }

  globalThis.AssistantWordPress = Object.freeze({
    getConfig,
    saveConfig,
    quickTest,
    fullWriteTest,
    dualWriteTest,
    createLog,
    selectDailyPost,
    pendingCandidates,
  });
})();
