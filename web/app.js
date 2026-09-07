/**
 * Renders results.json, produced by `csmarket analyze-case --export-web`.
 *
 * The page has no numbers of its own. With no data file it says so, rather
 * than falling back to invented figures that would look like real ones.
 */

const DATA_URL = "results.json";

const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

function money(value, currency) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency || "USD",
      minimumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

function pct(value, { sign = false, digits = 1 } = {}) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const formatted = (value * 100).toFixed(digits);
  return sign && value > 0 ? `+${formatted}%` : `${formatted}%`;
}

function when(iso) {
  if (!iso) return "unknown";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "unknown";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(parsed);
}

const PRICE_BASIS = {
  lowest_listing: "cheapest listing",
  sales_median_30_days: "median sale, 30d",
  sales_median_7_days: "median sale, 7d",
  sales_median_24_hours: "median sale, 24h",
};

function venueLabel(entry) {
  const basis = PRICE_BASIS[entry.price_type] || entry.price_type;
  return `${escapeHtml(entry.source_label)}<small>${escapeHtml(basis)}</small>`;
}

function row(entry, caseName, position) {
  const partial = entry.coverage < 1 ? " partial" : "";
  const roi = entry.expected_net_roi;
  return `
    <tr class="${position}">
      <td class="l case-name">${caseName ? escapeHtml(caseName) : ""}</td>
      <td class="l venue">${venueLabel(entry)}</td>
      <td>${money(entry.opening_cost, entry.currency)}</td>
      <td>${money(entry.net_expected_value, entry.currency)}</td>
      <td class="big${roi < 0 ? " loss" : ""}">${pct(roi, { sign: true })}</td>
      <td class="${partial}">${pct(entry.loss_probability)}</td>
      <td>${pct(entry.coverage, { digits: entry.coverage === 1 ? 0 : 1 })}</td>
    </tr>`;
}

function renderRows(data) {
  const html = data.cases
    .map((item) =>
      item.sources
        .map((entry, index) =>
          row(
            entry,
            index === 0 ? item.name : "",
            [
              index === 0 ? "case-first" : "",
              index === item.sources.length - 1 ? "case-last" : "",
            ]
              .filter(Boolean)
              .join(" "),
          ),
        )
        .join(""),
    )
    .join("");
  document.querySelector("#rows").innerHTML = html;

  const anyPartial = data.cases.some((item) =>
    item.sources.some((entry) => entry.coverage < 1),
  );
  document.querySelector("#table-note").textContent = anyPartial
    ? "* Some outcomes had no price on that venue, so the real chance of losing is at least this high."
    : "";
}

function sourceRow(name, detail, tag) {
  return `
    <tr>
      <td>${escapeHtml(name)}${tag ? `<span class="tag">${escapeHtml(tag)}</span>` : ""}</td>
      <td>${detail}</td>
    </tr>`;
}

function link(url, text) {
  return url
    ? `<a href="${escapeHtml(url)}">${escapeHtml(text)}</a>`
    : escapeHtml(text);
}

function renderSources(data) {
  const rows = [];

  for (const source of data.sources) {
    rows.push(
      sourceRow(
        source.name,
        `${escapeHtml(source.basis)} ${link(source.url, "↗")}`,
        "prices",
      ),
    );
  }

  rows.push(
    sourceRow(
      data.probability_source.name,
      `${escapeHtml(data.probability_source.basis)} ${link(data.probability_source.url, "↗")}`,
      "official",
    ),
  );

  rows.push(
    sourceRow(
      data.catalog_source.name,
      `${escapeHtml(data.catalog_source.basis)} Pinned at
       <code>${escapeHtml((data.catalog_source.commit || "").slice(0, 7))}</code>.
       ${link(data.catalog_source.url, "↗")}`,
      "community",
    ),
  );

  rows.push(
    sourceRow(
      "Key price",
      "Not observed from any market. A configured constant, and it is most of " +
        "the cost to open, so check it before trusting a return.",
      "assumed",
    ),
  );

  document.querySelector("#sources").innerHTML = rows.join("");
}

function renderMeta(data) {
  const venues = data.sources.map((source) => source.name).join(" and ");
  document.querySelector("#meta").textContent =
    `Prices from ${venues}, observed ${when(data.dataset.observed_at)} UTC, ` +
    `in ${data.dataset.currency}. ${data.dataset.case_count} case` +
    `${data.dataset.case_count === 1 ? "" : "s"}.`;
  document.querySelector("#version").textContent =
    `Data schema v${data.schema_version} · generated ${when(data.dataset.generated_at)} UTC`;
}

function renderError(error) {
  document.querySelector("#rows").innerHTML = `
    <tr><td colspan="7" class="note">
      No snapshot published yet — <code>${DATA_URL}</code> could not be loaded
      (${escapeHtml(error.message)}). Generate one with
      <code>python -m csmarket analyze-case "Kilowatt Case" --export-web</code>.
    </td></tr>`;
  document.querySelector("#sources").innerHTML = "";
}

fetch(DATA_URL, { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((data) => {
    if (!data || !Array.isArray(data.cases) || data.cases.length === 0) {
      throw new Error("no cases in the data file");
    }
    renderMeta(data);
    renderRows(data);
    renderSources(data);
  })
  .catch(renderError);
