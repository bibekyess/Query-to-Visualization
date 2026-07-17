// Reusable visualization rendering — Vega-Lite charts and vis-network graphs.
// Shared by the classic UI (app.js) and the chatbot (chat.js). Exposes a single
// entry point, window.VizRenderer.render(container, vizResponse), which builds a
// self-contained chart card (title, chart, metadata, inline citations) inside the
// given element.

(function () {
  const TYPE_TO_MARK = {
    time_series: { type: 'line', point: true },
    bar_chart: 'bar',
    histogram: 'bar',
    scatter: 'point',
    geographic: 'bar',
    grouped_bar: 'bar',
  };

  function toVegaLite(viz) {
    const { type, title, encoding, data } = viz;
    const mark = TYPE_TO_MARK[type] ?? 'bar';

    if (type === 'scatter') {
      const xTitle = encoding.x?.field ?? 'x';
      const yTitle = encoding.y?.field ?? 'y';
      return {
        $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
        title,
        mark: { type: 'point', filled: true, opacity: 0.6, color: '#2563eb' },
        data: { values: data },
        encoding: {
          x: { field: 'x', type: 'quantitative', title: xTitle },
          y: { field: 'y', type: 'quantitative', title: yTitle },
          tooltip: [
            { field: 'nct_id', type: 'nominal', title: 'Trial' },
            { field: 'x', type: 'quantitative', title: xTitle },
            { field: 'y', type: 'quantitative', title: yTitle },
          ],
        },
        width: 'container',
        height: 340,
      };
    }

    const xField = encoding.x?.field;
    const yField = encoding.y?.field ?? 'count';
    const seriesField = encoding.series?.field;
    const firstRow = data[0] ?? {};
    const xType = typeof firstRow[xField] === 'number' ? 'quantitative' : 'ordinal';

    const enc = {
      x: { field: xField, type: xType, axis: { labelAngle: -35, labelLimit: 120 }, title: xField },
      y: { field: yField, type: 'quantitative', title: yField },
      tooltip: [
        { field: xField, type: xType },
        { field: yField, type: 'quantitative' },
      ],
    };

    if (seriesField) {
      enc.color = { field: seriesField, type: 'nominal', title: seriesField };
      if (type === 'grouped_bar') enc.xOffset = { field: seriesField, type: 'nominal' };
      enc.tooltip.push({ field: seriesField, type: 'nominal' });
    } else if (mark === 'bar' || mark === 'point') {
      enc.color = { value: '#2563eb' };
    } else {
      enc.color = { value: '#2563eb' };
    }

    return {
      $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
      title,
      mark,
      data: { values: data },
      encoding: enc,
      width: 'container',
      height: 340,
      config: { range: { category: ['#2563eb', '#0ea5e9', '#8b5cf6', '#14b8a6', '#f59e0b', '#ec4899'] } },
    };
  }

  function renderNetwork(container, viz) {
    const nodes = new vis.DataSet(
      viz.nodes.map((n) => ({ id: n.id, label: n.label, value: n.weight, title: `${n.label}: ${n.weight} studies` }))
    );
    const edges = new vis.DataSet(
      viz.edges.map((e) => ({ from: e.source, to: e.target, value: e.weight, title: `Co-occurrence: ${e.weight}` }))
    );
    new vis.Network(container, { nodes, edges }, {
      nodes: { scaling: { min: 10, max: 46 }, font: { size: 12 }, borderWidth: 1, color: { background: '#dbe6fb', border: '#2563eb', highlight: { background: '#2563eb', border: '#1d4ed8' } } },
      edges: { scaling: { min: 1, max: 8 }, color: { color: '#b6c6e6', opacity: 0.7 }, smooth: { type: 'continuous' } },
      physics: { stabilization: { iterations: 180, updateInterval: 25 }, barnesHut: { gravitationalConstant: -3000 } },
      interaction: { hover: true, tooltipDelay: 100 },
    });
  }

  function citationHtml(datum) {
    const citations = datum.citations;
    if (!citations || !citations.length) return '';
    const skip = new Set(['count', 'citations', 'x', 'y', 'nct_id']);
    const labelKey = Object.keys(datum).find((k) => !skip.has(k) && !k.startsWith('_'));
    const label = datum.nct_id ?? (labelKey ? datum[labelKey] : 'selection');
    const cards = citations
      .map(({ nct_id, excerpt }) => `
        <div class="viz-cite-card">
          <a class="viz-cite-link" href="https://clinicaltrials.gov/study/${nct_id}" target="_blank" rel="noopener">${nct_id} ↗</a>
          <div class="viz-cite-excerpt">${escapeHtml(excerpt)}</div>
        </div>`)
      .join('');
    return `<div class="viz-cite-title">${citations.length} source trial${citations.length > 1 ? 's' : ''} for "${escapeHtml(String(label))}"</div>${cards}`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function metaHtml(meta) {
    if (!meta) return '';
    const badges = [
      `<span class="viz-badge">Total ${(meta.total_count ?? 0).toLocaleString()}</span>`,
      `<span class="viz-badge">Analyzed ${(meta.fetched_count ?? 0).toLocaleString()}</span>`,
      meta.count_verified ? '<span class="viz-badge verified">Verified</span>' : '',
      meta.truncated ? '<span class="viz-badge truncated">Sampled</span>' : '',
    ].join('');
    const warnings = (meta.warnings ?? []).map((w) => `<div class="viz-warning">⚠ ${escapeHtml(w)}</div>`).join('');
    return `<div class="viz-badges">${badges}</div>${warnings}`;
  }

  // Render a full visualization card into `container`. Returns a Promise.
  async function render(container, vizResponse) {
    const { visualization: viz, response_metadata: meta, message } = vizResponse;
    container.classList.add('viz-card');

    if (!viz) {
      container.innerHTML = `<div class="viz-empty">${escapeHtml(message || 'No matching data.')}</div>${metaHtml(meta)}`;
      return;
    }

    const uid = 'viz-' + Math.random().toString(36).slice(2);
    container.innerHTML = `
      <div class="viz-title">${escapeHtml(viz.title ?? '')}</div>
      <div class="viz-body" id="${uid}"></div>
      <div class="viz-citations" id="${uid}-cite"></div>
      ${metaHtml(meta)}
    `;
    const body = container.querySelector(`#${uid}`);
    const citeEl = container.querySelector(`#${uid}-cite`);

    if (viz.type === 'network_graph') {
      if (typeof vis === 'undefined') { renderFallback(body, viz); return; }
      body.style.height = '360px';
      renderNetwork(body, viz);
      return;
    }

    // Graceful degradation: if the Vega libraries didn't load (offline / blocked
    // CDN), fall back to a dependency-free bar rendering instead of an empty card.
    if (typeof vegaEmbed === 'undefined') { renderFallback(body, viz); return; }

    try {
      const spec = toVegaLite(viz);
      const result = await vegaEmbed(body, spec, {
        actions: { export: true, source: false, compiled: false, editor: false },
        renderer: 'svg',
      });
      const hasCitations = viz.data?.some((d) => d.citations?.length);
      if (hasCitations) {
        result.view.addEventListener('click', (_e, item) => {
          if (item?.datum?.citations?.length) citeEl.innerHTML = citationHtml(item.datum);
        });
        citeEl.innerHTML = '<div class="viz-cite-hint">Click a data point to see its source trials.</div>';
      }
    } catch (err) {
      renderFallback(body, viz);
    }
  }

  // Dependency-free fallback: horizontal CSS bars for aggregate charts, a compact
  // table for scatter, and a node list for networks. Keeps the answer useful even
  // when the charting library is unavailable.
  function renderFallback(body, viz) {
    if (viz.type === 'network_graph') {
      const nodes = (viz.nodes || []).slice(0, 12);
      body.innerHTML =
        '<div class="viz-fallback-note">Interactive graph unavailable — showing top entities.</div>' +
        nodes.map((n) => `<div class="viz-fb-row"><span class="viz-fb-label">${escapeHtml(n.label)}</span><span class="viz-fb-val">${n.weight}</span></div>`).join('');
      return;
    }
    const data = viz.data || [];
    if (!data.length) { body.innerHTML = '<div class="viz-fallback-note">No data.</div>'; return; }

    const xField = viz.encoding?.x?.field ?? Object.keys(data[0])[0];
    const yField = viz.encoding?.y?.field ?? 'count';
    const seriesField = viz.encoding?.series?.field;
    const vals = data.map((d) => Number(d[yField]) || 0);
    const max = Math.max(1, ...vals);
    const rows = data.slice(0, 24).map((d) => {
      const label = seriesField ? `${d[xField]} · ${d[seriesField]}` : d[xField];
      const v = Number(d[yField]) || 0;
      const pct = Math.round((v / max) * 100);
      return `<div class="viz-fb-row">
        <span class="viz-fb-label" title="${escapeHtml(String(label))}">${escapeHtml(String(label))}</span>
        <span class="viz-fb-bar"><span class="viz-fb-fill" style="width:${pct}%"></span></span>
        <span class="viz-fb-val">${v.toLocaleString()}</span>
      </div>`;
    }).join('');
    body.innerHTML = `<div class="viz-fallback-note">Chart library unavailable — showing ${yField} by ${xField}.</div>${rows}`;
  }

  window.VizRenderer = { render };
})();
