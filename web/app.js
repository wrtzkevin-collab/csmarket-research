const FALLBACK_DATA = {
  schema_version: "1.0",
  dataset: {
    label: "Demonstration snapshot",
    mode: "sample",
    currency: "USD",
    observed_at: "2026-09-06T12:00:00Z",
    generated_at: "2026-09-06T12:05:00Z",
    price_source: {
      name: "Synthetic price fixtures",
      url: "https://docs.skinport.com/items",
      basis: "Illustrative values only; the production adapter targets the documented Skinport API"
    },
    probability_source: {
      name: "Counter-Strike official rarity disclosure",
      url: "https://www.csgo.com.cn/news/gamebroad/20170911/206155.html"
    }
  },
  cases: [
    { name: "Illustrative Case A", case_price: 0.24, key_price: 2.49, opening_cost: 2.73, gross_expected_value: 1.78, net_expected_value: 1.54, gross_return_ratio: 0.652, expected_net_roi: -0.436, loss_probability: 0.824, coverage: 0.972, priced_outcomes: 141, total_outcomes: 145, status: "high coverage" },
    { name: "Illustrative Case B", case_price: 0.31, key_price: 2.49, opening_cost: 2.8, gross_expected_value: 1.68, net_expected_value: 1.46, gross_return_ratio: 0.6, expected_net_roi: -0.479, loss_probability: 0.831, coverage: 0.954, priced_outcomes: 146, total_outcomes: 153, status: "review gaps" },
    { name: "Illustrative Case C", case_price: 0.92, key_price: 2.49, opening_cost: 3.41, gross_expected_value: 1.86, net_expected_value: 1.61, gross_return_ratio: 0.545, expected_net_roi: -0.528, loss_probability: 0.846, coverage: 0.938, priced_outcomes: 136, total_outcomes: 145, status: "review gaps" }
  ],
  assumptions: [
    "The opening cost equals the case price plus one key; deposit and currency-conversion costs are excluded.",
    "Net expected value applies a 13% illustrative seller fee to outcomes. Actual fees depend on the venue and account.",
    "Outcomes inside each rarity tier are treated as equally likely. Wear, pattern and StatTrak distributions remain model assumptions unless separately sourced.",
    "Missing prices are excluded and reported through coverage. Results below 95% coverage should not be compared as precise estimates.",
    "Market listings are observations, not guaranteed sale prices. This sample is for interface testing and is not current market data."
  ]
};

const state = { data: null, sort: "gross_return_ratio", loadedFromFile: false };
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
const percent = new Intl.NumberFormat("en-US", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 });

async function loadData() {
  try {
    const response = await fetch("sample-result.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.loadedFromFile = true;
    return await response.json();
  } catch (error) {
    console.info("Using the embedded sample because the JSON file could not be fetched.", error);
    return FALLBACK_DATA;
  }
}

function formatTime(iso) {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC"
  }).format(new Date(iso)) + " UTC";
}

function metric(label, value, className = "") {
  return `
    <div class="result-metric ${className}">
      <span>${label}</span>
      <strong>${value}</strong>
    </div>`;
}

function caseCard(item, rank) {
  const coverageState = item.coverage >= 0.95 ? "coverage-good" : "coverage-review";
  return `
    <article class="case-card">
      <div class="case-title">
        <span class="rank">${String(rank + 1).padStart(2, "0")}</span>
        <div>
          <h3>${item.name}</h3>
          <p>Opening cost ${money.format(item.opening_cost)} · case ${money.format(item.case_price)} + key ${money.format(item.key_price)}</p>
        </div>
        <span class="coverage-badge ${coverageState}">${percent.format(item.coverage)} coverage</span>
      </div>
      <div class="result-grid">
        ${metric("Gross return ratio", percent.format(item.gross_return_ratio), "primary-metric")}
        ${metric("Expected net ROI", percent.format(item.expected_net_roi), "negative-metric")}
        ${metric(item.coverage < 1 ? "Observed loss probability ≥" : "Loss probability", percent.format(item.loss_probability))}
        ${metric("Gross EV", money.format(item.gross_expected_value))}
      </div>
      <div class="coverage-row">
        <span>Outcome coverage</span>
        <div class="coverage-track" aria-hidden="true"><span style="width:${item.coverage * 100}%"></span></div>
        <span>${item.priced_outcomes} / ${item.total_outcomes} priced</span>
      </div>
    </article>`;
}

function renderCases() {
  const cases = [...state.data.cases].sort((a, b) => {
    if (state.sort === "loss_probability") return a[state.sort] - b[state.sort];
    return b[state.sort] - a[state.sort];
  });
  document.querySelector("#case-list").innerHTML = cases.map(caseCard).join("");
}

function sourceCard(label, source, detail) {
  return `
    <article>
      <span>${label}</span>
      <h3>${source.name}</h3>
      <p>${detail}</p>
      <a href="${source.url}" target="_blank" rel="noreferrer">View source documentation <span aria-hidden="true">↗</span></a>
    </article>`;
}

function renderPage() {
  const { dataset, assumptions, schema_version: schemaVersion } = state.data;
  document.querySelector("#snapshot-strip").innerHTML = `
    <div><span>Dataset</span><strong>${dataset.label}</strong></div>
    <div><span>Observed at</span><strong>${formatTime(dataset.observed_at)}</strong></div>
    <div><span>Currency</span><strong>${dataset.currency}</strong></div>
    <div><span>Data mode</span><strong>${dataset.mode === "sample" ? "Sample · not live" : dataset.mode}</strong></div>`;

  document.querySelector("#assumption-list").innerHTML = assumptions
    .map((text, index) => `<li><span>${String(index + 1).padStart(2, "0")}</span><p>${text}</p></li>`)
    .join("");

  document.querySelector("#source-list").innerHTML =
    sourceCard("Market prices", dataset.price_source, dataset.price_source.basis) +
    sourceCard("Drop probabilities", dataset.probability_source, "Official rarity-tier probability disclosure; applicability must be checked per case type.");

  document.querySelector("#schema-version").textContent = `Sample schema v${schemaVersion}`;
  renderCases();
}

document.querySelector("#sort-select").addEventListener("change", (event) => {
  state.sort = event.target.value;
  renderCases();
});

loadData().then((data) => {
  state.data = data;
  renderPage();
});
