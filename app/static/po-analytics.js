/* Chart.js untuk halaman /po-analytics.
   Prinsip:
   - Data dibaca dari <script type="application/json"> via JSON.parse(textContent).
     Tidak ada innerHTML, tidak ada eval, tidak ada string HTML dari server.
   - Palet diambil dari getComputedStyle() supaya otomatis mengikuti light/dark.
   - darkmode.js tidak memancarkan event, jadi MutationObserver pada atribut
     class <html> yang memicu render ulang.
   - Kalau Chart.js gagal dimuat (CDN mati / offline), canvas disembunyikan dan
     tabel angka yang sudah ada di HTML tetap dipakai. */
(function () {
  'use strict';

  var DATA_ID = 'poAnalyticsData';
  var charts = [];
  var palette = null;

  function readData() {
    var el = document.getElementById(DATA_ID);
    if (!el) return null;
    try { return JSON.parse(el.textContent); }
    catch (e) { console.error('[analytics] data chart tidak valid:', e); return null; }
  }

  function css(name, fallback) {
    var v = getComputedStyle(document.body).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }

  function buildPalette() {
    var dark = document.documentElement.classList.contains('dark');
    var text = dark ? '#e2e8f0' : '#1f2937';
    var muted = dark ? '#94a3b8' : '#6b7280';
    var grid = dark ? 'rgba(148,163,184,0.18)' : 'rgba(107,114,128,0.16)';
    var series = dark
      ? ['#818cf8', '#34d399', '#fbbf24', '#f472b6']
      : ['#4f46e5', '#059669', '#d97706', '#db2777'];
    return { dark: dark, text: text, muted: muted, grid: grid, series: series };
  }

  function destroyAll() {
    charts.forEach(function (c) { if (c) c.destroy(); });
    charts = [];
  }

  function baseOpts(p) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { labels: { color: p.text, boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          backgroundColor: p.dark ? '#0f172a' : '#111827',
          titleColor: '#fff', bodyColor: '#fff', padding: 8, cornerRadius: 6,
        },
      },
      scales: {
        x: { ticks: { color: p.muted, font: { size: 11 } }, grid: { color: p.grid } },
        y: { beginAtZero: true, ticks: { color: p.muted, font: { size: 11 } }, grid: { color: p.grid } },
      },
    };
  }

  function fmt(n) {
    return new Intl.NumberFormat('id-ID').format(n || 0);
  }

  function make(id, config) {
    var el = document.getElementById(id);
    if (!el || !window.Chart) return null;
    try { charts.push(new window.Chart(el.getContext('2d'), config)); }
    catch (e) { console.error('[analytics] gagal membuat chart ' + id + ':', e); }
    return null;
  }

  function render() {
    var data = readData();
    if (!data) return;
    destroyAll();
    palette = buildPalette();
    var p = palette;

    // 1) Jumlah PO per kuartal + qty pcs (sumbu kanan).
    //    Kalau satu kuartal dipilih, batang lain diredupkan supaya fokus.
    var qSel = data.qtr || null;
    var barColors = (data.qLabels || []).map(function (_, i) {
      var idx = i + 1;
      var base = p.series[0];
      if (!qSel) return base;
      return idx === qSel ? base : p.muted;
    });
    var o1 = baseOpts(p);
    o1.scales.y.title = { display: true, text: 'Jumlah PO', color: p.muted, font: { size: 10 } };
    o1.scales.y1 = {
      beginAtZero: true, position: 'right', grid: { drawOnChartArea: false },
      ticks: { color: p.muted, font: { size: 10 }, callback: function (v) { return fmt(v); } },
    };
    make('chartQuarter', {
      type: 'bar',
      data: {
        labels: data.qLabels,
        datasets: [
          {
            label: 'Jumlah PO', data: data.qPo, backgroundColor: barColors,
            borderRadius: 4, yAxisID: 'y', order: 2,
          },
          {
            label: 'Qty (pcs)', data: data.qPcs, type: 'line', borderColor: p.series[1],
            backgroundColor: p.series[1], pointRadius: 3, borderWidth: 2, tension: 0.25,
            yAxisID: 'y1', order: 1,
          },
        ],
      },
      options: o1,
    });

    // 2) Jumlah PO per kuartal per perusahaan
    var ds = (data.companies || []).map(function (c, i) {
      var vals = (data.companyPo && data.companyPo[c]) || [0, 0, 0, 0];
      return {
        label: c,
        data: vals,
        // Sama seperti di atas: redupkan kuartal yang tidak dipilih.
        backgroundColor: vals.map(function (_, qi) {
          return (qSel && qi + 1 !== qSel) ? p.muted : p.series[i % p.series.length];
        }),
        borderRadius: 4,
      };
    });
    make('chartQuarterCompany', {
      type: 'bar',
      data: { labels: data.qLabels, datasets: ds },
      options: baseOpts(p),
    });

    // 3) Proporsi PO per perusahaan (donat)
    var totals = data.companies || [];
    var vals = totals.map(function (c) { return (data.companyTotals && data.companyTotals[c]) || 0; });
    // Jumlah PO ikut ditulis di label legenda supaya informasinya terlihat tanpa
    // hover (terutama kalau satu perusahaan saja yang punya PO).
    var labels = totals.map(function (c, i) { return c + ' (' + fmt(vals[i]) + ')'; });
    make('chartCompany', {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{
          data: vals,
          backgroundColor: totals.map(function (_, i) { return p.series[i % p.series.length]; }),
          borderWidth: 0,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, cutout: '58%',
        plugins: {
          legend: { position: 'bottom', labels: { color: p.text, boxWidth: 12, font: { size: 11 } } },
          tooltip: {
            backgroundColor: p.dark ? '#0f172a' : '#111827',
            titleColor: '#fff', bodyColor: '#fff', padding: 8, cornerRadius: 6,
            callbacks: {
              label: function (c) {
                var i = c.dataIndex;
                return (data.companies[i] || '') + ': ' + fmt(c.parsed) + ' PO';
              },
            },
          },
        },
      },
    });

    // 4) & 5) Daftar top (horizontal bar). Nilai mengikuti basis urutan aktif:
    //      sort=pcs -> total qty, sort=po -> jumlah PO.
    var byPo = data.sort === 'po';
    horizontal('chartTop', data.topLabels, byPo ? data.topPo : data.topValues, p, byPo ? 'Jumlah PO' : 'Qty (pcs)');
    horizontal('chartMissing', data.missingLabels, byPo ? data.missingPo : data.missingValues, p, byPo ? 'Jumlah PO' : 'Qty (pcs)');
  }

  function horizontal(id, labels, values, p, axisLabel) {
    if (!labels || !labels.length) return;
    var o = baseOpts(p);
    o.indexAxis = 'y';
    o.plugins.legend.display = false;
    o.scales = {
      x: {
        beginAtZero: true,
        title: { display: true, text: axisLabel || '', color: p.muted, font: { size: 10 } },
        ticks: { color: p.muted, font: { size: 10 }, callback: function (v) { return fmt(v); } },
        grid: { color: p.grid },
      },
      y: { ticks: { color: p.text, font: { size: 10 } }, grid: { display: false } },
    };
    make(id, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: axisLabel || '', data: values,
          backgroundColor: p.dark ? 'rgba(129,140,248,0.75)' : 'rgba(79,70,229,0.8)',
          borderRadius: 4,
        }],
      },
      options: o,
    });
  }

  function showFallback(reason) {
    // Chart tidak tersedia -> sembunyikan canvas, tabel angka tetap tampil.
    ['chartQuarter', 'chartCompany', 'chartQuarterCompany', 'chartTop', 'chartMissing']
      .forEach(function (id) {
        var el = document.getElementById(id);
        if (el && el.parentNode) el.parentNode.style.display = 'none';
      });
    if (reason && !document.getElementById('poChartNotice')) {
      var n = document.createElement('p');
      n.id = 'poChartNotice';
      n.className = 'mb-4 rounded-md bg-gray-50 border border-gray-200 px-4 py-2 text-xs text-gray-500';
      n.textContent = 'Grafik tidak dimuat (' + reason + '). Data tetap bisa dibaca di tabel.';
      var host = document.querySelector('main');
      if (host && host.firstChild) host.insertBefore(n, host.firstChild.nextSibling);
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById(DATA_ID)) return;
    if (!window.Chart) {
      showFallback('Chart.js tidak tersedia');
      return;
    }
    try {
      render();
    } catch (e) {
      console.error('[analytics] render gagal:', e);
      showFallback('render gagal');
      return;
    }
    // Render ulang saat tema berubah (darkmode.js hanya men-toggle class).
    var root = document.documentElement;
    if (window.MutationObserver) {
      new MutationObserver(function () {
        if (palette && palette.dark !== document.documentElement.classList.contains('dark')) render();
      }).observe(root, { attributes: true, attributeFilter: ['class'] });
    }
  });
})();
