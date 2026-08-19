import { basename, extname } from "node:path";

function lineAt(text, offset) {
  return text.slice(0, offset).split(/\r?\n/).length;
}

function normalizeServicePath(value) {
  const withoutAlias = String(value || "").replace(/^[^/]*::/, "/");
  const normalized = (`/${withoutAlias}`).replace(/\/+/g, "/").replace(/\{[^}]+\}|:\w+/g, "{param}");
  return normalized.replace(/\/$/, "") || "/";
}

export function extractNexacro(text, rel, workspace) {
  if (!/\.(?:xfdl|xjs)$/i.test(rel)) return { bindings: [], consumers: [], uiFlow: { screens: [], events: [], datasets: [], transactions: [] } };
  const events = [];
  const bindings = [];
  for (const match of text.matchAll(/<([A-Za-z_:][\w:.-]*)\b([^>]*)>/g)) {
    const component = match[2].match(/\bid\s*=\s*["']([^"']+)["']/i)?.[1] || match[1];
    for (const event of match[2].matchAll(/\b(on[a-z]\w*)\s*=\s*["']([A-Za-z_]\w*)["']/gi)) {
      const trigger = `${component}.${event[1]}`;
      const offset = match.index + event.index;
      events.push({ screen: rel, component, event: event[1], handler: event[2], file: rel, line: lineAt(text, offset), workspace: workspace.id, origin: "nexacro-adapter", confidence: "HIGH" });
      bindings.push({ trigger: `${rel}#${trigger}`, handler_name: event[2], type: "ui_event", file: rel, line: lineAt(text, offset), workspace: workspace.id });
    }
  }

  const datasets = [];
  for (const match of text.matchAll(/<Dataset\b([^>]*)>([\s\S]*?)<\/Dataset>/gi)) {
    const id = match[1].match(/\bid\s*=\s*["']([^"']+)["']/i)?.[1];
    if (!id) continue;
    const columns = [...match[2].matchAll(/<Column\b[^>]*\bid\s*=\s*["']([^"']+)["'][^>]*?(?:\btype\s*=\s*["']([^"']+)["'])?[^>]*\/?\s*>/gi)]
      .map((column) => ({ name: column[1], type: column[2] || "unknown" }));
    datasets.push({ id, screen: rel, columns, file: rel, line: lineAt(text, match.index), workspace: workspace.id, origin: "nexacro-adapter", confidence: "HIGH" });
  }

  const transactions = [];
  const consumers = [];
  const transaction = /(?:this\.)?transaction\s*\(\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']\s*,\s*["']([^"']*)["']\s*,\s*["']([^"']*)["']\s*,\s*["']([^"']*)["']\s*,\s*["']([^"']+)["']/g;
  for (const match of text.matchAll(transaction)) {
    const pathPattern = normalizeServicePath(match[2]);
    const line = lineAt(text, match.index);
    transactions.push({ service_id: match[1], url: match[2], path_pattern: pathPattern, input_datasets: match[3], output_datasets: match[4], arguments: match[5], callback: match[6], file: rel, line, workspace: workspace.id, origin: "nexacro-adapter", confidence: "HIGH" });
    consumers.push({ id: `${workspace.id}::${rel}:${line}::ANY ${pathPattern}`, workspace: workspace.id, source: "local", call_type: "nexacro-transaction", method: "ANY", path_literal: match[2], path_pattern: pathPattern, file: rel, line, consumer_kind: workspace.kind, service_id: match[1], callback: match[6], origin: "nexacro-adapter", confidence: "MEDIUM" });
  }

  const form = text.match(/<Form\b[^>]*\bid\s*=\s*["']([^"']+)["']/i);
  const screens = form ? [{ id: form[1], file: rel, title: text.match(/<Form\b[^>]*\btitletext\s*=\s*["']([^"']+)["']/i)?.[1] || basename(rel), workspace: workspace.id, origin: "nexacro-adapter", confidence: "HIGH" }] : [];
  return { bindings, consumers, uiFlow: { screens, events, datasets, transactions }, adapter: extname(rel).toLowerCase() === ".xfdl" ? "nexacro-form" : "nexacro" };
}
