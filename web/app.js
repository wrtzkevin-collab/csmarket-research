/**
 * Renders the research page from a document produced by
 * `csmarket analyze-case --export-web`.
 *
 * The page has no fabricated numbers of its own. When the data file is absent
 * it says so and renders nothing rather than falling back to invented figures
 * that would look identical to a real result.
 */

const DATA_URL = "results.json";

const state = { data: null, sort: "gross_return_ratio", error: null };

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2
});
const percent = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1
});

function formatMoney(value, currency) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  if (!currency || currency === "USD") return money.format(value);
  return `${value.toFixed(2)} ${currency}`;
}

function formatPercent(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return percent.format(value);
}

function formatTime(iso) {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "—";
  return (
    new Intl.DateTimeFormat("en-GB", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "UTC"
    }).format(parsed) + " UTC"
  );
}

function formatDuration(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) {
    return null;
  }
  if (seconds < 90) return `${Math.round(seconds)}s crawl`;
  return `${Math.round(seconds / 60)} min crawl`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      })[character]
  );
}

async function loadData() {
  const response = await fetch(DATA_URL, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const payload = await response.json();
  if (!payload || !Array.isArray(payload.cases) || payload.cases.length === 0) {
    throw new Error("the data file contains no cases");
  }
  return payload;
}

function metric(label, value, className = "") {
  return `
    <div class="result-metric ${className}">
      <span>${escapeHtml(label)}</span>
      <strong>${value}</strong>
    </div>`;
}

/** The venue a case is ranked and summarised by: the most complete one. */
function primaryEntry(item) {
  return [...item.sources].sort((a, b) => b.coverage - a.coverage)[0];
}

function sourcePanel(entry) {
  const coverageState = entry.coverage >= 0.95 ? "coverage-good" : "coverage-review";
  const lossLabel = entry.loss_probability_is_lower_bound
    ? "Loss probability ≥"
    : "Loss probability";
  const span = formatDuration(entry.observation_span_seconds);
  const observed = [formatTime(entry.observed_at), span].filter(Boolean).join(" · ");

  return `
    <div class="source-panel">
      <div class="source-panel-head">
        <div>
          <h4>${escapeHtml(entry.source_label)}</h4>
          <p>${escapeHtml(entry.price_type)} · ${escapeHtml(observed)}</p>
        </div>
        <span class="coverage-badge ${coverageState}">
          ${formatPercent(entry.coverage)} coverage
        </span>
      </div>
      <div class="result-grid">
        ${metric("Gross return ratio", formatPercent(entry.gross_return_ratio), "primary-metric")}
        ${metric("Expected net ROI", formatPercent(entry.expected_net_roi), "negative-metric")}
        ${metric(lossLabel, formatPercent(entry.loss_probability))}
        ${metric("Gross EV", formatMoney(entry.gross_expected_value, entry.currency))}
      </div>
      <div class="coverage-row">
        <span>Outcome coverage</span>
        <div class="coverage-track" aria-hidden="true">
          <span style="width:${Math.max(0, Math.min(1, entry.coverage)) * 100}%"></span>
        </div>
        <span>${entry.priced_outcomes} / ${entry.total_outcomes} priced</span>
      </div>
    </div>`;
}

function wearNote(entry) {
  const observed = entry?.wear_basis?.observed_volume;
  if (typeof observed !== "number") return "";
  return `<p class="wear-note">Wear grades: ${formatPercent(observed)} of probability
    mass weighted by observed sales volume, the remainder by a uniform float
    assumption.</p>`;
}

function caseCard(item, rank) {
  const lead = primaryEntry(item);
  const readiness = item.sources.every((entry) => entry.publication_ready)
    ? ""
    : `<p class="wear-note">Not publication ready: at least one venue is missing a
       price, so the estimate is a lower bound.</p>`;

  return `
    <article class="case-card">
      <div class="case-title">
        <span class="rank">${String(rank + 1).padStart(2, "0")}</span>
        <div>
          <h3>${escapeHtml(item.name)}</h3>
          <p>Opening cost ${formatMoney(lead.opening_cost, lead.currency)} ·
             case ${formatMoney(lead.case_price, lead.currency)} +
             key ${formatMoney(lead.key_price, lead.currency)}</p>
        </div>
      </div>
      <div class="source-panels">
        ${item.sources.map(sourcePanel).join("")}
      </div>
      ${wearNote(lead)}
      ${readiness}
    </article>`;
}

function renderCases() {
  const cases = [...state.data.cases].sort((a, b) => {
    const left = primaryEntry(a)[state.sort];
    const right = primaryEntry(b)[state.sort];
    if (state.sort === "loss_probability") return left - right;
    return right - left;
  });
  document.querySelector("#case-list").innerHTML = cases.map(caseCard).join("");
}

function sourceCard(label, source, detail) {
  const link = source.url
    ? `<a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">
         View source documentation <span aria-hidden="true">↗</span></a>`
    : "";
  return `
    <article>
      <span>${escapeHtml(label)}</span>
      <h3>${escapeHtml(source.name)}</h3>
      <p>${escapeHtml(detail)}</p>
      ${link}
    </article>`;
}

function renderPage() {
  const { dataset, assumptions, sources, schema_version: schemaVersion } = state.data;

  document.querySelector("#snapshot-strip").innerHTML = `
    <div><span>Dataset</span><strong>${escapeHtml(dataset.label)}</strong></div>
    <div><span>Observed at</span><strong>${formatTime(dataset.observed_at)}</strong></div>
    <div><span>Currency</span><strong>${escapeHtml(dataset.currency)}</strong></div>
    <div><span>Cases</span><strong>${dataset.case_count}</strong></div>`;

  document.querySelector("#assumption-list").innerHTML = assumptions
    .map(
      (text, index) =>
        `<li><span>${String(index + 1).padStart(2, "0")}</span><p>${escapeHtml(text)}</p></li>`
    )
    .join("");

  document.querySelector("#source-list").innerHTML =
    sources.map((source) => sourceCard("Market prices", source, source.basis)).join("") +
    sourceCard(
      "Drop probabilities",
      state.data.probability_source,
      state.data.probability_source.basis
    ) +
    sourceCard("Item catalogue", state.data.catalog_source, state.data.catalog_source.basis);

  document.querySelector("#schema-version").textContent = `Data schema v${schemaVersion}`;
  renderCases();
}

function renderError(error) {
  document.querySelector("#case-list").innerHTML = `
    <article class="case-card">
      <h3>No snapshot published</h3>
      <p>This page renders only calculated results, and
      <code>${DATA_URL}</code> could not be loaded (${escapeHtml(error.message)}).</p>
      <p>Generate one with
      <code>python -m csmarket analyze-case "Kilowatt Case" --export-web</code>
      and commit the file.</p>
    </article>`;
  document.querySelector("#schema-version").textContent = "No data file";
}

const sortSelect = document.querySelector("#sort-select");
if (sortSelect) {
  sortSelect.addEventListener("change", (event) => {
    state.sort = event.target.value;
    if (state.data) renderCases();
  });
}

loadData()
  .then((data) => {
    state.data = data;
    renderPage();
  })
  .catch((error) => {
    state.error = error;
    renderError(error);
  });
