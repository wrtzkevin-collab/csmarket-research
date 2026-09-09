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
    thinHeading: (count) =>
      `${count} cases held back — either under ${Math.round(COVERAGE_BAR * 100)}% priced, or most of the value rests on almost-empty listings, so the return is not comparable with the ones above`,
    thinFootnote: (count) =>
      `† ${count} figures rest mostly on items with fewer than a handful of offers, where one seller's asking price sets the whole result.`,
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
      listing_min: "最低挂单价",
      lowest_listing: "最低挂单价",
      sales_median_30_days: "近 30 天成交中位数",
      sales_median_7_days: "近 7 天成交中位数",
      sales_median_24_hours: "近 24 小时成交中位数",
    },
    partial:
      "* 这个市场上有些东西查不到价，所以实际亏本概率只会比这更高。",
    thinHeading: (count) =>
      `以下 ${count} 个箱子先放一边——要么已定价不足 ${Math.round(COVERAGE_BAR * 100)}%，要么大部分价值压在几乎没人挂的东西上，回本率没法跟上面的比`,
    thinFootnote: (count) =>
      `† 有 ${count} 个数字主要立在挂单数只有个位数的物品上，等于一个卖家的报价决定了整个结果。`,
    assumed: (share) =>
      `有 ${share} 的概率因为挂单太少、统计不出磨损分布，用了平均分的假设。`,
    meta: (venues, when, currency, count) =>
      `价格取自 ${venues}，${when} UTC 抓的，按 ${currency} 计价，一共 ${count} 个箱子。`,
    version: (schema, when) => `数据格式 v${schema} · ${when} UTC 生成`,
    tagPrices: "价格",
    tagOfficial: "官方",
    tagCommunity: "社区",
    tagAssumed: "拍的",
    keyPrice: "钥匙价格",
    keyPriceNote:
      "全页唯一一个没有市场报价的数字。钥匙不能交易，所以这里填的是人工配的常量，而它占了开箱成本一大半——信这个收益率之前，建议自己核一下。",
    pinned: (commit) => `锁在 <code>${commit}</code> 这一版。`,
    empty: (url, error) => `还没发布快照——<code>${url}</code> 加载失败（${error}）。`,
    noData: "没有数据文件",
  },
};

const T = STRINGS[LOCALE] || STRINGS.en;

/**
 * Below this share of priced probability a case's return is not comparable to
 * a fully measured one: it is an upper bound on whatever part we could see.
 * Sorting the table by return without this split puts the least-measured cases
 * at the top, which reads as "best case to open" and is the opposite of true.
 */
const COVERAGE_BAR = 0.95;

/**
 * Above this share of expected value resting on near-empty listings, the return
 * is one seller's asking price rather than a market level. Coverage cannot
 * catch it: a case can be 100% priced and still get most of its value from two
 * lone listings.
 */
const THIN_BAR = 1 / 3;

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
      <td class="big${entry.thin_ev_share > THIN_BAR ? " thin" : ""}">${pct(entry.net_return_ratio, { digits: 0 })}</td>
      <td class="${roi < 0 ? "loss" : ""}">${pct(roi, { sign: true })}</td>
      <td class="${partial}">${pct(entry.loss_probability)}</td>
      <td>${coveragePct(entry.coverage)}</td>
    </tr>`;
}

function bestCoverage(item) {
  return Math.max(...item.sources.map((entry) => entry.coverage));
}

/** Rank and summarise a case by whichever venue could price the most of it. */
function primaryEntry(item) {
  return [...item.sources].sort((a, b) => b.coverage - a.coverage)[0];
}

function thinShare(item) {
  const share = primaryEntry(item).thin_ev_share;
  return typeof share === "number" ? share : 0;
}

function isComparable(item) {
  return bestCoverage(item) >= COVERAGE_BAR && thinShare(item) <= THIN_BAR;
}

function leadReturn(item) {
  return primaryEntry(item).net_return_ratio ?? -Infinity;
}

function renderCaseRows(cases) {
  return cases
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
}

function renderRows(data) {
  const sorted = [...data.cases].sort((a, b) => leadReturn(b) - leadReturn(a));
  const measured = sorted.filter(isComparable);
  const held = sorted.filter((item) => !isComparable(item));

  let html = renderCaseRows(measured);
  if (held.length) {
    html += `<tr class="divider"><td colspan="8">${T.thinHeading(held.length)}</td></tr>`;
    html += renderCaseRows(held);
  }
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

  const thinCount = data.cases.reduce(
    (count, item) =>
      count + item.sources.filter((e) => e.thin_ev_share > THIN_BAR).length,
    0,
  );
  if (thinCount) {
    notes.push(T.thinFootnote(thinCount));
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
    <tr><td colspan="8" class="note">
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
