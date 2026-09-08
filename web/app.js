/**
 * Renders results.json, produced by `csmarket analyze-case --export-web`.
 *
 * The page has no numbers of its own. With no data file it says so, rather
 * than falling back to invented figures that would look like real ones.
 */

const CONFIG = window.PAGE_CONFIG || { data: "results.json", locale: "en" };
const DATA_URL = CONFIG.data;
const LOCALE = CONFIG.locale;

/**
 * Page chrome is written in each page's HTML; only strings the script builds
 * live here. Case names are not translated at all -- the localized name comes
 * from the catalogue, which carries the game's own official strings.
 */
const STRINGS = {
  en: {
    numberLocale: "en-US",
    dateLocale: "en-GB",
    unknown: "unknown",
    basis: {
      listing_min: "cheapest listing",
      lowest_listing: "cheapest listing",
      sales_median_30_days: "median sale, 30d",
      sales_median_7_days: "median sale, 7d",
      sales_median_24_hours: "median sale, 24h",
    },
    partial:
      "* Some outcomes had no price on that venue, so the real chance of losing is at least this high.",
    assumed: (share) =>
      `Up to ${share} of probability had too few listings to measure a wear split, and used an even spread instead.`,
    meta: (venues, when, currency, count) =>
      `Prices from ${venues}, observed ${when} UTC, in ${currency}. ${count} case${count === 1 ? "" : "s"}.`,
    version: (schema, when) =>
      `Data schema v${schema} · generated ${when} UTC`,
    tagPrices: "prices",
    tagOfficial: "official",
    tagCommunity: "community",
    tagAssumed: "assumed",
    keyPrice: "Key price",
    keyPriceNote:
      "Not observed from any market. A configured constant, and it is most of the cost to open, so check it before trusting a return.",
    pinned: (commit) => `Pinned at <code>${commit}</code>.`,
    empty: (url, error) =>
      `No snapshot published yet — <code>${url}</code> could not be loaded (${error}).`,
    noData: "No data file",
  },
  "zh-CN": {
    numberLocale: "zh-CN",
    dateLocale: "zh-CN",
    unknown: "未知",
    basis: {
      listing_min: "最低在售价",
      lowest_listing: "最低在售价",
      sales_median_30_days: "近 30 天成交中位数",
      sales_median_7_days: "近 7 天成交中位数",
      sales_median_24_hours: "近 24 小时成交中位数",
    },
    partial:
      "* 该市场上有部分结果查不到价格，所以真实亏损概率不低于此值。",
    assumed: (share) =>
      `最多有 ${share} 的概率因在售数量太少无法测量磨损分布，改用了均分假设。`,
    meta: (venues, when, currency, count) =>
      `价格来自 ${venues}，观测于 ${when}（UTC），币种 ${currency}，共 ${count} 个武器箱。`,
    version: (schema, when) => `数据格式 v${schema} · 生成于 ${when}（UTC）`,
    tagPrices: "价格",
    tagOfficial: "官方",
    tagCommunity: "社区维护",
    tagAssumed: "假设值",
    keyPrice: "钥匙价格",
    keyPriceNote:
      "没有任何市场报价。钥匙不可交易，这是一个人工配置的常量，而它占了开箱成本的大部分，采信收益率前请自行核实。",
    pinned: (commit) => `已锁定在提交 <code>${commit}</code>。`,
    empty: (url, error) =>
      `尚未发布快照 —— 无法加载 <code>${url}</code>（${error}）。`,
    noData: "无数据文件",
  },
};

const T = STRINGS[LOCALE] || STRINGS.en;

const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

function money(value, currency) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  try {
    return new Intl.NumberFormat(T.numberLocale, {
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

/**
 * Coverage below 1 must never round up to "100%": the whole point of the
 * figure is to say whether anything was missing, and a 100% next to a footnote
 * saying some outcomes were unpriced reads as a bug rather than as a caveat.
 */
function coveragePct(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  if (value >= 1) return "100%";
  const digits = 1;
  const factor = 10 ** (digits + 2);
  const floored = Math.floor(value * factor) / factor;
  return `${Math.min(floored * 100, 99.9).toFixed(digits)}%`;
}

function when(iso) {
  if (!iso) return T.unknown;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return T.unknown;
  return new Intl.DateTimeFormat(T.dateLocale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(parsed);
}

function venueLabel(entry) {
  const basis = T.basis[entry.price_type] || entry.price_type;
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
      <td>${coveragePct(entry.coverage)}</td>
    </tr>`;
}

function renderRows(data) {
  const html = data.cases
    .map((item) =>
      item.sources
        .map((entry, index) =>
          row(
            entry,
            index === 0 ? item.display_name || item.name : "",
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

  const notes = [];
  if (data.cases.some((item) => item.sources.some((e) => e.coverage < 1))) {
    notes.push(T.partial);
  }

  // Only worth the reader's attention when a material share of the estimate
  // rests on the assumption rather than on a measurement.
  const assumed = Math.max(
    0,
    ...data.cases.flatMap((item) =>
      item.sources.map((e) => e.wear_basis?.uniform_fallback ?? 0),
    ),
  );
  if (assumed > 0.01) {
    notes.push(T.assumed(pct(assumed)));
  }
  document.querySelector("#table-note").textContent = notes.join(" ");
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
        T.tagPrices,
      ),
    );
  }

  rows.push(
    sourceRow(
      data.probability_source.name,
      `${escapeHtml(data.probability_source.basis)} ${link(data.probability_source.url, "↗")}`,
      T.tagOfficial,
    ),
  );

  rows.push(
    sourceRow(
      data.catalog_source.name,
      `${escapeHtml(data.catalog_source.basis)}
       ${T.pinned(escapeHtml((data.catalog_source.commit || "").slice(0, 7)))}
       ${link(data.catalog_source.url, "↗")}`,
      T.tagCommunity,
    ),
  );

  rows.push(
    sourceRow(
      T.keyPrice,
      T.keyPriceNote,
      T.tagAssumed,
    ),
  );

  document.querySelector("#sources").innerHTML = rows.join("");
}

function renderMeta(data) {
  // Two endpoints of one venue share its name; listing them both reads as
  // "Skinport and Skinport".
  const venues = [...new Set(data.sources.map((source) => source.name))].join(
    " and ",
  );
  document.querySelector("#meta").textContent = T.meta(
    venues,
    when(data.dataset.observed_at),
    data.dataset.currency,
    data.dataset.case_count,
  );
  document.querySelector("#version").textContent = T.version(
    data.schema_version,
    when(data.dataset.generated_at),
  );
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
