// ── Tab & UI helpers ───────────────────────────────────────────────────────────

function switchTab(name) {
  ['query', 'json'].forEach((t) => {
    document.getElementById(`tab-${t}-btn`).classList.toggle('active', t === name);
    document.getElementById(`tab-${t}`).classList.toggle('active', t === name);
  });
}

function toggleFilters() {
  const panel = document.getElementById('filters-panel');
  const toggle = document.getElementById('filters-toggle');
  panel.classList.toggle('open');
  toggle.textContent = panel.classList.contains('open')
    ? '▾ Filters (optional)'
    : '▸ Filters (optional)';
}

function setLoading(loading) {
  const btn = document.getElementById('query-btn');
  btn.disabled = loading;
  btn.textContent = loading ? 'Loading…' : 'Visualize →';
}

function showError(id, msg) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.style.display = msg ? 'block' : 'none';
}

// ── Vega-Lite adapter ──────────────────────────────────────────────────────────

const TYPE_TO_MARK = {
  time_series: { type: 'line', point: true },
  bar_chart:   'bar',
  histogram:   'bar',
  scatter:     'point',
  geographic:  'bar',
  grouped_bar: 'bar',
};

function toVegaLite(viz) {
  const { type, title, encoding, data } = viz;
  const mark = TYPE_TO_MARK[type] ?? 'bar';

  const xField = encoding.x?.field;
  const yField = encoding.y?.field ?? 'count';
  const firstRow = data[0] ?? {};
  // Detect quantitative vs ordinal from the actual data value
  const xType = typeof firstRow[xField] === 'number' ? 'quantitative' : 'ordinal';

  const enc = {
    x: {
      field: xField,
      type: xType,
      axis: { labelAngle: -35, labelLimit: 120 },
      title: xField,
    },
    y: {
      field: yField,
      type: 'quantitative',
      title: yField,
    },
    tooltip: [
      { field: xField, type: xType },
      { field: yField, type: 'quantitative' },
    ],
  };

  // Scatter: size bubbles by the count field
  if (type === 'scatter') {
    enc.size = { field: yField, type: 'quantitative' };
  }

  return {
    $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
    title,
    mark,
    data: { values: data },
    encoding: enc,
    width: 'container',
    height: 380,
  };
}

// ── Network graph renderer (vis-network) ───────────────────────────────────────

function renderNetwork(viz) {
  const container = document.getElementById('network');
  container.innerHTML = '';  // clear any previous render

  const nodes = new vis.DataSet(
    viz.nodes.map((n) => ({
      id: n.id,
      label: n.label,
      value: n.weight,
      title: `${n.label}: ${n.weight} studies`,
    }))
  );
  const edges = new vis.DataSet(
    viz.edges.map((e) => ({
      from: e.source,
      to: e.target,
      value: e.weight,
      title: `Co-occurrence: ${e.weight}`,
    }))
  );

  new vis.Network(container, { nodes, edges }, {
    nodes: {
      scaling: { min: 10, max: 50 },
      font: { size: 12 },
      borderWidth: 1,
    },
    edges: {
      scaling: { min: 1, max: 8 },
      color: { color: '#94a3b8', opacity: 0.7 },
      smooth: { type: 'continuous' },
    },
    physics: {
      stabilization: { iterations: 200, updateInterval: 25 },
      barnesHut: { gravitationalConstant: -3000 },
    },
    interaction: { hover: true, tooltipDelay: 100 },
  });
}

// ── Citations panel ────────────────────────────────────────────────────────────

function showCitations(datum) {
  const citations = datum.citations;
  if (!citations || citations.length === 0) return;

  // Find the label for this datum (first non-count, non-citations key)
  const skip = new Set(['count', 'citations']);
  const labelKey = Object.keys(datum).find((k) => !skip.has(k) && !k.startsWith('_'));
  const label = labelKey ? datum[labelKey] : 'selected point';

  document.getElementById('citations-title').textContent =
    `${citations.length} citation${citations.length > 1 ? 's' : ''} for "${label}"`;

  document.getElementById('citations-list').innerHTML = citations
    .map(({ nct_id, excerpt }) => `
      <div class="citation-card">
        <a class="citation-link" href="https://clinicaltrials.gov/study/${nct_id}" target="_blank" rel="noopener">
          ${nct_id} ↗
        </a>
        <div class="citation-excerpt">${excerpt}</div>
      </div>`)
    .join('');

  document.getElementById('citations-hint').style.display = 'none';
  document.getElementById('citations-panel').style.display = 'block';
}

function hideCitations() {
  document.getElementById('citations-panel').style.display = 'none';
  document.getElementById('citations-hint').style.display = 'block';
}

// ── Main render dispatcher ─────────────────────────────────────────────────────

async function render(vizResponse) {
  const { visualization: viz, response_metadata: meta } = vizResponse;

  const placeholder = document.getElementById('placeholder');
  const chart = document.getElementById('chart');
  const network = document.getElementById('network');

  // Reset display state
  placeholder.style.display = 'none';
  chart.style.display = 'none';
  network.style.display = 'none';
  chart.innerHTML = '';
  hideCitations();
  document.getElementById('citations-hint').style.display = 'none';

  document.getElementById('chart-title').textContent = viz.title ?? '';

  if (viz.type === 'network_graph') {
    network.style.display = 'block';
    renderNetwork(viz);
    // Network graph nodes/edges don't carry citations in the current schema
  } else {
    chart.style.display = 'block';
    const spec = toVegaLite(viz);
    const hasCitations = viz.data?.some((d) => d.citations?.length);
    const result = await vegaEmbed(chart, spec, {
      actions: { export: true, source: false, compiled: false, editor: false },
      renderer: 'svg',
    });
    if (hasCitations) {
      document.getElementById('citations-hint').style.display = 'block';
      result.view.addEventListener('click', (_event, item) => {
        if (item?.datum?.citations?.length) {
          showCitations(item.datum);
        }
      });
    }
  }

  showMetadata(meta);
}

function showMetadata(meta) {
  if (!meta) return;
  const el = document.getElementById('metadata');

  document.getElementById('meta-badges').innerHTML = [
    `<span class="meta-badge">Total: ${(meta.total_count ?? 0).toLocaleString()}</span>`,
    `<span class="meta-badge">Fetched: ${(meta.fetched_count ?? 0).toLocaleString()}</span>`,
    meta.truncated ? '<span class="meta-badge" style="color:#92400e;background:#fffbeb;border-color:#fcd34d">Truncated</span>' : '',
    meta.count_verified ? '<span class="meta-badge" style="color:#065f46;background:#ecfdf5;border-color:#6ee7b7">Verified</span>' : '',
  ].join('');

  document.getElementById('meta-warnings').innerHTML = (meta.warnings ?? [])
    .map((w) => `<div class="warning">⚠ ${w}</div>`)
    .join('');

  document.getElementById('meta-interpretation').textContent =
    meta.query_interpretation ?? '';

  el.style.display = 'block';
}

// ── Query mode ─────────────────────────────────────────────────────────────────

async function submitQuery() {
  showError('query-error', '');
  const query = document.getElementById('query-input').value.trim();
  if (!query) { showError('query-error', 'Query is required.'); return; }

  const filters = {};
  const cond      = document.getElementById('f-condition').value.trim();
  const drug      = document.getElementById('f-drug').value.trim();
  const status    = document.getElementById('f-status').value;
  const startYear = document.getElementById('f-start-year').value;
  const endYear   = document.getElementById('f-end-year').value;
  if (cond)      filters.condition = cond;
  if (drug)      filters.drug_name = drug;
  if (status)    filters.status = status;
  if (startYear) filters.start_year = parseInt(startYear, 10);
  if (endYear)   filters.end_year   = parseInt(endYear, 10);

  setLoading(true);
  try {
    const resp = await fetch('/visualize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        filters: Object.keys(filters).length ? filters : null,
      }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail ?? `HTTP ${resp.status}`);
    }
    await render(await resp.json());
  } catch (e) {
    showError('query-error', e.message);
  } finally {
    setLoading(false);
  }
}

// ── Load JSON mode ─────────────────────────────────────────────────────────────

async function loadExample(name) {
  showError('json-error', '');
  try {
    const resp = await fetch(`/examples-data/${name}.json`);
    if (!resp.ok) throw new Error(`Could not load ${name}.json (${resp.status})`);
    const data = await resp.json();
    // Example files wrap the response under a "response" key
    await render(data.response ?? data);
  } catch (e) {
    showError('json-error', e.message);
  }
}

function loadFile(event) {
  showError('json-error', '');
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async (e) => {
    try {
      const data = JSON.parse(e.target.result);
      await render(data.response ?? data);
    } catch (err) {
      showError('json-error', `Invalid JSON: ${err.message}`);
    }
  };
  reader.readAsText(file);
}

async function renderPasted() {
  showError('json-error', '');
  const text = document.getElementById('json-paste').value.trim();
  if (!text) { showError('json-error', 'Nothing to render.'); return; }
  try {
    const data = JSON.parse(text);
    await render(data.response ?? data);
  } catch (e) {
    showError('json-error', `Invalid JSON: ${e.message}`);
  }
}

// ── Keyboard shortcuts ─────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('query-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submitQuery();
  });
});
