"use strict";

// Every value shown comes from cases.json, written by `muletrace demo build`.
// Text is inserted with textContent only, never as HTML.

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const pct = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 });
const int = new Intl.NumberFormat("en-US");
const buttons = new Map();

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function fact(label, value, tone) {
  return el("div", { class: "fact" },
    el("span", { class: "label" }, label),
    el("span", { class: `value ${tone || ""}` }, value));
}

function table(headers, rows, numeric = []) {
  const head = el("tr", {}, ...headers.map((h, i) => el("th", { class: numeric.includes(i) ? "num" : "" }, h)));
  const body = rows.map((row) => el("tr", {}, ...row.map((cell, i) =>
    el("td", { class: numeric.includes(i) ? "num" : (i === row.length - 1 ? "text" : "") }, cell))));
  return el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, ...body)));
}

function scoreSection(c) {
  const s = c.score;
  const truth = c.truth.confirmed_mule_within_horizon;
  return el("div", {},
    el("div", { class: "facts" },
      fact("Calibrated probability", `${pct.format(s.probability)}${s.probability_capped ? " (capped)" : ""}`),
      fact("Rank that day", `${int.format(c.rank)} of ${int.format(c.scored_accounts)}`),
      fact("Alerted at the budget", c.alerted_at_budget ? "Yes" : "No"),
      fact("Confirmed mule within 48 h", truth ? "Yes" : "No", truth ? "bad" : "good"),
      fact("Laundering inflow before the score", c.truth.already_active_at_as_of ? "Yes" : "No")),
    el("h3", {}, "What pushed the score up: top reason codes"),
    s.reasons.length
      ? table(["Feature", "Value", "Contribution"],
        s.reasons.map((r) => [r.feature, r.value === null ? "missing" : int.format(Math.round(r.value * 100) / 100), r.contribution.toFixed(4)]), [1, 2])
      : el("p", { class: "muted" }, "No feature pushed this score up."));
}

function evidenceSection(c) {
  const rows = c.evidence.transfers.map((t) => [
    t.tx_id, t.timestamp.replace("T", " ").slice(0, 16), t.direction, t.counterparty_id,
    usd.format(t.amount_usd), t.payment_format, t.description || "",
  ]);
  return el("div", {},
    el("h3", {}, "Evidence"),
    el("p", { class: "muted" },
      `Transfers of account ${c.account_id} from three days before the score to one day after it (at most the 25 largest, listed in time order).`),
    table(["tx", "Time", "Dir.", "Counterparty", "Amount", "Format", "Description (customer text)"], rows, [4]));
}

function traceSection(c) {
  if (!c.trace) return null;
  const t = c.trace;
  const intro = el("div", { class: "facts" },
    fact("Disputed transfer", `tx ${t.disputed_tx_id}`),
    fact("Disputed amount", usd.format(t.disputed_usd)),
    fact("Accounts reached", int.format(t.accounts_reached)),
    fact("Deepest hop", int.format(t.max_hop_reached)),
    fact("Still in reached accounts (upper bound)", usd.format(t.recoverable_usd)),
    fact("Left the trace", usd.format(t.left_trace_usd)));
  const hops = t.hops.length
    ? table(["Hop", "tx", "Time", "From", "To", "Tainted amount"],
      t.hops.map((h) => [h.hop, h.tx_id, String(h.timestamp).replace("T", " ").slice(0, 16), h.sender_id, h.receiver_id, usd.format(h.tainted_usd)]), [5])
    : el("p", { class: "muted" }, "The money had not moved on within the hop window: it is still in the receiving account.");
  const shown = t.hops.length < t.hops_followed
    ? el("p", { class: "muted" }, `First ${t.hops.length} of ${t.hops_followed} hops, by hop number.`)
    : null;
  return el("div", {},
    el("h3", {}, "Fund-flow trace (MED-inspired, assumptions in configs/tracer.yaml)"), intro, shown, hops);
}

function caseFileSection(c) {
  const f = c.case_file;
  const verdict = c.checker.passed
    ? el("span", { class: "good" }, "Passed the fact checker")
    : el("span", { class: "bad" }, `Rejected: ${c.checker.violations.map((v) => v.rule).join(", ")}`);
  return el("div", {},
    el("h3", {}, "Drafted case file (template baseline, not reviewed)"),
    el("p", {}, verdict),
    el("p", {}, f.summary),
    el("p", {},
      el("span", { class: "chip" }, `Typology: ${f.typology}`),
      el("span", { class: "chip" }, `Recommended: ${f.recommended_action}`),
      ...f.policy_refs.map((p) => el("span", { class: "chip" }, p))),
    el("ol", { class: "claims" }, ...f.claims.map((claim) => el("li", {}, claim.text))),
    el("p", { class: "muted" }, "The recommendation is a draft. Holding, monitoring or closing is the analyst's decision."));
}

function show(c, button) {
  document.querySelectorAll(".case-list button").forEach((b) => b.setAttribute("aria-current", "false"));
  button.setAttribute("aria-current", "true");
  const panel = document.getElementById("case");
  panel.replaceChildren(
    el("h2", {}, `Account ${c.account_id}`),
    el("p", { class: "muted" }, `${c.case_id} · scored on the ${c.as_of} snapshot · ${c.kind === "disputed" ? "received an accepted dispute" : "alerted"}`),
    ...[scoreSection(c), traceSection(c), evidenceSection(c), caseFileSection(c)].filter(Boolean));
}

function listItem(c) {
  const verdict = c.truth.confirmed_mule_within_horizon ? "mule" : "not a mule";
  const button = el("button", { type: "button", "aria-current": "false" },
    `Account ${c.account_id}`,
    el("span", { class: "meta" }, `${pct.format(c.score.probability)} · rank ${int.format(c.rank)} · ${verdict}`));
  button.addEventListener("click", () => {
    show(c, button);
    history.replaceState(null, "", `#${c.case_id}`);
    if (window.matchMedia("(max-width: 760px)").matches) {
      document.getElementById("case").scrollIntoView({ behavior: "smooth" });
    }
  });
  buttons.set(c.case_id, button);
  return el("li", {}, button);
}

async function main() {
  const panel = document.getElementById("case");
  try {
    const response = await fetch("cases.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    document.getElementById("budget").textContent = data.alert_budget_per_10k;
    const lists = { alerted: document.getElementById("alerted"), disputed: document.getElementById("disputed") };
    data.cases.forEach((c) => lists[c.kind].append(listItem(c)));
    const linked = data.cases.find((c) => `#${c.case_id}` === window.location.hash);
    const chosen = linked || data.cases[0];
    if (chosen) show(chosen, buttons.get(chosen.case_id));
  } catch (error) {
    panel.replaceChildren(el("p", { class: "bad" }, `Could not load cases.json (${error.message}). Serve this folder over HTTP.`));
  }
}

main();
