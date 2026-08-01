/**
 * Dashboard controller.
 *
 * Holds the single source of truth for filter state and the active view, then
 * lazily loads each view's data the first time it is shown and re-loads every
 * loaded view whenever filters change. Views are cached so tab switching is
 * instant and does not re-hit the API.
 */
(function (global) {
  "use strict";

  const FILTER_FIELDS = ["role_category", "seniority", "location", "region", "contract_type"];
  const FILTER_LABELS = {
    role_category: "Role category",
    seniority: "Seniority",
    location: "Location",
    region: "Region",
    contract_type: "Contract type",
  };
  const THEME_KEY = "ukjobs.theme";
  const MAX_TREND_SKILLS = 8;

  const state = {
    view: "overview",
    filters: Object.fromEntries(FILTER_FIELDS.map((f) => [f, []])),
    meta: null,
    trendSkills: [],
    predictSkills: new Set(),
    postings: [],
    loaded: new Set(),
  };

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));

  /* ----------------------------------------------------------- formatting */

  const numberFormat = new Intl.NumberFormat("en-GB");

  function formatMoney(value) {
    return value === null || value === undefined ? "-" : "£" + numberFormat.format(value);
  }

  function activeFilterCount() {
    return FILTER_FIELDS.reduce((total, field) => total + state.filters[field].length, 0);
  }

  /* --------------------------------------------------------------- errors */

  function showAlert(message) {
    const alert = $("#global-alert");
    alert.innerHTML = message;
    alert.hidden = false;
  }

  function clearAlert() {
    $("#global-alert").hidden = true;
  }

  /** Run a loader, showing skeletons then surfacing any failure to the user. */
  async function guard(containers, work) {
    containers.forEach(function (selector) {
      const node = $(selector);
      if (node && !node.dataset.loaded) {
        node.innerHTML = '<div class="skeleton skeleton--chart"></div>';
      }
      if (node) node.classList.add("is-busy");
    });

    try {
      await work();
      clearAlert();
    } catch (error) {
      if (error && error.name === "AbortError") return;
      showAlert(
        "<strong>Could not load data.</strong> " +
          (error && error.message ? error.message : "Unknown error.")
      );
      containers.forEach(function (selector) {
        const node = $(selector);
        if (node && !node.dataset.loaded) {
          Charts.empty(node, "Unavailable");
        }
      });
    } finally {
      containers.forEach(function (selector) {
        const node = $(selector);
        if (node) {
          node.classList.remove("is-busy");
          node.dataset.loaded = "1";
        }
      });
    }
  }

  /* ------------------------------------------------------------ chrome/UI */

  function applyTheme(theme) {
    if (theme) {
      document.documentElement.setAttribute("data-theme", theme);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }

  function initTheme() {
    applyTheme(localStorage.getItem(THEME_KEY));
    $("#theme-toggle").addEventListener("click", function () {
      const isDark = document.documentElement.getAttribute("data-theme")
        ? document.documentElement.getAttribute("data-theme") === "dark"
        : global.matchMedia("(prefers-color-scheme: dark)").matches;
      const next = isDark ? "light" : "dark";
      localStorage.setItem(THEME_KEY, next);
      applyTheme(next);
      renderActiveView(true);
    });
  }

  /** Slide the segmented control's thumb under the active tab. */
  function moveThumb() {
    const active = $(".segmented__item.is-active");
    const thumb = $(".segmented__thumb");
    if (!active || !thumb) return;
    thumb.style.width = active.offsetWidth + "px";
    thumb.style.transform = `translateX(${active.offsetLeft - 3}px)`;
  }

  function revealCards() {
    $$("[data-reveal]").forEach(function (card, index) {
      if (card.closest(".view[hidden]")) return;
      if (card.classList.contains("is-revealed")) return;
      setTimeout(() => card.classList.add("is-revealed"), index * 70);
    });
  }

  function switchView(view) {
    if (state.view === view) return;
    state.view = view;

    $$(".segmented__item").forEach(function (tab) {
      const isActive = tab.dataset.view === view;
      tab.classList.toggle("is-active", isActive);
      tab.setAttribute("aria-selected", String(isActive));
    });
    $$(".view").forEach(function (section) {
      const isActive = section.id === "view-" + view;
      section.hidden = !isActive;
      section.classList.toggle("is-active", isActive);
    });

    moveThumb();
    revealCards();
    loadView(view);
  }

  /* -------------------------------------------------------- filter panel */

  function openFilters() {
    $("#filter-panel").hidden = false;
    $("#filter-scrim").hidden = false;
    $("#filter-toggle").setAttribute("aria-expanded", "true");
    $("#filter-reset").focus();
  }

  function closeFilters() {
    $("#filter-panel").hidden = true;
    $("#filter-scrim").hidden = true;
    $("#filter-toggle").setAttribute("aria-expanded", "false");
  }

  function renderFilterPanel() {
    const options = (state.meta && state.meta.filters) || {};
    const host = $("#filter-groups");
    host.innerHTML = "";

    FILTER_FIELDS.forEach(function (field) {
      const values = options[field] || [];
      if (!values.length) return;

      const group = document.createElement("section");
      group.className = "filter-group";

      const head = document.createElement("div");
      head.className = "filter-group__head";
      const title = document.createElement("span");
      title.className = "filter-group__title";
      title.textContent = FILTER_LABELS[field] || field;
      const meta = document.createElement("span");
      meta.className = "filter-group__meta";
      meta.textContent = `${values.length} options`;
      head.append(title, meta);

      const chips = document.createElement("div");
      chips.className = "chip-row";
      // Long lists (locations run to hundreds) stay usable by showing the most
      // common values; the rest remain reachable via the postings search.
      values.slice(0, 40).forEach(function (value) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip";
        chip.textContent = value;
        chip.setAttribute("aria-pressed", "false");
        if (state.filters[field].includes(value)) {
          chip.classList.add("is-selected");
          chip.setAttribute("aria-pressed", "true");
        }
        chip.addEventListener("click", function () {
          const selected = state.filters[field];
          const index = selected.indexOf(value);
          if (index >= 0) selected.splice(index, 1);
          else selected.push(value);
          chip.classList.toggle("is-selected", index < 0);
          chip.setAttribute("aria-pressed", String(index < 0));
          onFiltersChanged();
        });
        chips.appendChild(chip);
      });

      group.append(head, chips);
      host.appendChild(group);
    });

    if (!host.children.length) {
      host.innerHTML = '<p class="chart-empty">No filterable fields in this dataset.</p>';
    }
  }

  function syncFilterBadge() {
    const count = activeFilterCount();
    const badge = $("#filter-count");
    badge.textContent = String(count);
    badge.hidden = count === 0;
  }

  function onFiltersChanged() {
    syncFilterBadge();
    state.loaded.clear();
    loadView(state.view);
    refreshFilterResultCount();
  }

  async function refreshFilterResultCount() {
    try {
      const data = await Api.overview(state.filters, { key: "filter-count" });
      const total = (state.meta && state.meta.dataset.total_rows) || data.totals.postings;
      $("#filter-result-count").textContent =
        `${numberFormat.format(data.totals.postings)} of ${numberFormat.format(total)} postings`;
    } catch (error) {
      if (error && error.name === "AbortError") return; // superseded by a newer change
      $("#filter-result-count").textContent = "-";
    }
  }

  /* ------------------------------------------------------------ view: overview */

  function renderStats(totals) {
    const cards = [
      { label: "Postings", value: numberFormat.format(totals.postings) },
      { label: "Companies", value: numberFormat.format(totals.companies) },
      { label: "Locations", value: numberFormat.format(totals.locations) },
      {
        label: "Median salary",
        value: totals.median_salary ? formatMoney(totals.median_salary) : "-",
        hint: `${Math.round(totals.salary_coverage * 100)}% of postings list pay`,
      },
    ];

    const host = $("#stat-row");
    host.innerHTML = "";
    cards.forEach(function (card, index) {
      const node = document.createElement("div");
      node.className = "stat";
      node.style.opacity = "0";
      node.innerHTML =
        `<div class="stat__label">${card.label}</div>` +
        `<div class="stat__value">${card.value}</div>` +
        (card.hint ? `<div class="stat__hint">${card.hint}</div>` : "");
      host.appendChild(node);
      node.animate(
        [
          { opacity: 0, transform: "translateY(10px)" },
          { opacity: 1, transform: "none" },
        ],
        { duration: 460, delay: index * 60, easing: "cubic-bezier(0.22,0.61,0.36,1)", fill: "both" }
      );
    });
  }

  async function loadOverview() {
    await guard(
      ["#chart-postings-week", "#chart-salary-hist", "#chart-by-role", "#chart-locations"],
      async function () {
        const [data, salary] = await Promise.all([
          Api.overview(state.filters),
          Api.salary(state.filters),
        ]);

        renderStats(data.totals);
        Charts.lineChart(
          $("#chart-postings-week"),
          [{ label: "Postings", points: data.postings_per_week.map((p) => ({ period: p.period, value: p.count })) }],
          { area: true, emptyMessage: "No dated postings in view." }
        );
        Charts.histogram($("#chart-salary-hist"), salary.histogram, {
          emptyMessage: "No salary data in view.",
        });
        Charts.horizontalBar(
          $("#chart-by-role"),
          data.by_role.map((row, i) => ({ label: row.label, value: row.count, color: Charts.seriesColor(i) }))
        );
        Charts.horizontalBar(
          $("#chart-locations"),
          data.top_locations.map((row) => ({ label: row.label, value: row.count })),
          { colorIndex: 5 }
        );
      }
    );
  }

  /* -------------------------------------------------------------- view: skills */

  function renderTrendChips(available) {
    const host = $("#trend-chips");
    host.innerHTML = "";
    available.slice(0, 24).forEach(function (skill) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = skill;
      const selected = state.trendSkills.includes(skill);
      chip.classList.toggle("is-selected", selected);
      chip.setAttribute("aria-pressed", String(selected));
      chip.addEventListener("click", function () {
        const index = state.trendSkills.indexOf(skill);
        if (index >= 0) {
          state.trendSkills.splice(index, 1);
        } else {
          if (state.trendSkills.length >= MAX_TREND_SKILLS) return;
          state.trendSkills.push(skill);
        }
        chip.classList.toggle("is-selected", index < 0);
        chip.setAttribute("aria-pressed", String(index < 0));
        loadSkillTrend();
      });
      host.appendChild(chip);
    });
  }

  async function loadSkillTrend() {
    await guard(["#chart-skill-trend"], async function () {
      const trend = await Api.skillTrend(state.filters, { skills: state.trendSkills });
      if (!state.trendSkills.length) state.trendSkills = trend.skills.slice(0, 4);

      // Align every series onto the same period axis so the lines share an x scale.
      const periods = Array.from(
        new Set(trend.series.flatMap((s) => s.points.map((p) => p.period)))
      ).sort();
      const series = trend.series.map(function (s) {
        const byPeriod = new Map(s.points.map((p) => [p.period, p.value]));
        return {
          label: s.skill,
          points: periods.map((period) => ({ period: period, value: byPeriod.get(period) || 0 })),
        };
      });

      Charts.lineChart($("#chart-skill-trend"), series, {
        legend: true,
        height: 280,
        emptyMessage: "Not enough dated data to trend these skills yet.",
      });
      renderTrendChips(trend.skills.concat(state.trendSkills).filter((v, i, a) => a.indexOf(v) === i));
    });
  }

  async function loadSkills() {
    await guard(["#chart-skill-demand"], async function () {
      const category = $("#skill-category").value;
      const limit = Number($("#skill-limit").value);
      const data = await Api.skills(state.filters, { category: category, limit: limit });

      const categories = ["All"].concat(data.categories);
      const select = $("#skill-category");
      if (select.options.length !== categories.length) {
        select.innerHTML = categories
          .map((c) => `<option value="${c}"${c === category ? " selected" : ""}>${c}</option>`)
          .join("");
      }

      const palette = new Map(data.categories.map((c, i) => [c, Charts.seriesColor(i)]));
      Charts.horizontalBar(
        $("#chart-skill-demand"),
        data.skills.map((row) => ({
          label: row.skill,
          value: row.postings_mentioning,
          color: palette.get(row.category),
          suffix: ` (${row.pct_of_postings}%)`,
        })),
        { rowHeight: 28, labelChars: 20, emptyMessage: "No skills matched." }
      );

      if (!state.trendSkills.length) {
        state.trendSkills = data.skills.slice(0, 4).map((row) => row.skill);
      }
      renderTrendChips(data.skills.map((row) => row.skill));
    });
    await loadSkillTrend();
  }

  /* -------------------------------------------------------------- view: salary */

  async function loadSalary() {
    await guard(
      ["#chart-salary-role", "#chart-salary-seniority", "#chart-salary-skill"],
      async function () {
        const data = await Api.salary(state.filters);
        Charts.boxPlot($("#chart-salary-role"), data.by_role, {
          emptyMessage: "No salary data for these filters.",
        });
        Charts.boxPlot($("#chart-salary-seniority"), data.by_seniority, {
          emptyMessage: "No salary data for these filters.",
        });
        Charts.horizontalBar(
          $("#chart-salary-skill"),
          data.by_skill.map((row) => ({
            label: row.skill,
            value: row.median_salary,
            suffix: ` · ${row.postings} posts`,
          })),
          {
            colorIndex: 6,
            format: Charts.formatMoney,
            labelChars: 20,
            emptyMessage: "Not enough salaried postings per skill yet.",
          }
        );
      }
    );
  }

  /* ------------------------------------------------------------ view: predict */

  function fillSelect(selector, values, preferred) {
    const select = $(selector);
    select.innerHTML = values.map((v) => `<option value="${v}">${v}</option>`).join("");
    if (preferred && values.includes(preferred)) select.value = preferred;
  }

  function renderPredictSkills() {
    const taxonomy = state.meta.taxonomy.skills_by_category;
    const host = $("#predict-skills");
    host.innerHTML = "";

    Object.keys(taxonomy).forEach(function (category, categoryIndex) {
      taxonomy[category].forEach(function (skill) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip";
        chip.title = category;
        const dot = document.createElement("span");
        dot.className = "chip__dot";
        dot.style.background = Charts.seriesColor(categoryIndex);
        chip.append(dot, document.createTextNode(skill));
        chip.setAttribute("aria-pressed", "false");
        chip.addEventListener("click", function () {
          const selected = state.predictSkills.has(skill);
          if (selected) state.predictSkills.delete(skill);
          else state.predictSkills.add(skill);
          chip.classList.toggle("is-selected", !selected);
          chip.setAttribute("aria-pressed", String(!selected));
          $("#predict-skill-count").textContent = `${state.predictSkills.size} selected`;
        });
        host.appendChild(chip);
      });
    });
  }

  function setupPredict() {
    const options = state.meta.filters;
    fillSelect("#predict-role", options.role_category || [], "Data Scientist");
    fillSelect("#predict-seniority", options.seniority || [], "Senior");
    fillSelect("#predict-region", options.region || [], "London");
    fillSelect("#predict-contract-type", options.contract_type || ["permanent"]);
    fillSelect("#predict-contract-time", ["full_time", "part_time"]);
    renderPredictSkills();

    $("#predict-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      const button = $("#predict-submit");
      button.disabled = true;
      button.textContent = "Estimating…";

      try {
        const result = await Api.predict({
          role_category: $("#predict-role").value,
          seniority: $("#predict-seniority").value,
          region: $("#predict-region").value,
          contract_type: $("#predict-contract-type").value,
          contract_time: $("#predict-contract-time").value,
          skills: Array.from(state.predictSkills),
        });
        renderPrediction(result);
      } catch (error) {
        $("#predict-result").innerHTML =
          `<div class="placeholder"><div class="placeholder__mark">!</div><p>${
            error.message || "Prediction failed."
          }</p></div>`;
      } finally {
        button.disabled = false;
        button.textContent = "Estimate salary";
      }
    });
  }

  function renderPrediction(result) {
    $("#predict-result").innerHTML = `
      <div class="result">
        <div>
          <div class="result__label">Estimated annual salary</div>
          <div class="result__value">${formatMoney(result.predicted_salary)}</div>
        </div>
        <div class="result__bar"><span></span></div>
        <p class="result__range">
          Likely range ${formatMoney(result.lower_bound)} – ${formatMoney(result.upper_bound)}
        </p>
        <dl class="result__meta">
          <div><dt>Model</dt><dd>${result.model_name}</dd></div>
          <div><dt>Trained on</dt><dd>${numberFormat.format(result.n_training_rows)}</dd></div>
          <div><dt>Test R²</dt><dd>${result.r2}</dd></div>
          <div><dt>Typical error</dt><dd>${formatMoney(result.mae_gbp)}</dd></div>
        </dl>
        <p class="result__note">
          ${result.skills_recognised.length} skill${
            result.skills_recognised.length === 1 ? "" : "s"
          } fed into the model${
            result.skills_ignored.length
              ? `, ${result.skills_ignored.length} unrecognised and ignored`
              : ""
          }. This is a rough guide from advertised salaries - not an offer, and only as
          good as the data collected so far.
        </p>
      </div>`;
  }

  /* ----------------------------------------------------------- view: postings */

  function renderPostings(postings) {
    const host = $("#postings-list");
    const query = $("#postings-search").value.trim().toLowerCase();
    const visible = query
      ? postings.filter(function (posting) {
          const haystack = [posting.title, posting.company, posting.location]
            .concat(posting.skills)
            .join(" ")
            .toLowerCase();
          return haystack.includes(query);
        })
      : postings;

    if (!visible.length) {
      host.innerHTML = '<div class="chart-empty">No postings match.</div>';
      return;
    }

    host.innerHTML = visible
      .map(function (posting) {
        const skills = posting.skills.map((s) => `<span class="tag">${s}</span>`).join("");
        const title = posting.url
          ? `<a href="${posting.url}" target="_blank" rel="noopener noreferrer">${posting.title}</a>`
          : posting.title;
        return `
          <article class="posting">
            <div class="posting__main">
              <div class="posting__title">${title}</div>
              <div class="posting__meta">
                ${[posting.company, posting.location, posting.seniority]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
              <div class="posting__skills">${skills}</div>
            </div>
            <div class="posting__salary">
              ${posting.salary ? formatMoney(posting.salary) : "-"}
              <span class="posting__date">${Charts.formatDate(posting.created)}</span>
            </div>
          </article>`;
      })
      .join("");
  }

  async function loadPostings() {
    await guard(["#postings-list"], async function () {
      const data = await Api.postings(state.filters, { limit: 100 });
      state.postings = data.postings;
      renderPostings(state.postings);
    });
  }

  /* ------------------------------------------------------------ live refresh */

  const REFRESH_POLL_MS = 2000;

  function showToast(message, variant) {
    const toast = $("#refresh-toast");
    toast.className = "toast" + (variant ? " toast--" + variant : "");
    toast.textContent = message;
    toast.hidden = false;
  }

  function setRefreshBusy(busy) {
    const button = $("#refresh-button");
    button.classList.toggle("is-spinning", busy);
    button.disabled = busy;
  }

  /** Poll until the background job leaves the running state. */
  async function pollRefresh() {
    const status = await Api.refreshStatus();

    if (status.status === "running") {
      showToast(status.message, null);
      setTimeout(() => pollRefresh().catch(() => setRefreshBusy(false)), REFRESH_POLL_MS);
      return;
    }

    setRefreshBusy(false);
    showToast(status.message, status.status === "failed" ? "failed" : "done");

    if (status.status === "done") {
      // The dataset changed underneath us: re-read the summary and redraw
      // whichever view is on screen, dropping the per-view cache first.
      state.meta = await Api.meta();
      renderDatasetSummary();
      renderFilterPanel();
      state.loaded.clear();
      await loadView(state.view, true);
      refreshFilterResultCount();
    }
  }

  async function onRefreshClicked() {
    setRefreshBusy(true);
    showToast("Starting refresh…", null);
    try {
      await Api.startRefresh();
      await pollRefresh();
    } catch (error) {
      setRefreshBusy(false);
      // 429 (cooldown) and 409 (already running) are expected states, not faults.
      const expected = error.status === 429 || error.status === 409;
      showToast(error.message || "Could not start a refresh.", expected ? null : "failed");
    }
  }

  function setupRefresh() {
    const available = state.meta && state.meta.refresh && state.meta.refresh.available;
    const button = $("#refresh-button");
    button.hidden = !available;
    if (available) {
      button.addEventListener("click", onRefreshClicked);
    }
  }

  /* ------------------------------------------------------------- orchestration */

  const LOADERS = {
    overview: loadOverview,
    skills: loadSkills,
    salary: loadSalary,
    postings: loadPostings,
    predict: async function () {
      /* Static form - populated once from meta, nothing per-filter to fetch. */
    },
  };

  function loadView(view, force) {
    if (state.loaded.has(view) && !force) return Promise.resolve();
    state.loaded.add(view);
    return (LOADERS[view] || (() => Promise.resolve()))();
  }

  function renderActiveView(force) {
    return loadView(state.view, force !== false);
  }

  function renderDatasetSummary() {
    const dataset = state.meta.dataset;
    $("#dataset-summary").textContent =
      `${numberFormat.format(dataset.total_rows)} postings` +
      (dataset.collected_from
        ? ` · collected ${Charts.formatDate(dataset.collected_from)}–${Charts.formatDate(
            dataset.collected_to
          )}`
        : "");

    $("#model-card").textContent = state.meta.model
      ? `Salary model: ${state.meta.model.name} · R² ${state.meta.model.r2} · ` +
        `typical error ${formatMoney(state.meta.model.mae_gbp)} · ` +
        `trained on ${numberFormat.format(state.meta.model.n_training_rows)} salaried postings · ` +
        `${state.meta.taxonomy.total_skills} skills tracked`
      : "No trained salary model found - run python -m src.train_salary_model.";
  }


  function bindChrome() {
    $$(".segmented__item").forEach(function (tab) {
      tab.addEventListener("click", () => switchView(tab.dataset.view));
    });

    $("#filter-toggle").addEventListener("click", function () {
      if ($("#filter-panel").hidden) openFilters();
      else closeFilters();
    });
    $("#filter-scrim").addEventListener("click", closeFilters);
    $("#filter-apply").addEventListener("click", closeFilters);
    $("#filter-reset").addEventListener("click", function () {
      FILTER_FIELDS.forEach((field) => (state.filters[field] = []));
      renderFilterPanel();
      onFiltersChanged();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !$("#filter-panel").hidden) closeFilters();
    });

    $("#skill-category").addEventListener("change", () => loadView("skills", true));
    $("#skill-limit").addEventListener("change", () => loadView("skills", true));
    $("#postings-search").addEventListener("input", () => renderPostings(state.postings));

    let resizeTimer = null;
    global.addEventListener("resize", function () {
      moveThumb();
      clearTimeout(resizeTimer);
      // Charts are drawn to a fixed viewBox, so they need a redraw at a new width.
      resizeTimer = setTimeout(() => loadView(state.view, true), 220);
    });
  }

  async function init() {
    initTheme();
    bindChrome();

    try {
      state.meta = await Api.meta();
    } catch (error) {
      showAlert(
        "<strong>Cannot reach the API.</strong> Start it with " +
          "<code>uvicorn api.main:app --reload</code>, or check that the backend is deployed." +
          (error && error.message ? ` <em>(${error.message})</em>` : "")
      );
      return;
    }

    renderDatasetSummary();
    renderFilterPanel();
    syncFilterBadge();
    setupPredict();
    setupRefresh();
    moveThumb();
    revealCards();
    await loadView("overview");
    refreshFilterResultCount();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
