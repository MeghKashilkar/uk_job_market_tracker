/**
 * Thin typed-ish wrapper over the dashboard API.
 *
 * Base URL resolution:
 *   - Served from localhost/127.0.0.1 (local `uvicorn`, which serves both the
 *     UI and the API): same origin, so the base is empty.
 *   - Anywhere else (Vercel, or the Render URL directly): the backend named in
 *     <meta name="api-base">. This is what makes the Vercel-hosted frontend
 *     reach the Render backend without depending on a Vercel rewrite - the CDN
 *     serves the static files, the browser calls Render directly, and Render's
 *     CORS is open.
 *
 * Every call funnels through `request`, so error handling and the in-flight
 * abort behaviour live in exactly one place.
 */
(function (global) {
  "use strict";

  function resolveBase() {
    const host = global.location.hostname;
    if (host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0") {
      return ""; // local dev: uvicorn serves the API on the same origin
    }
    const meta = document.querySelector('meta[name="api-base"]');
    return (meta && meta.getAttribute("content")) || "";
  }

  const BASE = resolveBase();

  /** Requests currently in flight, keyed so a newer one cancels its predecessor. */
  const inFlight = new Map();

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  }

  async function request(path, options) {
    const opts = options || {};
    const key = opts.key || path;

    if (inFlight.has(key)) {
      inFlight.get(key).abort();
    }
    const controller = new AbortController();
    inFlight.set(key, controller);

    let response;
    try {
      response = await fetch(BASE + path, {
        method: opts.method || "GET",
        headers: opts.body ? { "Content-Type": "application/json" } : undefined,
        body: opts.body ? JSON.stringify(opts.body) : undefined,
        signal: controller.signal,
      });
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new ApiError("Cannot reach the API. Is the server running?", 0);
    } finally {
      if (inFlight.get(key) === controller) inFlight.delete(key);
    }

    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const payload = await response.json();
        if (payload && payload.detail) {
          detail =
            typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
        }
      } catch (_) {
        /* response had no JSON body - keep the status-based message */
      }
      throw new ApiError(detail, response.status);
    }

    return response.json();
  }

  /** Build a repeated-key query string from the filter selections. */
  function toQuery(filters, extra) {
    const params = new URLSearchParams();
    Object.keys(filters || {}).forEach(function (field) {
      (filters[field] || []).forEach(function (value) {
        params.append(field, value);
      });
    });
    Object.keys(extra || {}).forEach(function (field) {
      const value = extra[field];
      if (value === null || value === undefined || value === "") return;
      if (Array.isArray(value)) {
        value.forEach((item) => params.append(field, item));
      } else {
        params.append(field, String(value));
      }
    });
    const query = params.toString();
    return query ? "?" + query : "";
  }

  global.Api = {
    ApiError: ApiError,
    health: () => request("/api/health", { key: "health" }),
    meta: () => request("/api/meta", { key: "meta" }),
    // `key` is overridable so two callers wanting the same endpoint concurrently
    // (the overview charts and the filter panel's result count) do not abort
    // each other via the de-duplication in `request`.
    overview: (filters, options) =>
      request("/api/overview" + toQuery(filters), {
        key: (options && options.key) || "overview",
      }),
    skills: (filters, extra) => request("/api/skills" + toQuery(filters, extra), { key: "skills" }),
    skillTrend: (filters, extra) =>
      request("/api/skills/trend" + toQuery(filters, extra), { key: "trend" }),
    salary: (filters) => request("/api/salary" + toQuery(filters), { key: "salary" }),
    postings: (filters, extra) =>
      request("/api/postings" + toQuery(filters, extra), { key: "postings" }),
    predict: (payload) =>
      request("/api/predict", { method: "POST", body: payload, key: "predict" }),
    startRefresh: () => request("/api/refresh", { method: "POST", key: "refresh" }),
    refreshStatus: () => request("/api/refresh/status", { key: "refresh-status" }),
  };
})(window);
