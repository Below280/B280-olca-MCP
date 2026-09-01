import { useState, useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer,
} from "recharts";

/*
 * Below280 LCA Results Dashboard
 * Themes: Below280 dark, openLCA green, Greyscale light
 * Languages: English, Portuguese
 */

// ── PASTE MCP RESULTS INTO DATA ─────────────────────────────
const DATA = {
  title: "Kerdyn Green PET Foam — Scenario Comparison",
  scenarios: {
    system: "2026-A1/A2/A3", method: "EN15804+A2 (EF 3.1)",
    results: {
      "IN_180 (Chennai)": [
        { category: "GWP-total", amount: 4.823, unit: "kg CO2-eq" },
        { category: "GWP-fossil", amount: 4.156, unit: "kg CO2-eq" },
        { category: "GWP-biogenic", amount: 0.542, unit: "kg CO2-eq" },
        { category: "GWP-luluc", amount: 0.125, unit: "kg CO2-eq" },
        { category: "ODP", amount: 3.21e-7, unit: "kg CFC-11-eq" },
        { category: "AP", amount: 0.0234, unit: "mol H+-eq" },
        { category: "EP-freshwater", amount: 1.82e-4, unit: "kg P-eq" },
        { category: "EP-marine", amount: 0.00312, unit: "kg N-eq" },
        { category: "POCP", amount: 0.0145, unit: "kg NMVOC-eq" },
        { category: "ADPF", amount: 68.4, unit: "MJ" },
        { category: "WDP", amount: 2.34, unit: "m3 world-eq" },
        { category: "PM", amount: 3.45e-7, unit: "disease incidence" },
      ],
      "CN_180 (Tianjin)": [
        { category: "GWP-total", amount: 5.912, unit: "kg CO2-eq" },
        { category: "GWP-fossil", amount: 5.234, unit: "kg CO2-eq" },
        { category: "GWP-biogenic", amount: 0.548, unit: "kg CO2-eq" },
        { category: "GWP-luluc", amount: 0.130, unit: "kg CO2-eq" },
        { category: "ODP", amount: 4.56e-7, unit: "kg CFC-11-eq" },
        { category: "AP", amount: 0.0312, unit: "mol H+-eq" },
        { category: "EP-freshwater", amount: 2.45e-4, unit: "kg P-eq" },
        { category: "EP-marine", amount: 0.00456, unit: "kg N-eq" },
        { category: "POCP", amount: 0.0189, unit: "kg NMVOC-eq" },
        { category: "ADPF", amount: 82.1, unit: "MJ" },
        { category: "WDP", amount: 3.12, unit: "m3 world-eq" },
        { category: "PM", amount: 4.89e-7, unit: "disease incidence" },
      ],
    },
  },
  sensitivity: {
    system: "2026-A1/A2/A3", method: "EN15804+A2 (EF 3.1)", variation_pct: 10,
    baseline: {
      "GWP-total": { amount: 4.823, unit: "kg CO2-eq" },
      "GWP-fossil": { amount: 4.156, unit: "kg CO2-eq" },
      "AP": { amount: 0.0234, unit: "mol H+-eq" },
      "ADPF": { amount: 68.4, unit: "MJ" },
      "WDP": { amount: 2.34, unit: "m3 world-eq" },
      "EP-freshwater": { amount: 1.82e-4, unit: "kg P-eq" },
    },
    sensitivity: {
      "a1_pet_resin_kg": { baseline_value: 1.12,
        minus: { "GWP-total": 4.31, "GWP-fossil": 3.72, "AP": 0.0210, "ADPF": 61.2, "WDP": 2.11, "EP-freshwater": 1.63e-4 },
        plus:  { "GWP-total": 5.34, "GWP-fossil": 4.59, "AP": 0.0258, "ADPF": 75.6, "WDP": 2.57, "EP-freshwater": 2.01e-4 } },
      "a3_electricity_kwh": { baseline_value: 3.45,
        minus: { "GWP-total": 4.65, "GWP-fossil": 4.01, "AP": 0.0225, "ADPF": 65.8, "WDP": 2.18, "EP-freshwater": 1.75e-4 },
        plus:  { "GWP-total": 4.99, "GWP-fossil": 4.31, "AP": 0.0243, "ADPF": 71.0, "WDP": 2.50, "EP-freshwater": 1.89e-4 } },
      "a3_natural_gas_mj": { baseline_value: 8.2,
        minus: { "GWP-total": 4.71, "GWP-fossil": 4.05, "AP": 0.0228, "ADPF": 66.1, "WDP": 2.31, "EP-freshwater": 1.79e-4 },
        plus:  { "GWP-total": 4.94, "GWP-fossil": 4.26, "AP": 0.0240, "ADPF": 70.7, "WDP": 2.37, "EP-freshwater": 1.85e-4 } },
      "a2_transport_tkm": { baseline_value: 12.5,
        minus: { "GWP-total": 4.78, "GWP-fossil": 4.12, "AP": 0.0231, "ADPF": 67.6, "WDP": 2.32, "EP-freshwater": 1.80e-4 },
        plus:  { "GWP-total": 4.87, "GWP-fossil": 4.19, "AP": 0.0237, "ADPF": 69.2, "WDP": 2.36, "EP-freshwater": 1.84e-4 } },
    },
    tested: ["a1_pet_resin_kg", "a3_electricity_kwh", "a3_natural_gas_mj", "a2_transport_tkm"],
  },
  contributions: {
    system: "2026-A1/A2/A3", method: "EN15804+A2 (EF 3.1)",
    categories: {
      "GWP-fossil": { total: 4.156, unit: "kg CO2-eq", covered_pct: 94.2,
        contributors: [
          { process: "bridge:PET granulate.GLO", amount: 2.18, pct: 52.5 },
          { process: "bridge:electricity.IN", amount: 0.83, pct: 20.0 },
          { process: "bridge:natural gas.RER", amount: 0.46, pct: 11.1 },
          { process: "bridge:transport.sea", amount: 0.21, pct: 5.1 },
          { process: "bridge:transport.road", amount: 0.14, pct: 3.4 },
          { process: "bridge:packaging.GLO", amount: 0.09, pct: 2.2 },
        ] },
      "AP": { total: 0.0234, unit: "mol H+-eq", covered_pct: 91.8,
        contributors: [
          { process: "bridge:electricity.IN", amount: 0.0098, pct: 41.9 },
          { process: "bridge:PET granulate.GLO", amount: 0.0062, pct: 26.5 },
          { process: "bridge:natural gas.RER", amount: 0.0031, pct: 13.2 },
          { process: "bridge:transport.sea", amount: 0.0015, pct: 6.4 },
          { process: "bridge:transport.road", amount: 0.0009, pct: 3.8 },
        ] },
      "ADPF": { total: 68.4, unit: "MJ", covered_pct: 96.1,
        contributors: [
          { process: "bridge:PET granulate.GLO", amount: 38.2, pct: 55.8 },
          { process: "bridge:natural gas.RER", amount: 12.4, pct: 18.1 },
          { process: "bridge:electricity.IN", amount: 9.8, pct: 14.3 },
          { process: "bridge:transport.sea", amount: 3.2, pct: 4.7 },
          { process: "bridge:transport.road", amount: 2.1, pct: 3.1 },
        ] },
    },
  },
};

// ── THEMES ──────────────────────────────────────────────────
const THEMES = {
  greyscale: {
    name: "Greyscale",
    bg: "#f5f5f5", panelBg: "#ffffff", border: "#d0d0d0",
    text: "#222222", muted: "#666666", faint: "#aaaaaa",
    primary: "#333333", secondary: "#777777", accent: "#e8e8e8",
    bars: ["#333333", "#888888", "#555555", "#aaaaaa", "#666666"],
    grid: "#00000012", tick: "#555", tooltipBg: "#ffffff",
    tabActive: "#e0e0e0", tabText: "#222",
  },
  dark: {
    name: "Dark",
    bg: "#111111", panelBg: "#1a1a1a", border: "#333333",
    text: "#e0e0e0", muted: "#999", faint: "#555",
    primary: "#ffffff", secondary: "#aaaaaa", accent: "#333333",
    bars: ["#e0e0e0", "#999999", "#cccccc", "#777777", "#bbbbbb"],
    grid: "#ffffff10", tick: "#aaa", tooltipBg: "#222222",
    tabActive: "#333333", tabText: "#ffffff",
  },
  b280: {
    name: "B280",
    bg: "#0d0d1a", panelBg: "#12122a", border: "#2e0a4a",
    text: "#e0e0e0", muted: "#888", faint: "#444",
    primary: "#12ebf2", secondary: "#ff5c05", accent: "#2e0a4a",
    bars: ["#12ebf2", "#ff5c05", "#a259ff", "#ff5ca2", "#59ffa2"],
    grid: "#ffffff10", tick: "#ccc", tooltipBg: "#2e0a4a",
    tabActive: "#2e0a4a", tabText: "#12ebf2",
  },
  openlca: {
    name: "openLCA",
    bg: "#1a2332", panelBg: "#1e2d3d", border: "#2a4a3a",
    text: "#d8e8d8", muted: "#8aaa8a", faint: "#3a5a3a",
    primary: "#4caf50", secondary: "#ff9800", accent: "#1b5e20",
    bars: ["#4caf50", "#ff9800", "#29b6f6", "#ab47bc", "#ef5350"],
    grid: "#ffffff10", tick: "#9ab89a", tooltipBg: "#1b3a2a",
    tabActive: "#1b5e20", tabText: "#4caf50",
  },
};

// ── TRANSLATIONS ────────────────────────────────────────────
const LANG = {
  en: {
    impact_cat: "Impact category", baseline: "Baseline",
    deviation: "Deviation from baseline", copy_csv: "Copy CSV",
    copied: "Copied", scenarios: "Scenarios", sensitivity: "Sensitivity",
    contributions: "Contributions", table: "Table",
    norm_profile: "Normalised profile (each category scaled to its maximum)",
    total: "Total", covered: "covered", show: "Show",
    contribution: "Contribution", no_data: "No table data.",
    footer_left: "Below280 \u00b7 openLCA MCP",
    footer_right: "All results from connected database",
  },
  pt: {
    impact_cat: "Categoria de impacto", baseline: "Linha de base",
    deviation: "Desvio da linha de base", copy_csv: "Copiar CSV",
    copied: "Copiado", scenarios: "Cen\u00e1rios", sensitivity: "Sensibilidade",
    contributions: "Contribui\u00e7\u00f5es", table: "Tabela",
    norm_profile: "Perfil normalizado (cada categoria ajustada ao seu m\u00e1ximo)",
    total: "Total", covered: "coberto", show: "Mostrar",
    contribution: "Contribui\u00e7\u00e3o", no_data: "Sem dados na tabela.",
    footer_left: "Below280 \u00b7 openLCA MCP",
    footer_right: "Todos os resultados da base de dados conectada",
  },
};

const fmt = (v) => {
  if (v === undefined || v === null) return "\u2014";
  const abs = Math.abs(v);
  if (abs === 0) return "0";
  if (abs < 0.001 || abs >= 1e6) return v.toExponential(3);
  if (abs < 1) return v.toPrecision(3);
  return v.toLocaleString("en-GB", { maximumSignificantDigits: 4 });
};

// ── Select component ────────────────────────────────────────
function Select({ value, onChange, options, theme }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}
      style={{ background: theme.panelBg, color: theme.primary,
        border: `1px solid ${theme.primary}33`, borderRadius: 4,
        padding: "6px 10px", fontSize: 13 }}>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

// ── Scenario Comparison ─────────────────────────────────────
function ScenarioView({ data, t, theme }) {
  const names = Object.keys(data.results);
  const cats = data.results[names[0]].map((d) => d.category);
  const [sel, setSel] = useState(cats[0] || "");

  const chartData = useMemo(() => names.map((n, i) => {
    const imp = data.results[n].find((d) => d.category === sel);
    return { name: n, value: imp?.amount || 0, fill: theme.bars[i % theme.bars.length] };
  }), [sel, names, data.results, theme]);

  const unit = data.results[names[0]]?.find((d) => d.category === sel)?.unit || "";

  const radarData = useMemo(() => cats.slice(0, 12).map((cat) => {
    const entry = { category: cat.length > 16 ? cat.slice(0, 14) + "\u2026" : cat };
    const vals = names.map((s) => Math.abs(data.results[s].find((d) => d.category === cat)?.amount || 0));
    const mx = Math.max(...vals, 1e-30);
    names.forEach((s, i) => { entry[s] = (vals[i] / mx) * 100; });
    return entry;
  }), [cats, names, data.results]);

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 13, color: theme.muted, marginRight: 8 }}>{t.impact_cat}</label>
        <Select value={sel} onChange={setSel} options={cats} theme={theme} />
      </div>
      <p style={{ fontSize: 12, color: theme.muted, margin: "0 0 4px" }}>{sel} ({unit})</p>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={chartData} margin={{ left: 10, right: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} />
          <XAxis dataKey="name" tick={{ fill: theme.tick, fontSize: 11 }} />
          <YAxis tick={{ fill: theme.tick, fontSize: 11 }} tickFormatter={fmt} />
          <Tooltip contentStyle={{ background: theme.tooltipBg, border: `1px solid ${theme.primary}44`, borderRadius: 4, color: theme.text }}
            labelStyle={{ color: theme.primary }} formatter={(v) => [fmt(v) + " " + unit, ""]} />
          <Bar dataKey="value" radius={[3, 3, 0, 0]}>
            {chartData.map((e, i) => <rect key={i} fill={e.fill} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      {names.length > 1 && radarData.length > 2 && (
        <div style={{ marginTop: 24 }}>
          <p style={{ fontSize: 13, color: theme.muted, marginBottom: 4 }}>{t.norm_profile}</p>
          <ResponsiveContainer width="100%" height={320}>
            <RadarChart data={radarData}>
              <PolarGrid stroke={theme.grid.replace("10", "20")} />
              <PolarAngleAxis dataKey="category" tick={{ fill: theme.muted, fontSize: 9 }} />
              <PolarRadiusAxis tick={false} axisLine={false} />
              {names.map((s, i) => (
                <Radar key={s} name={s} dataKey={s} stroke={theme.bars[i]} fill={theme.bars[i]} fillOpacity={0.12} strokeWidth={1.5} />
              ))}
              <Legend wrapperStyle={{ fontSize: 11, color: theme.muted }} />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

// ── Sensitivity Tornado ─────────────────────────────────────
function SensitivityView({ data, t, theme }) {
  const cats = Object.keys(data.baseline);
  const [sel, setSel] = useState(cats[0] || "");
  const params = data.tested || Object.keys(data.sensitivity);
  const baseVal = data.baseline[sel]?.amount || 0;
  const unit = data.baseline[sel]?.unit || "";

  const chartData = useMemo(() => {
    if (!sel) return [];
    return params.map((p) => {
      const m = data.sensitivity[p]?.minus?.[sel] || baseVal;
      const pl = data.sensitivity[p]?.plus?.[sel] || baseVal;
      return { name: p.length > 24 ? p.slice(0, 22) + "\u2026" : p,
        low: Math.min(m, pl) - baseVal, high: Math.max(m, pl) - baseVal,
        range: Math.abs(pl - m) };
    }).sort((a, b) => b.range - a.range);
  }, [sel, params, data, baseVal]);

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 13, color: theme.muted, marginRight: 8 }}>{t.impact_cat}</label>
        <Select value={sel} onChange={setSel} options={cats} theme={theme} />
        <span style={{ fontSize: 11, color: theme.faint, marginLeft: 12 }}>
          {t.baseline}: {fmt(baseVal)} {unit} | \u00b1{data.variation_pct}%
        </span>
      </div>
      <ResponsiveContainer width="100%" height={Math.max(180, chartData.length * 36 + 40)}>
        <BarChart data={chartData} layout="vertical" margin={{ left: 150, right: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} />
          <XAxis type="number" tick={{ fill: theme.tick, fontSize: 10 }} tickFormatter={fmt} />
          <YAxis type="category" dataKey="name" width={140} tick={{ fill: theme.tick, fontSize: 10 }} />
          <Tooltip contentStyle={{ background: theme.tooltipBg, border: `1px solid ${theme.primary}44`, borderRadius: 4, color: theme.text }}
            formatter={(v, name) => [fmt(v) + " " + unit, name === "low" ? "\u2212" + data.variation_pct + "%" : "+" + data.variation_pct + "%"]} />
          <Bar dataKey="low" fill={theme.bars[0]} stackId="t" radius={[3, 0, 0, 3]} />
          <Bar dataKey="high" fill={theme.bars[1]} stackId="t" />
        </BarChart>
      </ResponsiveContainer>
      <div style={{ display: "flex", gap: 16, justifyContent: "center", marginTop: 8, fontSize: 11 }}>
        <span><span style={{ color: theme.bars[0] }}>{"\u25a0"}</span> \u2212{data.variation_pct}%</span>
        <span><span style={{ color: theme.bars[1] }}>{"\u25a0"}</span> +{data.variation_pct}%</span>
        <span style={{ color: theme.faint }}>{t.deviation}</span>
      </div>
    </div>
  );
}

// ── Contribution Breakdown ──────────────────────────────────
function ContributionView({ data, t, theme }) {
  const catNames = Object.keys(data.categories);
  const [sel, setSel] = useState(catNames[0] || "");
  const cd = data.categories[sel] || { contributors: [], total: 0, unit: "" };
  const chartData = useMemo(() => cd.contributors.slice(0, 12).map((c) => ({
    name: c.process.length > 30 ? c.process.slice(0, 28) + "\u2026" : c.process,
    value: c.amount, pct: c.pct,
  })), [cd]);

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 13, color: theme.muted, marginRight: 8 }}>{t.impact_cat}</label>
        <Select value={sel} onChange={setSel} options={catNames} theme={theme} />
        <span style={{ fontSize: 11, color: theme.faint, marginLeft: 12 }}>
          {t.total}: {fmt(cd.total)} {cd.unit} | {cd.covered_pct}% {t.covered}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={Math.max(180, chartData.length * 34 + 40)}>
        <BarChart data={chartData} layout="vertical" margin={{ left: 190, right: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} />
          <XAxis type="number" tick={{ fill: theme.tick, fontSize: 10 }} tickFormatter={fmt} />
          <YAxis type="category" dataKey="name" width={180} tick={{ fill: theme.tick, fontSize: 10 }} />
          <Tooltip contentStyle={{ background: theme.tooltipBg, border: `1px solid ${theme.primary}44`, borderRadius: 4, color: theme.text }}
            formatter={(v, _, props) => [`${fmt(v)} ${cd.unit} (${props.payload.pct}%)`, t.contribution]} />
          <Bar dataKey="value" fill={theme.bars[0]} radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Results Table ───────────────────────────────────────────
function TableView({ scenarios, sensitivity, t, theme }) {
  const [copied, setCopied] = useState(false);
  const [src, setSrc] = useState(scenarios ? "scenarios" : "sensitivity");
  const { headers, rows } = useMemo(() => {
    if (src === "scenarios" && scenarios) {
      const ns = Object.keys(scenarios.results);
      const cs = scenarios.results[ns[0]];
      return { headers: [t.impact_cat, "Unit", ...ns],
        rows: cs.map((c) => [c.category, c.unit, ...ns.map((n) =>
          scenarios.results[n].find((d) => d.category === c.category)?.amount)]) };
    }
    if (src === "sensitivity" && sensitivity) {
      const cs = Object.keys(sensitivity.baseline);
      const ps = sensitivity.tested || Object.keys(sensitivity.sensitivity);
      const h = [t.impact_cat, "Unit", t.baseline];
      ps.forEach((p) => { h.push(`${p} \u2212${sensitivity.variation_pct}%`); h.push(`${p} +${sensitivity.variation_pct}%`); });
      return { headers: h, rows: cs.map((c) => {
        const r = [c, sensitivity.baseline[c]?.unit || "", sensitivity.baseline[c]?.amount];
        ps.forEach((p) => { r.push(sensitivity.sensitivity[p]?.minus?.[c]); r.push(sensitivity.sensitivity[p]?.plus?.[c]); });
        return r;
      }) };
    }
    return { headers: [], rows: [] };
  }, [src, scenarios, sensitivity, t]);

  const copyCSV = () => {
    const csv = [headers.join(","), ...rows.map((r) => r.map((v) => typeof v === "number" ? v : `"${v ?? ""}"`).join(","))].join("\n");
    navigator.clipboard.writeText(csv);
    setCopied(true); setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10, alignItems: "center" }}>
        <div>
          <label style={{ fontSize: 12, color: theme.muted, marginRight: 8 }}>{t.show}</label>
          {scenarios && <button onClick={() => setSrc("scenarios")} style={{ background: src === "scenarios" ? theme.tabActive : "transparent", color: src === "scenarios" ? theme.tabText : theme.faint, border: `1px solid ${theme.border}`, borderRadius: 3, padding: "3px 10px", fontSize: 11, cursor: "pointer", marginRight: 4 }}>{t.scenarios}</button>}
          {sensitivity && <button onClick={() => setSrc("sensitivity")} style={{ background: src === "sensitivity" ? theme.tabActive : "transparent", color: src === "sensitivity" ? theme.tabText : theme.faint, border: `1px solid ${theme.border}`, borderRadius: 3, padding: "3px 10px", fontSize: 11, cursor: "pointer" }}>{t.sensitivity}</button>}
        </div>
        <button onClick={copyCSV} style={{ background: copied ? theme.primary + "22" : "transparent", color: theme.primary, border: `1px solid ${theme.primary}44`, borderRadius: 4, padding: "4px 12px", fontSize: 11, cursor: "pointer" }}>
          {copied ? t.copied : t.copy_csv}
        </button>
      </div>
      {rows.length === 0 ? <p style={{ color: theme.faint }}>{t.no_data}</p> : (
        <div style={{ overflowX: "auto", maxHeight: 380 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
            <thead><tr>{headers.map((h, i) => (
              <th key={i} style={{ textAlign: i < 2 ? "left" : "right", padding: "6px 8px", borderBottom: `1px solid ${theme.primary}33`, color: theme.primary, fontWeight: 600, position: "sticky", top: 0, background: theme.panelBg, whiteSpace: "nowrap" }}>{h}</th>
            ))}</tr></thead>
            <tbody>{rows.map((row, ri) => (
              <tr key={ri} style={{ borderBottom: `1px solid ${theme.grid}` }}>
                {row.map((cell, ci) => (
                  <td key={ci} style={{ textAlign: ci < 2 ? "left" : "right", padding: "5px 8px", color: ci === 0 ? theme.text : theme.muted, whiteSpace: ci < 2 ? "normal" : "nowrap" }}>
                    {typeof cell === "number" ? fmt(cell) : (cell ?? "\u2014")}
                  </td>
                ))}
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Main Dashboard ──────────────────────────────────────────
const TAB_KEYS = [];
if (DATA.scenarios) TAB_KEYS.push("scenarios");
if (DATA.contributions) TAB_KEYS.push("contributions");
if (DATA.sensitivity) TAB_KEYS.push("sensitivity");
TAB_KEYS.push("table");

export default function B280Dashboard() {
  const [tab, setTab] = useState(TAB_KEYS[0]);
  const [themeKey, setThemeKey] = useState("greyscale");
  const [lang, setLang] = useState("en");
  const theme = THEMES[themeKey];
  const t = LANG[lang];

  const tabLabel = (key) => {
    const map = { scenarios: t.scenarios, contributions: t.contributions, sensitivity: t.sensitivity, table: t.table };
    return map[key] || key;
  };

  const cycleTheme = () => {
    const keys = Object.keys(THEMES);
    setThemeKey(keys[(keys.indexOf(themeKey) + 1) % keys.length]);
  };

  return (
    <div style={{ fontFamily: "'Inter', system-ui, sans-serif", background: theme.bg, color: theme.text, minHeight: "100vh", padding: "24px 20px", transition: "background 0.3s, color 0.3s" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <div style={{ width: 6, height: 24, background: theme.primary, borderRadius: 2 }} />
            <h1 style={{ fontSize: 18, fontWeight: 700, color: theme.text, margin: 0 }}>{DATA.title}</h1>
          </div>
          <p style={{ fontSize: 11, color: theme.faint, margin: "2px 0 0 16px" }}>
            {DATA.scenarios?.system || DATA.sensitivity?.system || ""} {"\u00b7"} {DATA.scenarios?.method || DATA.sensitivity?.method || ""}
          </p>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => setLang(lang === "en" ? "pt" : "en")}
            style={{ background: theme.panelBg, color: theme.muted, border: `1px solid ${theme.border}`, borderRadius: 4, padding: "4px 10px", fontSize: 11, cursor: "pointer" }}>
            {lang === "en" ? "PT" : "EN"}
          </button>
          <button onClick={cycleTheme}
            style={{ background: theme.panelBg, color: theme.muted, border: `1px solid ${theme.border}`, borderRadius: 4, padding: "4px 10px", fontSize: 11, cursor: "pointer" }}>
            {theme.name}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 2, marginBottom: 20, borderBottom: `1px solid ${theme.border}` }}>
        {TAB_KEYS.map((k) => (
          <button key={k} onClick={() => setTab(k)} style={{
            background: tab === k ? theme.tabActive : "transparent",
            color: tab === k ? theme.tabText : theme.muted,
            border: "none", padding: "8px 16px", fontSize: 12,
            fontWeight: tab === k ? 600 : 400, cursor: "pointer",
            borderRadius: "4px 4px 0 0",
          }}>{tabLabel(k)}</button>
        ))}
      </div>

      {/* Content */}
      <div style={{ background: theme.panelBg, borderRadius: 6, border: `1px solid ${theme.border}`, padding: 20 }}>
        {tab === "scenarios" && DATA.scenarios && <ScenarioView data={DATA.scenarios} t={t} theme={theme} />}
        {tab === "sensitivity" && DATA.sensitivity && <SensitivityView data={DATA.sensitivity} t={t} theme={theme} />}
        {tab === "contributions" && DATA.contributions && <ContributionView data={DATA.contributions} t={t} theme={theme} />}
        {tab === "table" && <TableView scenarios={DATA.scenarios} sensitivity={DATA.sensitivity} t={t} theme={theme} />}
      </div>

      {/* Footer */}
      <div style={{ marginTop: 16, fontSize: 10, color: theme.faint, display: "flex", justifyContent: "space-between" }}>
        <span>{t.footer_left}</span><span>{t.footer_right}</span>
      </div>
    </div>
  );
}
