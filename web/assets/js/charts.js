/**
 * Minimal animated SVG chart toolkit.
 *
 * Hand-rolled rather than pulled from a charting library: the dashboard needs
 * exactly four mark types, wants spring-timed entrances that match the rest of
 * the UI, and must inherit theme colours from CSS custom properties. That is a
 * few hundred lines here versus a dependency plus a plugin for box plots.
 *
 * Every renderer takes (container, data, options) and replaces the container's
 * contents. Charts re-render on resize and on theme change.
 */
(function (global) {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const SERIES_COUNT = 8;
  const REDUCED_MOTION = global.matchMedia("(prefers-reduced-motion: reduce)");

  /* ---------------------------------------------------------------- utils */

  function el(name, attrs, parent) {
    const node = document.createElementNS(SVG_NS, name);
    for (const key in attrs) {
      if (attrs[key] !== null && attrs[key] !== undefined) {
        node.setAttribute(key, String(attrs[key]));
      }
    }
    if (parent) parent.appendChild(node);
    return node;
  }

  function seriesColor(index) {
    return `var(--series-${(index % SERIES_COUNT) + 1})`;
  }

  function formatCompact(value) {
    const abs = Math.abs(value);
    if (abs >= 1e9) return (value / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
    if (abs >= 1e6) return (value / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (abs >= 1e3) return (value / 1e3).toFixed(abs >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "k";
    return String(Math.round(value));
  }

  function formatMoney(value) {
    return "£" + Math.round(value).toLocaleString("en-GB");
  }

  function formatDate(iso) {
    const date = new Date(iso + "T00:00:00Z");
    if (Number.isNaN(date.getTime())) return iso;
    return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
  }

  /** "Nice" axis ceiling so gridlines land on round numbers. */
  function niceCeil(value) {
    if (value <= 0) return 1;
    const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
    const scaled = value / magnitude;
    const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
    return step * magnitude;
  }

  function truncate(text, max) {
    return text.length > max ? text.slice(0, max - 1) + "…" : text;
  }

  function prefersReducedMotion() {
    return REDUCED_MOTION.matches;
  }

  /* -------------------------------------------------------------- tooltip */

  let tooltipNode = null;

  function tooltip() {
    if (!tooltipNode) {
      tooltipNode = document.createElement("div");
      tooltipNode.className = "chart-tooltip";
      tooltipNode.setAttribute("role", "status");
      document.body.appendChild(tooltipNode);
    }
    return tooltipNode;
  }

  /** Wire hover/focus tooltips onto a mark. */
  function attachTooltip(node, text) {
    node.addEventListener("pointerenter", function (event) {
      const tip = tooltip();
      tip.textContent = text;
      tip.style.left = event.clientX + "px";
      tip.style.top = event.clientY + "px";
      tip.classList.add("is-visible");
    });
    node.addEventListener("pointermove", function (event) {
      const tip = tooltip();
      tip.style.left = event.clientX + "px";
      tip.style.top = event.clientY + "px";
    });
    node.addEventListener("pointerleave", function () {
      tooltip().classList.remove("is-visible");
    });
  }

  /* ------------------------------------------------------------ scaffolding */

  function prepare(container, height) {
    container.innerHTML = "";
    const width = Math.max(container.clientWidth || 0, 280);
    const svg = el(
      "svg",
      {
        class: "chart",
        viewBox: `0 0 ${width} ${height}`,
        width: "100%",
        height: height,
        role: "img",
      },
      container
    );
    return { svg, width, height };
  }

  function empty(container, message) {
    container.innerHTML = "";
    const node = document.createElement("div");
    node.className = "chart-empty";
    node.textContent = message || "No data for the current filters.";
    container.appendChild(node);
  }

  function legend(container, items) {
    const wrap = document.createElement("div");
    wrap.className = "chart-legend";
    items.forEach(function (item) {
      const entry = document.createElement("span");
      entry.className = "chart-legend__item";
      const swatch = document.createElement("span");
      swatch.className = "chart-legend__swatch";
      swatch.style.background = item.color;
      entry.appendChild(swatch);
      entry.appendChild(document.createTextNode(item.label));
      wrap.appendChild(entry);
    });
    container.appendChild(wrap);
  }

  /** Animate a numeric attribute from `from` to `to` with an ease-out curve. */
  function animateAttr(node, attr, from, to, duration, delay) {
    if (prefersReducedMotion() || duration <= 0) {
      node.setAttribute(attr, String(to));
      return;
    }
    node.setAttribute(attr, String(from));
    const start = performance.now() + (delay || 0);
    function frame(now) {
      const elapsed = now - start;
      if (elapsed < 0) {
        requestAnimationFrame(frame);
        return;
      }
      const t = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      node.setAttribute(attr, String(from + (to - from) * eased));
      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  /* ------------------------------------------------------- horizontal bars */

  function horizontalBar(container, data, options) {
    const opts = options || {};
    if (!data || !data.length) return empty(container, opts.emptyMessage);

    const rowHeight = opts.rowHeight || 30;
    const labelWidth = opts.labelWidth || 132;
    const padRight = 58;
    const padTop = 6;
    const height = padTop * 2 + data.length * rowHeight;
    const view = prepare(container, height);
    const trackWidth = Math.max(view.width - labelWidth - padRight, 60);
    const max = niceCeil(Math.max.apply(null, data.map((d) => d.value)) || 1);
    const format = opts.format || formatCompact;

    data.forEach(function (row, index) {
      const y = padTop + index * rowHeight;
      const barHeight = Math.min(rowHeight - 10, 20);
      const width = Math.max((row.value / max) * trackWidth, row.value > 0 ? 2 : 0);

      el(
        "text",
        {
          class: "chart__axis-label",
          x: labelWidth - 10,
          y: y + barHeight / 2 + 4,
          "text-anchor": "end",
        },
        view.svg
      ).textContent = truncate(row.label, opts.labelChars || 18);

      const bar = el(
        "rect",
        {
          class: "chart__bar",
          x: labelWidth,
          y: y,
          height: barHeight,
          rx: barHeight / 2,
          fill: row.color || opts.color || seriesColor(opts.colorIndex || 0),
          width: 0,
        },
        view.svg
      );
      animateAttr(bar, "width", 0, width, 560, index * 26);
      attachTooltip(bar, `${row.label}: ${format(row.value)}${row.suffix || ""}`);

      const value = el(
        "text",
        {
          class: "chart__value-label",
          x: labelWidth + width + 8,
          y: y + barHeight / 2 + 4,
          opacity: 0,
        },
        view.svg
      );
      value.textContent = format(row.value) + (row.suffix || "");
      animateAttr(value, "opacity", 0, 1, 380, 300 + index * 26);
    });
  }

  /* ------------------------------------------------------------- line/area */

  function lineChart(container, series, options) {
    const opts = options || {};
    const usable = (series || []).filter((s) => s.points && s.points.length);
    if (!usable.length) return empty(container, opts.emptyMessage);

    const height = opts.height || 260;
    const padding = { top: 18, right: 18, bottom: 34, left: 46 };
    const view = prepare(container, height);
    const plotWidth = Math.max(view.width - padding.left - padding.right, 40);
    const plotHeight = height - padding.top - padding.bottom;

    const labels = usable[0].points.map((p) => p.period);
    let max = 0;
    usable.forEach((s) => s.points.forEach((p) => (max = Math.max(max, p.value))));
    max = niceCeil(max || 1);

    const stepX = usable[0].points.length > 1 ? plotWidth / (usable[0].points.length - 1) : 0;
    const xAt = (i) => padding.left + (stepX ? i * stepX : plotWidth / 2);
    const yAt = (v) => padding.top + plotHeight - (v / max) * plotHeight;

    // Gridlines + y axis
    for (let tick = 0; tick <= 4; tick += 1) {
      const value = (max / 4) * tick;
      const y = yAt(value);
      el(
        "line",
        { class: "chart__grid-line", x1: padding.left, x2: view.width - padding.right, y1: y, y2: y },
        view.svg
      );
      el(
        "text",
        { class: "chart__axis-label", x: padding.left - 9, y: y + 4, "text-anchor": "end" },
        view.svg
      ).textContent = opts.formatY ? opts.formatY(value) : formatCompact(value);
    }

    // X axis labels - thinned so they never collide
    const maxTicks = Math.max(Math.floor(plotWidth / 76), 2);
    const stride = Math.ceil(labels.length / maxTicks);
    labels.forEach(function (label, index) {
      if (index % stride !== 0 && index !== labels.length - 1) return;
      el(
        "text",
        {
          class: "chart__axis-label",
          x: xAt(index),
          y: height - 12,
          "text-anchor": "middle",
        },
        view.svg
      ).textContent = opts.formatX ? opts.formatX(label) : formatDate(label);
    });

    usable.forEach(function (s, seriesIndex) {
      const color = s.color || seriesColor(seriesIndex);
      const points = s.points.map((p, i) => [xAt(i), yAt(p.value)]);
      const path = points.map((p, i) => (i ? "L" : "M") + p[0] + " " + p[1]).join(" ");

      if (opts.area && usable.length === 1) {
        const gradientId = "area-fill-" + Math.random().toString(36).slice(2, 9);
        const defs = el("defs", {}, view.svg);
        const gradient = el(
          "linearGradient",
          { id: gradientId, x1: 0, y1: 0, x2: 0, y2: 1 },
          defs
        );
        el("stop", { offset: "0%", "stop-color": color, "stop-opacity": 0.26 }, gradient);
        el("stop", { offset: "100%", "stop-color": color, "stop-opacity": 0 }, gradient);
        const base = padding.top + plotHeight;
        el(
          "path",
          {
            d: `${path} L ${points[points.length - 1][0]} ${base} L ${points[0][0]} ${base} Z`,
            fill: `url(#${gradientId})`,
          },
          view.svg
        );
      }

      const line = el(
        "path",
        {
          d: path,
          fill: "none",
          stroke: color,
          "stroke-width": 2.2,
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
        },
        view.svg
      );

      // Draw-on animation via stroke dash offset
      const length = line.getTotalLength ? line.getTotalLength() : 0;
      if (length && !prefersReducedMotion()) {
        line.setAttribute("stroke-dasharray", String(length));
        animateAttr(line, "stroke-dashoffset", length, 0, 760, seriesIndex * 90);
      }

      points.forEach(function (point, index) {
        const dot = el(
          "circle",
          {
            cx: point[0],
            cy: point[1],
            r: 3.4,
            fill: "var(--surface)",
            stroke: color,
            "stroke-width": 2,
            opacity: 0,
          },
          view.svg
        );
        animateAttr(dot, "opacity", 0, 1, 300, 500 + seriesIndex * 90 + index * 18);
        const value = s.points[index].value;
        attachTooltip(
          dot,
          `${s.label ? s.label + " - " : ""}${formatDate(s.points[index].period)}: ${
            opts.formatY ? opts.formatY(value) : value
          }`
        );
      });
    });

    if (opts.legend && usable.length > 1) {
      legend(
        container,
        usable.map((s, i) => ({ label: s.label, color: s.color || seriesColor(i) }))
      );
    }
  }

  /* ------------------------------------------------------------- histogram */

  function histogram(container, bins, options) {
    const opts = options || {};
    if (!bins || !bins.length) return empty(container, opts.emptyMessage);

    const height = opts.height || 260;
    const padding = { top: 18, right: 14, bottom: 34, left: 46 };
    const view = prepare(container, height);
    const plotWidth = Math.max(view.width - padding.left - padding.right, 40);
    const plotHeight = height - padding.top - padding.bottom;
    const max = niceCeil(Math.max.apply(null, bins.map((b) => b.count)) || 1);
    const slot = plotWidth / bins.length;
    const barWidth = Math.max(slot - 3, 1);

    for (let tick = 0; tick <= 4; tick += 1) {
      const value = (max / 4) * tick;
      const y = padding.top + plotHeight - (value / max) * plotHeight;
      el(
        "line",
        { class: "chart__grid-line", x1: padding.left, x2: view.width - padding.right, y1: y, y2: y },
        view.svg
      );
      el(
        "text",
        { class: "chart__axis-label", x: padding.left - 9, y: y + 4, "text-anchor": "end" },
        view.svg
      ).textContent = formatCompact(value);
    }

    bins.forEach(function (bin, index) {
      const barHeight = (bin.count / max) * plotHeight;
      const x = padding.left + index * slot + (slot - barWidth) / 2;
      const y = padding.top + plotHeight - barHeight;
      const bar = el(
        "rect",
        {
          class: "chart__bar",
          x: x,
          width: barWidth,
          y: padding.top + plotHeight,
          height: 0,
          rx: Math.min(3, barWidth / 2),
          fill: seriesColor(0),
        },
        view.svg
      );
      animateAttr(bar, "height", 0, barHeight, 520, index * 14);
      animateAttr(bar, "y", padding.top + plotHeight, y, 520, index * 14);
      attachTooltip(
        bar,
        `${formatMoney(bin.lower)}–${formatMoney(bin.upper)}: ${bin.count} postings`
      );
    });

    const first = bins[0];
    const last = bins[bins.length - 1];
    el(
      "text",
      { class: "chart__axis-label", x: padding.left, y: height - 12, "text-anchor": "start" },
      view.svg
    ).textContent = formatMoney(first.lower);
    el(
      "text",
      {
        class: "chart__axis-label",
        x: view.width - padding.right,
        y: height - 12,
        "text-anchor": "end",
      },
      view.svg
    ).textContent = formatMoney(last.upper);
  }

  /* -------------------------------------------------------------- box plot */

  function boxPlot(container, groups, options) {
    const opts = options || {};
    if (!groups || !groups.length) return empty(container, opts.emptyMessage);

    const rowHeight = 46;
    const labelWidth = opts.labelWidth || 150;
    const padding = { top: 12, right: 20, bottom: 30 };
    const height = padding.top + padding.bottom + groups.length * rowHeight;
    const view = prepare(container, height);
    const plotWidth = Math.max(view.width - labelWidth - padding.right, 60);

    let min = Infinity;
    let max = 0;
    groups.forEach(function (group) {
      min = Math.min(min, group.min);
      max = Math.max(max, group.max);
    });
    // Anchor the axis at zero-ish so box widths stay comparable across groups.
    min = Math.max(0, Math.floor((min * 0.92) / 5000) * 5000);
    max = niceCeil(max);
    const span = max - min || 1;
    const xAt = (value) => labelWidth + ((value - min) / span) * plotWidth;

    for (let tick = 0; tick <= 4; tick += 1) {
      const value = min + (span / 4) * tick;
      const x = xAt(value);
      el(
        "line",
        {
          class: "chart__grid-line",
          x1: x,
          x2: x,
          y1: padding.top,
          y2: height - padding.bottom,
        },
        view.svg
      );
      el(
        "text",
        { class: "chart__axis-label", x: x, y: height - 10, "text-anchor": "middle" },
        view.svg
      ).textContent = formatMoney(value);
    }

    groups.forEach(function (group, index) {
      const centre = padding.top + index * rowHeight + rowHeight / 2;
      const color = seriesColor(index);
      const boxTop = centre - 9;
      const boxHeight = 18;
      const x1 = xAt(group.q1);
      const x3 = xAt(group.q3);
      const boxWidth = Math.max(x3 - x1, 2);

      el(
        "text",
        {
          class: "chart__axis-label",
          x: labelWidth - 10,
          y: centre + 4,
          "text-anchor": "end",
        },
        view.svg
      ).textContent = truncate(group.label, 20);

      // Whiskers
      const whisker = el(
        "line",
        {
          x1: xAt(group.min),
          x2: xAt(group.max),
          y1: centre,
          y2: centre,
          stroke: color,
          "stroke-width": 1.5,
          opacity: 0.45,
        },
        view.svg
      );
      animateAttr(whisker, "opacity", 0, 0.45, 400, index * 30);
      [group.min, group.max].forEach(function (value) {
        el(
          "line",
          {
            x1: xAt(value),
            x2: xAt(value),
            y1: centre - 6,
            y2: centre + 6,
            stroke: color,
            "stroke-width": 1.5,
            opacity: 0.45,
          },
          view.svg
        );
      });

      // Interquartile box
      const box = el(
        "rect",
        {
          class: "chart__bar",
          x: x1,
          y: boxTop,
          height: boxHeight,
          rx: 5,
          fill: color,
          "fill-opacity": 0.24,
          stroke: color,
          "stroke-width": 1.5,
          width: 0,
        },
        view.svg
      );
      animateAttr(box, "width", 0, boxWidth, 560, index * 30);

      // Median
      const median = el(
        "line",
        {
          x1: xAt(group.median),
          x2: xAt(group.median),
          y1: boxTop,
          y2: boxTop + boxHeight,
          stroke: color,
          "stroke-width": 2.6,
          "stroke-linecap": "round",
          opacity: 0,
        },
        view.svg
      );
      animateAttr(median, "opacity", 0, 1, 340, 260 + index * 30);

      attachTooltip(
        box,
        `${group.label} - median ${formatMoney(group.median)} · ` +
          `IQR ${formatMoney(group.q1)}–${formatMoney(group.q3)} · n=${group.count}`
      );
    });
  }

  /* ---------------------------------------------------------------- export */

  global.Charts = {
    horizontalBar: horizontalBar,
    lineChart: lineChart,
    histogram: histogram,
    boxPlot: boxPlot,
    empty: empty,
    formatMoney: formatMoney,
    formatCompact: formatCompact,
    formatDate: formatDate,
    seriesColor: seriesColor,
  };
})(window);
