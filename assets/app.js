/* ============================================================
   A股事件筛选器 — 交互逻辑（无依赖）
   ============================================================ */
(function () {
  'use strict';

  var TYPES = [
    { key: 'increase', label: '增持', color: '#dd3b4b' },
    { key: 'decrease', label: '减持', color: '#109c60' },
    { key: 'placement', label: '定增', color: '#b8770a' },
    { key: 'repurchase', label: '回购', color: '#2b59ff' },
    { key: 'dividend', label: '分红', color: '#6c4cf1' }
  ];
  var TYPE_INDEX = {};
  TYPES.forEach(function (t, i) { TYPE_INDEX[t.key] = { label: t.label, color: t.color, order: i }; });

  var PAGE_SIZE = 25;
  var FAV_KEY = 'astock.favs.v1';
  var THEME_KEY = 'astock.theme';

  var DATA = window.ASTOCK_DATA || null;
  var EVENTS = (DATA && DATA.events) ? DATA.events.slice() : [];
  EVENTS.forEach(function (e) {
    if (!e.ratioLabel) e.ratioLabel = '占总股本%';
    if (e.amount == null) e.amount = null;
  });

  var TODAY = (DATA && DATA.tradeDate) ? DATA.tradeDate : new Date().toISOString().slice(0, 10);
  var TODAY_TS = new Date(TODAY + 'T00:00:00').getTime();

  var els = {
    typeChips: document.getElementById('typeChips'),
    q: document.getElementById('q'),
    board: document.getElementById('board'),
    minAmount: document.getElementById('minAmount'),
    minYield: document.getElementById('minYield'),
    status: document.getElementById('status'),
    sort: document.getElementById('sort'),
    favOnly: document.getElementById('favOnly'),
    rangeSeg: document.getElementById('rangeSeg'),
    kpis: document.getElementById('kpis'),
    tbody: document.getElementById('tbody'),
    mobileList: document.getElementById('mobileList'),
    pager: document.getElementById('pager'),
    resultCount: document.getElementById('resultCount'),
    resultHint: document.getElementById('resultHint'),
    chartTrend: document.getElementById('chartTrend'),
    chartDonut: document.getElementById('chartDonut'),
    drawer: document.getElementById('drawer'),
    drawerName: document.getElementById('drawerName'),
    drawerCode: document.getElementById('drawerCode'),
    drawerBody: document.getElementById('drawerBody'),
    scrim: document.getElementById('scrim'),
    toast: document.getElementById('toast'),
    sidebar: document.getElementById('sidebar'),
    modePill: document.getElementById('modePill'),
    updatePill: document.getElementById('updatePill'),
    sourceStatus: document.getElementById('sourceStatus'),
    btnFavView: document.getElementById('btnFavView')
  };

  var state = {
    q: '',
    types: [],
    board: '',
    days: 90,
    minAmount: 0,
    minYield: 0,
    status: '',
    sortKey: 'announceDate',
    sortDir: 'desc',
    favOnly: false,
    page: 1
  };

  var filtered = [];
  var favs = new Set(loadFavs());
  var tip = null;

  /* ---------------------------------------------------------- 工具 */

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function num(v) {
    return typeof v === 'number' && isFinite(v) ? v : null;
  }

  function fmtAmount(wan) {
    var v = num(wan);
    if (v == null) return '—';
    if (v >= 10000) return (v / 10000).toFixed(v >= 100000 ? 0 : 2) + '亿';
    if (v >= 1) return Math.round(v).toLocaleString('zh-CN') + '万';
    return v.toFixed(1) + '万';
  }

  function fmtShares(n) {
    var v = num(n);
    if (v == null) return '—';
    if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿股';
    if (v >= 1e4) return (v / 1e4).toFixed(v >= 1e6 ? 0 : 1) + '万股';
    return Math.round(v).toLocaleString('zh-CN') + '股';
  }

  function fmtPct(v, digits) {
    var n = num(v);
    if (n == null) return '—';
    return n.toFixed(digits == null ? 2 : digits) + '%';
  }

  function fmtDate(d, withYear) {
    if (!d) return '—';
    return withYear ? d : d.slice(5);
  }

  function tsOf(d) {
    return d ? new Date(d + 'T00:00:00').getTime() : 0;
  }

  function debounce(fn, wait) {
    var t;
    return function () {
      var args = arguments, ctx = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(ctx, args); }, wait);
    };
  }

  function toast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.add('on');
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { els.toast.classList.remove('on'); }, 1800);
  }

  function loadFavs() {
    try { return JSON.parse(localStorage.getItem(FAV_KEY) || '[]'); } catch (e) { return []; }
  }

  function saveFavs() {
    try { localStorage.setItem(FAV_KEY, JSON.stringify(Array.from(favs))); } catch (e) { /* 忽略隐私模式 */ }
  }

  function quoteUrl(code) {
    var prefix = code.charAt(0) === '6' ? 'sh' : (code.charAt(0) === '0' || code.charAt(0) === '3') ? 'sz' : 'bj';
    return 'https://quote.eastmoney.com/' + prefix + code + '.html';
  }

  /* ---------------------------------------------------------- 筛选 */

  function matches(ev, opts) {
    opts = opts || {};
    if (!opts.skipType && state.types.length && state.types.indexOf(ev.type) === -1) return false;
    if (!opts.skipFav && state.favOnly && !favs.has(ev.code)) return false;
    if (state.board && ev.board !== state.board) return false;
    if (state.status && ev.status !== state.status) return false;
    if (state.minAmount > 0 && (ev.amount == null || ev.amount < state.minAmount)) return false;
    if (state.days > 0) {
      var ref = tsOf(ev.announceDate || ev.startDate);
      if (!ref || TODAY_TS - ref > state.days * 86400000) return false;
    }
    if (state.minYield > 0) {
      var y = ev.type === 'dividend' ? (num(ev.dividendYield) != null ? ev.dividendYield : ev.ratio) : null;
      if (y == null || y < state.minYield) return false;
    }
    if (state.q) {
      var hay = (ev.code + ' ' + ev.name + ' ' + (ev.party || '') + ' ' + (ev.method || '')).toLowerCase();
      var tokens = state.q.toLowerCase().split(/\s+/).filter(Boolean);
      for (var i = 0; i < tokens.length; i++) {
        if (hay.indexOf(tokens[i]) === -1) return false;
      }
    }
    return true;
  }

  var COMPARATORS = {
    announceDate: function (a, b) { return tsOf(a.announceDate) - tsOf(b.announceDate); },
    amount: function (a, b) { return (a.amount == null ? -1 : a.amount) - (b.amount == null ? -1 : b.amount); },
    ratio: function (a, b) { return (a.ratio == null ? -1 : a.ratio) - (b.ratio == null ? -1 : b.ratio); },
    shares: function (a, b) { return (a.shares == null ? -1 : a.shares) - (b.shares == null ? -1 : b.shares); },
    changePct: function (a, b) { return (a.changePct == null ? -9999 : a.changePct) - (b.changePct == null ? -9999 : b.changePct); },
    name: function (a, b) { return String(a.name).localeCompare(String(b.name), 'zh-Hans-CN'); },
    code: function (a, b) { return String(a.code).localeCompare(String(b.code)); },
    type: function (a, b) { return TYPE_INDEX[a.type].order - TYPE_INDEX[b.type].order; }
  };

  function compute() {
    var list = EVENTS.filter(function (ev) { return matches(ev); });
    var cmp = COMPARATORS[state.sortKey] || COMPARATORS.announceDate;
    var dir = state.sortDir === 'asc' ? 1 : -1;
    list.sort(function (a, b) {
      var r = cmp(a, b) * dir;
      if (r !== 0) return r;
      return tsOf(b.announceDate) - tsOf(a.announceDate);
    });
    return list;
  }

  /* ---------------------------------------------------------- 渲染：筛选控件 */

  function renderTypeChips() {
    var base = EVENTS.filter(function (ev) { return matches(ev, { skipType: true }); });
    var counts = {};
    base.forEach(function (ev) { counts[ev.type] = (counts[ev.type] || 0) + 1; });

    els.typeChips.innerHTML = TYPES.map(function (t) {
      var on = state.types.indexOf(t.key) !== -1;
      return '<button type="button" class="chip" data-type="' + t.key + '" aria-pressed="' + on + '">' +
        t.label + '<span class="n">' + (counts[t.key] || 0) + '</span></button>';
    }).join('');
  }

  function renderStatusOptions() {
    var seen = {};
    EVENTS.forEach(function (ev) { if (ev.status) seen[ev.status] = (seen[ev.status] || 0) + 1; });
    var items = Object.keys(seen).sort(function (a, b) { return seen[b] - seen[a]; });
    var html = '<option value="">全部状态</option>' + items.map(function (s) {
      return '<option value="' + escapeHtml(s) + '"' + (s === state.status ? ' selected' : '') + '>' +
        escapeHtml(s) + '（' + seen[s] + '）</option>';
    }).join('');
    els.status.innerHTML = html;
  }

  function syncControls() {
    els.q.value = state.q;
    els.board.value = state.board;
    els.minAmount.value = String(state.minAmount);
    els.minYield.value = String(state.minYield);
    els.status.value = state.status;
    els.sort.value = state.sortKey + '-' + state.sortDir;
    els.favOnly.checked = state.favOnly;
    els.btnFavView.classList.toggle('is-on', state.favOnly);
    Array.prototype.forEach.call(els.rangeSeg.querySelectorAll('button'), function (b) {
      b.classList.toggle('is-active', Number(b.dataset.days) === state.days);
    });
    renderTypeChips();
  }

  /* ---------------------------------------------------------- 渲染：KPI */

  function renderKpis(list) {
    var byType = {};
    TYPES.forEach(function (t) { byType[t.key] = { count: 0, amount: 0, codes: new Set() }; });
    list.forEach(function (ev) {
      var bucket = byType[ev.type];
      if (!bucket) return;
      bucket.count++;
      bucket.amount += num(ev.amount) || 0;
      bucket.codes.add(ev.code);
    });

    var net = byType.increase.amount - byType.decrease.amount;
    var yieldSum = 0, yieldN = 0;
    list.forEach(function (ev) {
      if (ev.type === 'dividend' && num(ev.dividendYield) != null) { yieldSum += ev.dividendYield; yieldN++; }
    });

    var cards = [
      {
        key: '', label: '命中事件', accent: '#0d1a2d',
        value: list.length.toLocaleString('zh-CN'), unit: '条',
        sub: '涉及 ' + new Set(list.map(function (e) { return e.code; })).size + ' 只个股'
      },
      {
        key: 'increase', label: '股东增持', accent: '#dd3b4b',
        value: fmtAmount(byType.increase.amount).replace(/[万亿].*$/, ''), unit: /亿/.test(fmtAmount(byType.increase.amount)) ? '亿' : '万',
        sub: byType.increase.count + ' 条 · 净' + (net >= 0 ? '增持 ' : '减持 ') + fmtAmount(Math.abs(net))
      },
      {
        key: 'decrease', label: '股东减持', accent: '#109c60',
        value: fmtAmount(byType.decrease.amount).replace(/[万亿].*$/, ''), unit: /亿/.test(fmtAmount(byType.decrease.amount)) ? '亿' : '万',
        sub: byType.decrease.count + ' 条 · ' + byType.decrease.codes.size + ' 只个股'
      },
      {
        key: 'placement', label: '定增募资', accent: '#b8770a',
        value: fmtAmount(byType.placement.amount).replace(/[万亿].*$/, ''), unit: /亿/.test(fmtAmount(byType.placement.amount)) ? '亿' : '万',
        sub: byType.placement.count + ' 单 · ' + byType.placement.codes.size + ' 只个股'
      },
      {
        key: 'repurchase', label: '回购金额', accent: '#2b59ff',
        value: fmtAmount(byType.repurchase.amount).replace(/[万亿].*$/, ''), unit: /亿/.test(fmtAmount(byType.repurchase.amount)) ? '亿' : '万',
        sub: byType.repurchase.count + ' 条 · ' + byType.repurchase.codes.size + ' 只个股'
      },
      {
        key: 'dividend', label: '分红家数', accent: '#6c4cf1',
        value: String(byType.dividend.codes.size), unit: '家',
        sub: '平均股息率 ' + (yieldN ? (yieldSum / yieldN).toFixed(2) + '%' : '—') + ' · ' + byType.dividend.count + ' 条'
      }
    ];

    els.kpis.innerHTML = cards.map(function (c) {
      var on = c.key && state.types.length === 1 && state.types[0] === c.key;
      return '<button type="button" class="kpi' + (on ? ' is-on' : '') + '" data-kpi="' + c.key + '" style="--accent:' + c.accent + '">' +
        '<span class="k-label"><i class="dot" style="background:' + c.accent + '"></i>' + c.label + '</span>' +
        '<span class="k-value">' + c.value + '<small>' + c.unit + '</small></span>' +
        '<span class="k-sub">' + c.sub + '</span>' +
        '</button>';
    }).join('');
  }

  /* ---------------------------------------------------------- 渲染：表格 */

  function starSvg() {
    return '<svg viewBox="0 0 24 24" fill="none"><path d="M12 3.6l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8L3.5 9.8l5.9-.9L12 3.6z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>';
  }

  function typeTag(type) {
    var info = TYPE_INDEX[type] || { label: type, color: '#888' };
    return '<span class="tag ' + type + '">' + info.label + '</span>';
  }

  function renderTable() {
    var start = (state.page - 1) * PAGE_SIZE;
    var pageItems = filtered.slice(start, start + PAGE_SIZE);

    els.resultCount.textContent = filtered.length.toLocaleString('zh-CN');
    els.resultHint.textContent = filtered.length ? '第 ' + (start + 1) + '–' + Math.min(start + PAGE_SIZE, filtered.length) + ' 条' : '当前条件无匹配';

    if (!filtered.length) {
      els.tbody.innerHTML = '<tr><td colspan="10"><div class="empty"><h4>没有符合条件的事件</h4><p>试着放宽金额、时间范围，或清空类型筛选</p><button class="ghost-btn" data-act="reset">清空筛选条件</button></div></td></tr>';
      els.mobileList.innerHTML = '<div class="empty"><h4>没有符合条件的事件</h4><p>试着放宽金额、时间范围</p><button class="ghost-btn" data-act="reset">清空筛选条件</button></div>';
      els.pager.innerHTML = '';
      return;
    }

    els.tbody.innerHTML = pageItems.map(function (ev) {
      var fav = favs.has(ev.code);
      var amountText = num(ev.amount) == null ? '—' : (ev.amountEstimated ? '≈' : '') + fmtAmount(ev.amount);
      var qty = ev.qtyText ? ev.qtyText : fmtShares(ev.shares);
      return '<tr data-id="' + escapeHtml(ev.id) + '">' +
        '<td class="c-star"><button type="button" class="star-btn' + (fav ? ' is-on' : '') + '" data-star="' + ev.code + '" aria-label="收藏">' + starSvg() + '</button></td>' +
        '<td class="c-code">' + ev.code + '</td>' +
        '<td class="c-name"><span class="nm">' + escapeHtml(ev.name) + '</span><span class="bd">' + escapeHtml(ev.board) + '</span></td>' +
        '<td>' + typeTag(ev.type) + '</td>' +
        '<td class="c-party" title="' + escapeHtml(ev.party) + '">' + escapeHtml(ev.party) + '</td>' +
        '<td class="c-num">' + qty + '</td>' +
        '<td class="c-num">' + (num(ev.ratio) == null ? '—' : fmtPct(ev.ratio)) + '</td>' +
        '<td class="c-num strong">' + amountText + '</td>' +
        '<td class="c-date">' + fmtDate(ev.announceDate) + '</td>' +
        '<td class="c-status">' + escapeHtml(ev.status || '—') + '</td>' +
        '</tr>';
    }).join('');

    els.mobileList.innerHTML = pageItems.map(function (ev) {
      var fav = favs.has(ev.code);
      var amountText = num(ev.amount) == null ? '—' : (ev.amountEstimated ? '≈' : '') + fmtAmount(ev.amount);
      return '<div class="m-card" data-id="' + escapeHtml(ev.id) + '">' +
        '<div class="m-top"><div class="m-name"><b>' + escapeHtml(ev.name) + '</b><span>' + ev.code + '</span></div>' +
        '<div style="display:flex;align-items:center;gap:6px">' + typeTag(ev.type) +
        '<button type="button" class="star-btn' + (fav ? ' is-on' : '') + '" data-star="' + ev.code + '" aria-label="收藏">' + starSvg() + '</button></div></div>' +
        '<div class="m-grid">' +
        '<div>金额<b>' + amountText + '</b></div>' +
        '<div>' + (ev.ratioLabel || '占比').replace('%', '') + '<b>' + (num(ev.ratio) == null ? '—' : fmtPct(ev.ratio)) + '</b></div>' +
        '<div>公告日<b>' + fmtDate(ev.announceDate) + '</b></div>' +
        '</div>' +
        '<div class="m-party">' + escapeHtml(ev.party) + (ev.status ? ' · ' + escapeHtml(ev.status) : '') + '</div>' +
        '</div>';
    }).join('');

    renderPager();
  }

  function renderPager() {
    var pages = Math.ceil(filtered.length / PAGE_SIZE);
    if (pages <= 1) { els.pager.innerHTML = ''; return; }
    var cur = state.page;
    var nums = [];
    for (var i = 1; i <= pages; i++) {
      if (i === 1 || i === pages || Math.abs(i - cur) <= 1) nums.push(i);
      else if (nums[nums.length - 1] !== '…') nums.push('…');
    }
    els.pager.innerHTML =
      '<button type="button" data-page="' + (cur - 1) + '"' + (cur === 1 ? ' disabled' : '') + '>上一页</button>' +
      nums.map(function (n) {
        return n === '…' ? '<span class="ellipsis">…</span>'
          : '<button type="button" data-page="' + n + '" class="' + (n === cur ? 'is-active' : '') + '">' + n + '</button>';
      }).join('') +
      '<button type="button" data-page="' + (cur + 1) + '"' + (cur === pages ? ' disabled' : '') + '>下一页</button>';
  }

  /* ---------------------------------------------------------- 图表 */

  function ensureTip() {
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'chart-tip';
      document.body.appendChild(tip);
    }
    return tip;
  }

  function showTip(html, x, y) {
    var t = ensureTip();
    t.innerHTML = html;
    t.style.left = x + 'px';
    t.style.top = y + 'px';
    t.classList.add('on');
  }

  function hideTip() { if (tip) tip.classList.remove('on'); }

  function renderTrend(list) {
    var box = els.chartTrend;
    var W = box.clientWidth || 600;
    var H = box.clientHeight || 190;
    var days = 14;
    var pad = { l: 32, r: 6, t: 10, b: 22 };
    var innerW = Math.max(60, W - pad.l - pad.r);
    var innerH = Math.max(40, H - pad.t - pad.b);

    var buckets = [];
    for (var d = days - 1; d >= 0; d--) {
      var date = new Date(TODAY_TS - d * 86400000);
      var key = date.toISOString().slice(0, 10);
      buckets.push({ key: key, label: key.slice(5), items: {} });
    }
    var index = {};
    buckets.forEach(function (b) { index[b.key] = b; });

    list.forEach(function (ev) {
      var b = index[ev.announceDate];
      if (b) b.items[ev.type] = (b.items[ev.type] || 0) + 1;
    });

    var max = 1;
    buckets.forEach(function (b) {
      var total = 0;
      TYPES.forEach(function (t) { total += b.items[t.key] || 0; });
      b.total = total;
      if (total > max) max = total;
    });

    var slot = innerW / days;
    var barW = Math.max(6, Math.min(26, slot * 0.58));
    var svg = ['<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="近14日事件分布">'];

    for (var g = 0; g <= 3; g++) {
      var y = pad.t + innerH - (innerH * g / 3);
      var val = Math.round(max * g / 3);
      svg.push('<line x1="' + pad.l + '" y1="' + y + '" x2="' + (W - pad.r) + '" y2="' + y + '" stroke="currentColor" stroke-opacity="' + (g === 0 ? .18 : .08) + '" stroke-width="1"/>');
      svg.push('<text x="' + (pad.l - 6) + '" y="' + (y + 3.5) + '" text-anchor="end" font-size="9.5" fill="currentColor" fill-opacity=".42">' + val + '</text>');
    }

    buckets.forEach(function (b, i) {
      var x = pad.l + slot * i + (slot - barW) / 2;
      var acc = 0;
      TYPES.forEach(function (t) {
        var count = b.items[t.key] || 0;
        if (!count) return;
        var h = (count / max) * innerH;
        var y = pad.t + innerH - acc - h;
        svg.push('<rect x="' + x + '" y="' + y + '" width="' + barW + '" height="' + Math.max(1, h) + '" rx="' + Math.min(3, barW / 2) + '" fill="' + t.color + '" fill-opacity=".92"/>');
        acc += h;
      });
      if (i % 2 === 0 || i === buckets.length - 1) {
        svg.push('<text x="' + (x + barW / 2) + '" y="' + (H - 6) + '" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity=".42">' + b.label + '</text>');
      }
      // 悬浮热区
      svg.push('<rect class="hit" x="' + (pad.l + slot * i) + '" y="' + pad.t + '" width="' + slot + '" height="' + innerH + '" fill="transparent" data-i="' + i + '"/>');
    });

    svg.push('</svg>');
    box.innerHTML = svg.join('');

    Array.prototype.forEach.call(box.querySelectorAll('.hit'), function (hit) {
      hit.addEventListener('mousemove', function (e) {
        var b = buckets[Number(hit.dataset.i)];
        var rows = TYPES.filter(function (t) { return b.items[t.key]; })
          .map(function (t) { return '<span style="color:' + t.color + '">●</span> ' + t.label + ' ' + b.items[t.key]; })
          .join('　');
        showTip('<b>' + b.key + '</b>　共 ' + (b.total || 0) + ' 条<br>' + (rows || '无事件'), e.clientX, e.clientY - 6);
      });
      hit.addEventListener('mouseleave', hideTip);
    });
  }

  function renderDonut(list) {
    var sums = {}, total = 0;
    TYPES.forEach(function (t) { sums[t.key] = 0; });
    list.forEach(function (ev) {
      if (num(ev.amount) != null && sums[ev.type] != null) { sums[ev.type] += ev.amount; total += ev.amount; }
    });
    var useCount = total <= 0;
    if (useCount) {
      list.forEach(function (ev) { if (sums[ev.type] != null) { sums[ev.type] += 1; total += 1; } });
    }

    var size = 160, r = 62, cx = size / 2, cy = size / 2, C = 2 * Math.PI * r;
    var offset = 0;
    var arcs = [];
    TYPES.forEach(function (t) {
      var v = sums[t.key];
      if (!v) return;
      var frac = v / total;
      arcs.push('<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="' + t.color + '" stroke-width="18" ' +
        'stroke-dasharray="' + (frac * C - 2).toFixed(2) + ' ' + (C - frac * C + 2).toFixed(2) + '" ' +
        'stroke-dashoffset="' + (-offset * C).toFixed(2) + '" transform="rotate(-90 ' + cx + ' ' + cy + ')" stroke-linecap="butt"/>');
      offset += frac;
    });

    var centerValue = useCount ? total + ' 条' : fmtAmount(total);
    var legend = TYPES.map(function (t) {
      var v = sums[t.key];
      if (!v) return '';
      return '<li><i class="sw" style="background:' + t.color + '"></i><span>' + t.label + '</span>' +
        '<b class="val">' + (useCount ? v + ' 条' : fmtAmount(v)) + '</b></li>';
    }).join('');

    els.chartDonut.innerHTML =
      '<svg viewBox="0 0 ' + size + ' ' + size + '" width="' + size + '" height="' + size + '" role="img" aria-label="事件金额构成">' +
      '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="currentColor" stroke-opacity=".08" stroke-width="18"/>' +
      arcs.join('') +
      '<text x="' + cx + '" y="' + (cy - 2) + '" text-anchor="middle" class="donut-center-num">' + centerValue + '</text>' +
      '<text x="' + cx + '" y="' + (cy + 14) + '" text-anchor="middle" class="donut-center-lbl">' + (useCount ? '事件数' : '合计金额') + '</text>' +
      '</svg>' +
      '<ul class="donut-legend" style="list-style:none;margin:0;padding:0">' + (legend || '<li class="muted">暂无金额数据</li>') + '</ul>';
  }

  /* ---------------------------------------------------------- 详情抽屉 */

  function row(label, value) {
    return '<div class="row"><span>' + label + '</span><b>' + value + '</b></div>';
  }

  function openDrawer(id) {
    var ev = null;
    for (var i = 0; i < EVENTS.length; i++) { if (EVENTS[i].id === id) { ev = EVENTS[i]; break; } }
    if (!ev) return;

    els.drawerName.textContent = ev.name + ' · ' + (TYPE_INDEX[ev.type] || {}).label;
    els.drawerCode.textContent = ev.code + ' · ' + ev.board + ' · 公告 ' + (ev.announceDate || '—');

    var heroAmount = num(ev.amount) == null ? '—' : (ev.amountEstimated ? '≈' : '') + fmtAmount(ev.amount);
    var heroQty = ev.qtyText ? ev.qtyText : fmtShares(ev.shares);

    var rows = [
      row('事件类型', typeTag(ev.type)),
      row('进度状态', escapeHtml(ev.status || '—')),
      row(ev.type === 'dividend' ? '股息率（估算）' : '占总股本', num(ev.ratio) == null ? '—' : fmtPct(ev.ratio)),
      row('公告日期', ev.announceDate || '—')
    ];
    if (ev.startDate && ev.startDate !== ev.announceDate && ev.type !== 'dividend') rows.push(row('变动开始', ev.startDate));
    if (ev.endDate) rows.push(row('变动截止', ev.endDate));
    if (num(ev.price) != null) rows.push(row(ev.type === 'placement' ? '发行价' : '最新价', '¥' + ev.price.toFixed(2)));
    if (num(ev.changePct) != null) {
      var cls = ev.changePct >= 0 ? 'var(--up)' : 'var(--down)';
      rows.push(row('当日涨跌幅', '<span style="color:' + cls + '">' + (ev.changePct >= 0 ? '+' : '') + ev.changePct.toFixed(2) + '%</span>'));
    }
    if (ev.partyKind && ev.type !== 'repurchase') rows.push(row('变动方类型', escapeHtml(ev.partyKind)));

    // 类型专属信息
    if (ev.type === 'dividend') {
      if (num(ev.dividendPer10) != null) rows.push(row('每 10 股派现', ev.dividendPer10 + ' 元'));
      if (num(ev.bonusPer10)) rows.push(row('每 10 股送股', ev.bonusPer10 + ' 股'));
      if (num(ev.transferPer10)) rows.push(row('每 10 股转增', ev.transferPer10 + ' 股'));
      if (ev.recordDate) rows.push(row('股权登记日', ev.recordDate));
      if (ev.exDate) rows.push(row('除权除息日', ev.exDate));
      if (ev.reportPeriod) rows.push(row('报告期', ev.reportPeriod.slice(0, 4) + '-' + ev.reportPeriod.slice(4, 6) + '-' + ev.reportPeriod.slice(6)));
    }
    if (ev.type === 'repurchase') {
      if (num(ev.planAmountLow) != null || num(ev.planAmountHigh) != null) {
        rows.push(row('计划金额区间', fmtAmount(ev.planAmountLow) + ' ~ ' + fmtAmount(ev.planAmountHigh)));
      }
      if (num(ev.priceLow) != null || num(ev.priceHigh) != null) {
        rows.push(row('已回购价格区间', '¥' + (ev.priceLow || 0).toFixed(2) + ' ~ ¥' + (ev.priceHigh || 0).toFixed(2)));
      }
      if (num(ev.shares) != null) rows.push(row('已回购股数', fmtShares(ev.shares)));
    }
    if (ev.type === 'placement') {
      if (ev.method) rows.push(row('发行方式', escapeHtml(ev.method)));
      if (num(ev.premium) != null) rows.push(row('相对市价折溢价', (ev.premium > 0 ? '+' : '') + ev.premium.toFixed(2) + '%'));
      if (num(ev.shares) != null) rows.push(row('发行数量', fmtShares(ev.shares)));
      if (num(ev.lockup) != null) rows.push(row('锁定期', ev.lockup + ' 个月'));
    }
    if (ev.method && ev.type !== 'placement') rows.push(row('交易方式', escapeHtml(ev.method)));

    els.drawerBody.innerHTML =
      '<div class="d-hero">' +
      '<div class="box"><span>' + (ev.type === 'dividend' ? '预计派现总额' : '事件金额') + '</span><b>' + heroAmount + '</b></div>' +
      '<div class="box"><span>' + (ev.type === 'dividend' ? '分红方案' : '变动数量') + '</span><b style="font-size:15px">' + escapeHtml(heroQty) + '</b></div>' +
      '</div>' +
      '<div class="d-section"><h4>变动方 / 方案</h4><div class="d-list">' + row('名称', escapeHtml(ev.party || '—')) + '</div></div>' +
      '<div class="d-section"><h4>事件明细</h4><div class="d-list">' + rows.join('') + '</div></div>' +
      '<div class="d-actions">' +
      '<a class="ghost-btn" href="' + quoteUrl(ev.code) + '" target="_blank" rel="noopener">东方财富行情 ↗</a>' +
      '<button class="ghost-btn" data-copy="' + ev.code + '">复制代码</button>' +
      '<button class="ghost-btn" data-star="' + ev.code + '">' + (favs.has(ev.code) ? '取消自选' : '加入自选') + '</button>' +
      '</div>' +
      '<p class="d-note">金额' + (ev.amountEstimated ? '为估算值（按最新价或总股本推算）' : '为公告披露值') + '；数据源：' + escapeHtml(ev.source || '—') + '。请以交易所公告为准，本工具不构成投资建议。</p>';

    els.drawer.classList.add('on');
    els.drawer.setAttribute('aria-hidden', 'false');
    els.scrim.hidden = false;
    requestAnimationFrame(function () { els.scrim.classList.add('on'); });
    document.body.style.overflow = 'hidden';
  }

  function closeDrawer() {
    els.drawer.classList.remove('on');
    els.drawer.setAttribute('aria-hidden', 'true');
    els.scrim.classList.remove('on');
    document.body.style.overflow = '';
    setTimeout(function () { els.scrim.hidden = true; }, 220);
  }

  /* ---------------------------------------------------------- 状态同步 */

  function apply(resetPage) {
    if (resetPage !== false) state.page = 1;
    filtered = compute();
    renderKpis(filtered);
    renderTrend(filtered);
    renderDonut(filtered);
    renderTable();
    renderTypeChips();
    writeHash();
  }

  var writeHash = debounce(function () {
    var p = new URLSearchParams();
    if (state.q) p.set('q', state.q);
    if (state.types.length) p.set('t', state.types.join(','));
    if (state.board) p.set('b', state.board);
    if (state.days !== 90) p.set('d', String(state.days));
    if (state.minAmount) p.set('min', String(state.minAmount));
    if (state.minYield) p.set('y', String(state.minYield));
    if (state.status) p.set('st', state.status);
    if (state.sortKey !== 'announceDate' || state.sortDir !== 'desc') p.set('s', state.sortKey + '-' + state.sortDir);
    if (state.favOnly) p.set('fav', '1');
    if (state.page > 1) p.set('p', String(state.page));
    var hash = p.toString();
    if (location.hash.slice(1) !== hash) {
      history.replaceState(null, '', hash ? '#' + hash : location.pathname + location.search);
    }
  }, 250);

  function readHash() {
    var p = new URLSearchParams(location.hash.slice(1));
    if (p.get('q')) { state.q = p.get('q'); els.q.value = state.q; }
    if (p.get('t')) state.types = p.get('t').split(',').filter(function (k) { return TYPE_INDEX[k]; });
    if (p.get('b')) state.board = p.get('b');
    if (p.get('d')) state.days = Number(p.get('d')) || 0;
    if (p.get('min')) state.minAmount = Number(p.get('min')) || 0;
    if (p.get('y')) state.minYield = Number(p.get('y')) || 0;
    if (p.get('st')) state.status = p.get('st');
    if (p.get('s')) {
      var parts = p.get('s').split('-');
      if (COMPARATORS[parts[0]]) { state.sortKey = parts[0]; state.sortDir = parts[1] === 'asc' ? 'asc' : 'desc'; }
    }
    if (p.get('fav') === '1') state.favOnly = true;
    if (p.get('page') || p.get('p')) state.page = Number(p.get('page') || p.get('p')) || 1;
  }

  /* ---------------------------------------------------------- 顶部信息 */

  function renderHeader() {
    if (!DATA) {
      els.modePill.textContent = '无数据';
      els.modePill.className = 'pill is-bad';
      els.updatePill.innerHTML = '<span class="dot"></span>请先运行采集脚本';
      return;
    }
    var modeMap = {
      live: { text: '实时数据', cls: 'pill' },
      demo: { text: '演示数据', cls: 'pill is-demo' },
      degraded: { text: '数据降级', cls: 'pill is-bad' }
    };
    var m = modeMap[DATA.dataMode] || modeMap.live;
    els.modePill.textContent = m.text;
    els.modePill.className = m.cls;

    var gen = (DATA.generatedAt || '').replace('T', ' ').slice(5, 16);
    els.updatePill.innerHTML = '<span class="dot"></span>更新 ' + gen + ' · 近 ' + (DATA.lookbackDays || '—') + ' 天';

    var bad = (DATA.sources || []).filter(function (s) { return s.status === 'error'; });
    els.sourceStatus.textContent = (DATA.sources || []).map(function (s) {
      return s.name + '：' + (s.status === 'ok' ? s.message : s.status === 'demo' ? '演示' : s.status === 'skipped' ? '已关闭' : '采集失败');
    }).join('　|　') + (bad.length ? '　（部分数据源异常，已降级显示其它数据）' : '');
  }

  /* ---------------------------------------------------------- 事件绑定 */

  function bind() {
    els.q.addEventListener('input', debounce(function () {
      state.q = els.q.value.trim();
      apply();
    }, 180));

    els.typeChips.addEventListener('click', function (e) {
      var btn = e.target.closest('.chip');
      if (!btn) return;
      var key = btn.dataset.type;
      var i = state.types.indexOf(key);
      if (i === -1) state.types.push(key); else state.types.splice(i, 1);
      syncControls();
      apply();
    });

    els.kpis.addEventListener('click', function (e) {
      var card = e.target.closest('.kpi');
      if (!card) return;
      var key = card.dataset.kpi;
      if (!key) { state.types = []; }
      else if (state.types.length === 1 && state.types[0] === key) { state.types = []; }
      else { state.types = [key]; }
      syncControls();
      apply();
      toast(state.types.length ? '已筛选：' + TYPE_INDEX[state.types[0]].label : '已显示全部类型');
    });

    [els.board, els.minAmount, els.minYield, els.status].forEach(function (el) {
      el.addEventListener('change', function () {
        if (el === els.board) state.board = el.value;
        if (el === els.minAmount) state.minAmount = Number(el.value) || 0;
        if (el === els.minYield) state.minYield = Number(el.value) || 0;
        if (el === els.status) state.status = el.value;
        apply();
      });
    });

    els.sort.addEventListener('change', function () {
      var parts = els.sort.value.split('-');
      state.sortKey = parts[0];
      state.sortDir = parts[1];
      apply();
    });

    els.favOnly.addEventListener('change', function () {
      state.favOnly = els.favOnly.checked;
      els.btnFavView.classList.toggle('is-on', state.favOnly);
      apply();
      if (state.favOnly && !favs.size) toast('还没有自选股，点表格左侧的星标收藏');
    });

    els.rangeSeg.addEventListener('click', function (e) {
      var btn = e.target.closest('button');
      if (!btn) return;
      state.days = Number(btn.dataset.days);
      syncControls();
      apply();
    });

    els.btnFavView.addEventListener('click', function () {
      els.favOnly.checked = !els.favOnly.checked;
      els.favOnly.dispatchEvent(new Event('change'));
    });

    document.getElementById('btnReset').addEventListener('click', resetAll);

    document.addEventListener('click', function (e) {
      var resetBtn = e.target.closest('[data-act="reset"]');
      if (resetBtn) { resetAll(); return; }

      var star = e.target.closest('[data-star]');
      if (star) {
        e.stopPropagation();
        var code = star.dataset.star;
        if (favs.has(code)) { favs.delete(code); toast('已移出自选'); }
        else { favs.add(code); toast('已加入自选'); }
        saveFavs();
        renderTable();
        if (els.drawer.classList.contains('on')) {
          var id = els.drawer.dataset.id;
          if (id) openDrawer(id);
        }
        apply(false);
        return;
      }

      var copy = e.target.closest('[data-copy]');
      if (copy) {
        var text = copy.dataset.copy;
        if (navigator.clipboard) navigator.clipboard.writeText(text).then(function () { toast('已复制 ' + text); });
        else toast(text);
        return;
      }

      var pageBtn = e.target.closest('[data-page]');
      if (pageBtn && !pageBtn.disabled) {
        state.page = Number(pageBtn.dataset.page);
        filtered = compute();
        renderTable();
        writeHash();
        window.scrollTo({ top: els.pager.getBoundingClientRect().top + window.scrollY - 240, behavior: 'smooth' });
        return;
      }

      var rowEl = e.target.closest('tr[data-id], .m-card[data-id]');
      if (rowEl) {
        els.drawer.dataset.id = rowEl.dataset.id;
        openDrawer(rowEl.dataset.id);
        return;
      }

      var sortTh = e.target.closest('th[data-sort]');
      if (sortTh) {
        var key = sortTh.dataset.sort;
        if (!COMPARATORS[key]) return;
        if (state.sortKey === key) state.sortDir = state.sortDir === 'desc' ? 'asc' : 'desc';
        else { state.sortKey = key; state.sortDir = key === 'name' || key === 'code' ? 'asc' : 'desc'; }
        els.sort.value = state.sortKey + '-' + state.sortDir;
        apply();
        markSortHeaders();
      }
    });

    document.getElementById('btnDrawerClose').addEventListener('click', closeDrawer);
    els.scrim.addEventListener('click', function () { closeDrawer(); if (window.innerWidth <= 980) toggleSidebar(false); });

    document.getElementById('btnCsv').addEventListener('click', exportCsv);

    document.getElementById('btnTheme').addEventListener('click', function () {
      var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      setTheme(next);
    });

    document.getElementById('btnReload').addEventListener('click', reloadData);

    document.getElementById('btnFilterMobile').addEventListener('click', function () {
      toggleSidebar(!els.sidebar.classList.contains('on'));
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if (els.drawer.classList.contains('on')) closeDrawer();
        else toggleSidebar(false);
      }
      if (e.key === '/' && document.activeElement !== els.q && !/input|select|textarea/i.test(document.activeElement.tagName)) {
        e.preventDefault();
        els.q.focus();
      }
    });

    window.addEventListener('resize', debounce(function () {
      renderTrend(filtered);
    }, 200));

    window.addEventListener('hashchange', function () {
      readHash();
      syncControls();
      apply(false);
    });
  }

  function markSortHeaders() {
    Array.prototype.forEach.call(document.querySelectorAll('th[data-sort]'), function (th) {
      var on = th.dataset.sort === state.sortKey;
      th.classList.toggle('is-sorted', on);
      var arrow = th.querySelector('.arrow');
      if (!arrow) {
        arrow = document.createElement('span');
        arrow.className = 'arrow';
        th.appendChild(arrow);
      }
      arrow.textContent = on ? (state.sortDir === 'desc' ? '▾' : '▴') : '';
    });
  }

  function toggleSidebar(open) {
    els.sidebar.classList.toggle('on', open);
    document.getElementById('btnFilterMobile').setAttribute('aria-expanded', String(!!open));
    if (open) {
      els.scrim.hidden = false;
      requestAnimationFrame(function () { els.scrim.classList.add('on'); });
    } else if (!els.drawer.classList.contains('on')) {
      els.scrim.classList.remove('on');
      setTimeout(function () { if (!els.drawer.classList.contains('on') && !els.sidebar.classList.contains('on')) els.scrim.hidden = true; }, 200);
    }
  }

  function resetAll() {
    state = { q: '', types: [], board: '', days: 90, minAmount: 0, minYield: 0, status: '', sortKey: 'announceDate', sortDir: 'desc', favOnly: false, page: 1 };
    syncControls();
    if (location.hash) history.replaceState(null, '', location.pathname + location.search);
    apply();
    toast('已清空筛选条件');
    if (window.innerWidth <= 980) toggleSidebar(false);
  }

  function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* ignore */ }
  }

  function reloadData() {
    var url = 'data/latest.json?v=' + Date.now();
    fetch(url, { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (json) {
        DATA = json;
        EVENTS = json.events || [];
        TODAY = json.tradeDate || TODAY;
        TODAY_TS = new Date(TODAY + 'T00:00:00').getTime();
        renderHeader();
        renderStatusOptions();
        apply(false);
        toast('数据已刷新');
      })
      .catch(function () {
        toast('刷新失败：请通过 http 服务打开页面');
      });
  }

  function exportCsv() {
    var head = ['代码', '名称', '板块', '类型', '变动方/方案', '数量(股)', '占总股本%', '股息率%', '金额(万元)', '公告日', '状态', '起始日', '结束日', '数据源'];
    var lines = [head.join(',')];
    filtered.forEach(function (ev) {
      var cells = [
        ev.code, '"' + ev.name + '"', ev.board, (TYPE_INDEX[ev.type] || {}).label,
        '"' + String(ev.party || '').replace(/"/g, '""') + '"',
        ev.shares == null ? '' : Math.round(ev.shares),
        ev.ratio == null ? '' : ev.ratio,
        ev.dividendYield == null ? '' : ev.dividendYield,
        ev.amount == null ? '' : Math.round(ev.amount),
        ev.announceDate || '', ev.status || '', ev.startDate || '', ev.endDate || '', ev.source || ''
      ];
      lines.push(cells.join(','));
    });
    var blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'A股事件筛选_' + TODAY + '.csv';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 300);
    toast('已导出 ' + filtered.length + ' 条');
  }

  /* ---------------------------------------------------------- 启动 */

  function init() {
    try {
      var saved = localStorage.getItem(THEME_KEY);
      if (saved === 'dark' || saved === 'light') setTheme(saved);
    } catch (e) { /* ignore */ }

    renderHeader();
    if (!DATA || !EVENTS.length) {
      els.kpis.innerHTML = '';
      els.tbody.innerHTML = '<tr><td colspan="10"><div class="empty"><h4>还没有数据</h4>' +
        '<p>在仓库根目录运行 <code>python scripts/fetch_data.py</code> 生成数据，或先运行 <code>python scripts/fetch_data.py --demo</code> 预览界面。</p></div></td></tr>';
      els.mobileList.innerHTML = els.tbody.innerHTML;
      if (els.status) renderStatusOptions();
      return;
    }

    readHash();
    renderStatusOptions();
    syncControls();
    bind();
    apply(false);
    markSortHeaders();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
