/* 쉼표 지역 현황 (지자체·보험사 담당자용). /api/dongs(관악구 행정동 경계)를 한 번, /api/report를 시각마다 부른다.
   시연 모드에서는 라이더 앱(index.html) 시연 패널의 시각을 BroadcastChannel로 받아 따라간다.
   두 창을 나란히 띄우면 시각을 옮기거나 쉼을 시작·끝낼 때마다 이 화면도 다시 그린다.
   32도 판정, 단계 이름은 서버가 준 값(hot, stage)을 그대로 쓴다. 색만 여기서 정한다. */
(function () {
  "use strict";
  var S = { cfg: null, min: 840, linked: false, geo: null, unitPx: 0.5, last: null };
  var board = document.getElementById("board"), when = document.getElementById("when"), sync = document.getElementById("sync");

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function hhmm(m) { return pad(Math.floor(m / 60)) + ":" + pad(m % 60); }
  function won(x) { return Math.round(x).toLocaleString("ko-KR") + "원"; }
  function num(x) { return (+x).toLocaleString("ko-KR"); }
  function esc(t) { return String(t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  // 색: 32도 구간은 서버가 반올림 전 값으로 정한 hot을 쓴다 (화면의 32.0이 31.96일 수 있다)
  function heat(t, hot) {
    if (t == null) return "var(--cool)";
    if (t >= 38) return "#a82c0c";
    if (t >= 36.5) return "var(--ember)";
    if (t >= 35) return "var(--amber)";
    if (t >= 33.5) return "#f5a83a";
    if (hot) return "var(--sun)";
    if (t >= 31) return "var(--warm)";
    return "var(--cool)";
  }
  function api(path, params) {
    if (S.cfg.demo) params.at = hhmm(S.min);
    var qs = Object.keys(params).map(function (k) { return k + "=" + encodeURIComponent(params[k]); }).join("&");
    return fetch("/api/" + path + "?" + qs).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || "요청을 처리하지 못했어요."); return j; });
    });
  }

  // ---------- 지도: 경도·위도를 평면으로 (관악구는 좁아서 위도 보정만 하면 된다) ----------
  function project(geo) {
    var xs = [], ys = [];
    geo.features.forEach(function (f) { rings(f.geometry).forEach(function (r) { r.forEach(function (p) { xs.push(p[0]); ys.push(p[1]); }); }); });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    var k = Math.cos((y0 + y1) / 2 * Math.PI / 180), W = 1000, s = W / ((x1 - x0) * k), H = Math.round((y1 - y0) * s);
    function pt(p) { return [(p[0] - x0) * k * s, (y1 - p[1]) * s]; }
    geo.features.forEach(function (f) {
      f.d = rings(f.geometry).map(function (r) { return "M" + r.map(function (p) { var q = pt(p); return q[0].toFixed(1) + "," + q[1].toFixed(1); }).join("L") + "Z"; }).join("");
      var outer = outers(f.geometry).map(function (r) { return r.map(pt); });
      var big = outer.reduce(function (a, b) { return Math.abs(area(b)) > Math.abs(area(a)) ? b : a; });
      var pole = poleOf(big);
      f.anchor = pole.p; f.room = pole.r;   // 이름 자리: 경계에서 가장 먼 점과 그 거리 (중심 좌표는 오목한 동에서 밖으로 나가거나 이웃과 겹친다)
    });
    geo.w = W; geo.h = H;
    return geo;
  }
  function rings(g) {
    var polys = g.type === "MultiPolygon" ? g.coordinates : [g.coordinates], out = [];
    polys.forEach(function (p) { p.forEach(function (r) { out.push(r); }); });
    return out;
  }
  function outers(g) { return (g.type === "MultiPolygon" ? g.coordinates : [g.coordinates]).map(function (p) { return p[0]; }); }
  function area(r) { var a = 0; for (var i = 0, j = r.length - 1; i < r.length; j = i++) a += (r[j][0] + r[i][0]) * (r[j][1] - r[i][1]); return a / 2; }
  function inside(p, r) {
    var hit = false;
    for (var i = 0, j = r.length - 1; i < r.length; j = i++) {
      if ((r[i][1] > p[1]) !== (r[j][1] > p[1]) && p[0] < (r[j][0] - r[i][0]) * (p[1] - r[i][1]) / (r[j][1] - r[i][1]) + r[i][0]) hit = !hit;
    }
    return hit;
  }
  function edgeDist(p, r) {
    var best = Infinity;
    for (var i = 0, j = r.length - 1; i < r.length; j = i++) {
      var ax = r[j][0], ay = r[j][1], dx = r[i][0] - ax, dy = r[i][1] - ay, L = dx * dx + dy * dy;
      var u = L ? Math.max(0, Math.min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L)) : 0;
      best = Math.min(best, Math.hypot(p[0] - ax - u * dx, p[1] - ay - u * dy));
    }
    return best;
  }
  // 다각형 안에서 경계까지 가장 먼 점 (격자로 찾고 그 주변을 한 번 더 좁혀 찾는다)
  function poleOf(r) {
    var xs = r.map(function (p) { return p[0]; }), ys = r.map(function (p) { return p[1]; });
    var bx0 = Math.min.apply(null, xs), bx1 = Math.max.apply(null, xs), by0 = Math.min.apply(null, ys), by1 = Math.max.apply(null, ys);
    var best = { p: [(bx0 + bx1) / 2, (by0 + by1) / 2], r: 0 }, step = Math.max(bx1 - bx0, by1 - by0) / 24;
    for (var pass = 0; pass < 2; pass++) {
      var cx = best.p[0], cy = best.p[1], span = pass ? step * 2 : null;
      var xa = pass ? cx - span : bx0, xb = pass ? cx + span : bx1, ya = pass ? cy - span : by0, yb = pass ? cy + span : by1, st = pass ? step / 6 : step;
      for (var x = xa; x <= xb; x += st) for (var y = ya; y <= yb; y += st) {
        var q = [x, y];
        if (!inside(q, r)) continue;
        var d = edgeDist(q, r);
        if (d > best.r) best = { p: q, r: d };
      }
    }
    return best;
  }

  // 동 이름표 배치: 화면에서 9~13px로 보이게 크기를 정하고, 겹치면 서로 밀어낸다. 지도 밖으로 나가지 않게 가둔다.
  function layoutLabels(g, unitPx) {
    var mapPx = unitPx * (g.w + 20), minF = 9 / unitPx, maxF = (mapPx < 440 ? 11 : 13) / unitPx, pad = 2 / unitPx;   // 좁은 화면은 크기 차이를 줄인다
    var L = g.features.map(function (f) {
      var n = f.name.length, fs = Math.max(minF, Math.min(maxF, 2.2 * f.room / n));
      return { f: f, fs: fs, x: f.anchor[0], y: f.anchor[1], w: Math.max(n, 2.6) * fs * 1.1 + pad, h: fs * 2.45 + pad };   // 실제 글자 상자보다 조금 넉넉히
    });
    for (var it = 0; it < 400; it++) {
      var moved = false;
      for (var i = 0; i < L.length; i++) for (var j = i + 1; j < L.length; j++) {
        var a = L[i], b = L[j], ox = (a.w + b.w) / 2 - Math.abs(a.x - b.x), oy = (a.h + b.h) / 2 - Math.abs(a.y - b.y);
        if (ox <= 0 || oy <= 0) continue;
        moved = true;
        if (oy <= ox) { var sy = (a.y < b.y ? -1 : 1) * (oy / 2 + 0.5); a.y += sy; b.y -= sy; }
        else { var sx = (a.x < b.x ? -1 : 1) * (ox / 2 + 0.5); a.x += sx; b.x -= sx; }
      }
      L.forEach(function (l) {
        l.x = Math.max(l.w / 2, Math.min(g.w - l.w / 2, l.x));
        l.y = Math.max(l.h / 2, Math.min(g.h - l.h / 2, l.y));
      });
      if (!moved) break;
    }
    return L;
  }

  function mapSvg(r) {
    var by = {}; r.dongs.forEach(function (d) { by[d.code] = d; });
    var g = S.geo, paths = "", me = "";
    g.features.forEach(function (f) {
      var d = by[f.code] || {}, t = d.temp;
      var tip = f.name + " " + (t == null ? "값 없음" : t.toFixed(1) + "도") + ", 오늘 보전 " + (d.paid_hours || 0) + "시간 " + won(d.amount || 0);
      var path = '<path d="' + f.d + '" fill="' + heat(t, d.hot) + '" class="dong' + (d.me ? " me" : "") + '"><title>' + esc(tip) + '</title></path>';
      if (d.me) me = path; else paths += path;
    });
    return '<svg class="dongmap" viewBox="-10 -10 ' + (g.w + 20) + ' ' + (g.h + 20) + '" role="img" aria-label="관악구 행정동별 체감온도">' +
      paths + me + '<g class="labels">' + labelsSvg(r) + '</g></svg>';
  }
  function labelsSvg(r) {
    var by = {}; r.dongs.forEach(function (d) { by[d.code] = d; });
    return layoutLabels(S.geo, S.unitPx).map(function (l) {
      var t = (by[l.f.code] || {}).temp, x = l.x.toFixed(1);
      return '<text x="' + x + '" y="' + l.y.toFixed(1) + '" font-size="' + l.fs.toFixed(1) + '" class="' + (t != null && t >= 31 ? "" : "lite") + '">' +
        '<tspan x="' + x + '" dy="-0.25em">' + esc(l.f.name) + '</tspan><tspan x="' + x + '" dy="1.1em" class="fig">' + (t == null ? "-" : t.toFixed(1)) + '</tspan></text>';
    }).join("");
  }
  // 지도가 실제로 그려진 폭으로 글자 크기를 다시 맞춘다 (첫 그림은 화면 폭으로 짐작한 값)
  function fitLabels(r) {
    var svg = board.querySelector(".dongmap");
    if (!svg) return;
    var px = svg.getBoundingClientRect().width / (S.geo.w + 20);
    if (px > 0 && Math.abs(px - S.unitPx) / S.unitPx > 0.03) {
      S.unitPx = px;
      svg.querySelector(".labels").innerHTML = labelsSvg(r);
    }
  }



  // 도넛: [{label, value, color}] — 가운데에 총합이나 한 줄을 넣는다
  function donutSvg(parts, centerTop, centerBottom) {
    var total = parts.reduce(function (a, p) { return a + p.value; }, 0) || 1;
    var R = 54, r = 34, cx = 62, cy = 62, acc = -Math.PI / 2, out = "";
    parts.forEach(function (p) {
      if (p.value <= 0) return;
      var ang = (p.value / total) * Math.PI * 2, end = acc + ang, big = ang > Math.PI ? 1 : 0;
      var x1 = cx + R * Math.cos(acc), y1 = cy + R * Math.sin(acc), x2 = cx + R * Math.cos(end), y2 = cy + R * Math.sin(end);
      var x3 = cx + r * Math.cos(end), y3 = cy + r * Math.sin(end), x4 = cx + r * Math.cos(acc), y4 = cy + r * Math.sin(acc);
      out += '<path d="M' + x1.toFixed(1) + ' ' + y1.toFixed(1) + 'A' + R + ' ' + R + ' 0 ' + big + ' 1 ' + x2.toFixed(1) + ' ' + y2.toFixed(1) +
        'L' + x3.toFixed(1) + ' ' + y3.toFixed(1) + 'A' + r + ' ' + r + ' 0 ' + big + ' 0 ' + x4.toFixed(1) + ' ' + y4.toFixed(1) + 'Z" fill="' + p.color + '"/>';
      acc = end;
    });
    if (centerTop) out += '<text x="' + cx + '" y="' + (cy + (centerBottom ? -2 : 6)) + '" text-anchor="middle" font-size="20" font-weight="800" fill="var(--ink)">' + centerTop + '</text>';
    if (centerBottom) out += '<text x="' + cx + '" y="' + (cy + 16) + '" text-anchor="middle" font-size="11" fill="var(--mute)">' + centerBottom + '</text>';
    return '<svg class="donut" viewBox="0 0 124 124" role="img">' + out + '</svg>';
  }

  // 진행 막대 한 줄
  function barRow(label, value, max, color, right) {
    var pct = Math.max(0, Math.min(100, max > 0 ? (value / max) * 100 : 0));
    return '<div class="brow"><div class="brow-top"><span>' + label + '</span><b>' + right + '</b></div>' +
      '<div class="btrack"><i style="width:' + pct.toFixed(1) + '%;background:' + color + '"></i></div></div>';
  }

  // 오늘 시간별 추이: 막대는 폭염 속 운행 시간, 점·선은 그 시각에 쉬고 있던 라이더
  function trendSvg(r) {
    var hs = r.hours || [];
    if (!hs.length) return "";
    var W = 920, H = 200, L = 46, R = 44, T = 16, B = 30;
    var iw = W - L - R, ih = H - T - B, n = hs.length, bw = iw / n;
    var rawHot = Math.max(1, Math.max.apply(null, hs.map(function (x) { return x.hot_hours; })));
    var step = Math.pow(10, Math.floor(Math.log(rawHot) / Math.LN10)) / 2;   // 눈금을 읽기 좋은 수로 올린다
    var maxHot = Math.ceil(rawHot / step) * step;
    var maxRest = Math.max(1, Math.max.apply(null, hs.map(function (x) { return x.resting; })));
    var now = r.now_hour, out = "";
    // 가로 눈금
    [0, 0.5, 1].forEach(function (f) {
      var y = T + ih - ih * f;
      out += '<line x1="' + L + '" y1="' + y + '" x2="' + (W - R) + '" y2="' + y + '" stroke="#e7eef6" stroke-width="1"/>' +
        '<text x="' + (L - 8) + '" y="' + (y + 5) + '" text-anchor="end" font-size="12" fill="#8fa2b8">' + Math.round(maxHot * f) + '</text>';
    });
    // 막대
    hs.forEach(function (x, i) {
      var bh = ih * (x.hot_hours / maxHot), bx = L + i * bw + bw * 0.18, by = T + ih - bh;
      var future = x.hour > now;
      if (bh > 0.5) out += '<rect x="' + bx.toFixed(1) + '" y="' + by.toFixed(1) + '" width="' + (bw * 0.64).toFixed(1) +
        '" height="' + bh.toFixed(1) + '" rx="3" fill="' + (future ? "#f3d9c4" : x.hour === now ? "var(--ember)" : "var(--amber)") + '"/>';
    });
    // 쉬는 라이더 선
    var pts = hs.map(function (x, i) {
      return [L + i * bw + bw / 2, T + ih - ih * (x.resting / maxRest)];
    });
    var upto = pts.filter(function (_, i) { return hs[i].hour <= now; });
    if (upto.length > 1) out += '<polyline fill="none" stroke="var(--sky)" stroke-width="2.5" stroke-linejoin="round" points="' +
      upto.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" ") + '"/>';
    upto.forEach(function (p, i) {
      if (hs[i].resting > 0) out += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="3.5" fill="var(--sky)"/>';
    });
    // 지금 시각
    var ni = hs.map(function (x) { return x.hour; }).indexOf(now);
    if (ni >= 0) {
      var nx = L + ni * bw + bw / 2;
      out += '<line x1="' + nx.toFixed(1) + '" y1="' + T + '" x2="' + nx.toFixed(1) + '" y2="' + (T + ih) + '" stroke="var(--ember)" stroke-width="1.5" stroke-dasharray="4 4" opacity=".7"/>';
    }
    // 시각 눈금
    hs.forEach(function (x, i) {
      if (x.hour % 3 !== 0) return;
      out += '<text x="' + (L + i * bw + bw / 2).toFixed(1) + '" y="' + (H - 8) + '" text-anchor="middle" font-size="12" fill="#8fa2b8">' + x.hour + '시</text>';
    });
    // 오른쪽 축: 쉬는 라이더
    out += '<text x="' + (W - R + 8) + '" y="' + (T + 5) + '" font-size="12" fill="var(--sky)">' + maxRest + '명</text>';
    return '<svg class="trend" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img" aria-label="오늘 시간별 폭염 속 운행 시간과 쉬는 라이더 수">' + out + '</svg>';
  }

  function view(r) {
    var me = r.dongs.filter(function (d) { return d.me; })[0], hot = r.dongs.filter(function (d) { return d.hot; }).length, H = r.heat_min;
    var se = r.season, shl = r.shelters || {}, v = r.verify || {};
    var top = r.dongs.slice().sort(function (a, b) { return b.missed_hours - a.missed_hours; }).slice(0, 5);
    var peak = (r.hours || []).reduce(function (a, b) { return b.hot_hours > a.hot_hours ? b : a; }, { hour: null, hot_hours: 0 });

    var h = '<div class="dash-head"><div><p class="eyebrow">관악구 21개 동 · ' + r.time.slice(0, 10) + '</p>' +
      '<h1 class="title">' + (r.missed_hours > 0 ? "오늘 체감 " + H + "도 넘는 시간에 쉬지 않고 일한 라이더 시간이 " + num(r.missed_hours) + "시간이에요"
        : hot ? H + "도를 넘은 동이 " + hot + "곳이에요" : "지금은 모든 동이 " + H + "도 아래예요") + '</h1></div></div>';

    h += '<div class="dash">';

    // 1) 오늘 요약 — 짙은 강조 카드
    h += '<section class="dcard dark c3"><p class="dlab">지금 쉬는 라이더</p><b class="dfig">' + r.resting + '<small>명</small></b>' +
      '<div class="dsplit"><div><span>오늘 보전</span><b>' + r.paid_hours + '시간</b></div><div><span>오늘 지급 예정<sup>3</sup></span><b>' + won(r.amount) + '</b></div></div>' +
      '<div class="dwarn"><span>폭염 속 운행 시간</span><b>' + num(r.missed_hours) + '시간</b></div></section>';

    // 2) 시간별 추이
    h += '<section class="dcard c6"><div class="dtop"><h2>오늘 시간별 추이</h2>' +
      '<span class="lg"><i style="background:var(--amber)"></i>폭염 속 운행<i style="background:var(--sky);margin-left:12px"></i>그때 쉬던 라이더</span></div>' +
      trendSvg(r) +
      '<p class="note">' + (peak.hour != null && peak.hot_hours > 0
        ? '<b>' + peak.hour + '시</b>에 ' + num(Math.round(peak.hot_hours)) + '시간으로 가장 많았어요. 이 시각부터 쉼터와 알림을 늘리면 돼요.'
        : '아직 오늘 폭염 속 운행 기록이 없어요.') + '</p></section>';

    // 3) 단계별 지급 비중
    if (r.stages) {
      var pay = r.stages.filter(function (x) { return x.basis !== "none"; });
      var parts = pay.map(function (x, i) { return { label: x.stage, value: (x.season && x.season.amount) || x.amount || 0, color: i ? "var(--sky)" : "var(--amber)" }; });
      var tot = parts.reduce(function (a, p) { return a + p.value; }, 0);
      h += '<section class="dcard c3"><div class="dtop"><h2>단계별 지급 비중</h2></div>' +
        '<div class="dcenter">' + donutSvg(parts, num(r.stages.reduce(function (a, x) { return a + x.riders; }, 0)) + "명", "등록 라이더") + '</div>' +
        '<ul class="dlist">' + pay.map(function (x, i) {
          var amt = (x.season && x.season.amount) || x.amount || 0;
          return '<li><i style="background:' + (i ? "var(--sky)" : "var(--amber)") + '"></i><span>' + x.stage + ' ' + esc(x.name) + '</span><b>' + (tot ? Math.round(amt / tot * 100) : 0) + '%</b></li>';
        }).join("") + '<li><i style="background:var(--line)"></i><span>A 앱만 사용</span><b>지급 없음</b></li></ul></section>';
    }

    h += '</div>';   // 윗줄 끝

    // ── 아랫단: 세 열에 쌓는다 (칸마다 높이가 달라 생기는 빈자리를 없앤다)
    var sMap = '<section class="dcard map"><div class="dtop"><h2>동별 체감온도</h2>' +
      '<span class="chip"><i style="background:' + heat(me && me.temp, me && me.hot) + '"></i>' + (me ? esc(me.name) + " " + (me.temp == null ? "-" : me.temp.toFixed(1) + "도") : "관악구") + '</span></div>' +
      (S.geo ? mapSvg(r) : '<p class="note">지도 경계를 불러오는 중이에요.</p>') +
      '<div class="legend heat-legend"><span class="hl"><i style="background:var(--sun)"></i><i style="background:#f5a83a"></i><i style="background:var(--amber)"></i><i style="background:var(--ember)"></i><i style="background:#a82c0c"></i>' +
      '<em>' + H + '</em><em>33.5</em><em>35</em><em>36.5</em><em>38도</em></span>' +
      '<span>' + H + '도부터 보전 기준<sup>1</sup></span></div></section>';

    var sRank = '<section class="dcard"><div class="dtop"><h2>조치가 필요한 동</h2></div>' +
      '<p class="note">쉼터가 적은 동부터 늘리면 돼요</p><ol class="rank">' + top.map(function (d) {
        var n = shl[d.code] || 0;
        return '<li><div class="rank-top"><b>' + esc(d.name) + '</b><span class="fig">' + num(d.missed_hours) + '<small>시간</small></span></div>' +
          '<div class="rank-sub"><span>보전 ' + d.paid_hours + '시간</span>' +
          '<span class="' + (n === 0 ? "shl none" : n <= 1 ? "shl few" : "shl") + '">쉼터 ' + n + '곳</span></div></li>';
      }).join("") + '</ol></section>';

    var sSeason = "";
    if (se) {
      var d0 = new Date(se.season[0]), d1 = new Date(se.season[1]), dn = new Date(r.time.slice(0, 10));
      var pct = Math.max(0, Math.min(100, (dn - d0) / (d1 - d0) * 100));
      sSeason = '<section class="dcard"><div class="dtop"><h2>2026 여름</h2><span class="pill-s">' + Math.round(pct) + '% 지남</span></div>' +
        '<b class="dfig amt">' + won(se.amount) + '</b><p class="note">지금까지 지급액</p>' +
        '<div class="dbars">' +
        barRow("여름 기간", pct, 100, "var(--sky)", se.season[0].slice(5).replace("-", "/") + "~" + se.season[1].slice(5).replace("-", "/")) +
        barRow("보전 받은 라이더", se.paid_riders, se.riders, "var(--amber)", num(se.paid_riders) + " / " + num(se.riders) + "명") +
        barRow("보전된 시간", se.paid_hours, se.missed_hours, "var(--sun)", num(se.paid_hours) + " / " + num(Math.round(se.missed_hours)) + "시간") +
        '</div><p class="note foot">폭염 속 운행 시간 중 쉼표로 보전된 비율이에요<sup>3</sup></p></section>';
    }

    var sVerify = '<section class="dcard"><div class="dtop"><h2>정산 내역 사후 대조</h2><span class="pill-s">B단계</span></div>' +
      '<div class="dcenter">' + donutSvg([
        { value: v.verified || 0, color: "var(--sky)" }, { value: v.pending || 0, color: "var(--line)" }, { value: v.mismatch || 0, color: "var(--ember)" }
      ], num(v.mismatch || 0) + "건", "불일치") + '</div>' +
      '<ul class="dlist"><li><i style="background:var(--sky)"></i><span>확인 완료</span><b>' + num(v.verified || 0) + '명</b></li>' +
      '<li><i style="background:var(--line)"></i><span>대조 대기</span><b>' + num(v.pending || 0) + '명</b></li>' +
      '<li><i style="background:var(--ember)"></i><span>불일치</span><b>' + num(v.mismatch || 0) + '명</b></li></ul>' +
      '<p class="note foot">불일치면 지급을 멈추고 다시 등록받아요. 플랫폼이 연동되면(C) 대조가 필요 없어요.</p></section>';

    var slots = [[6, 9], [9, 12], [12, 15], [15, 18], [18, 22]];
    var byslot = slots.map(function (sl) {
      return { label: sl[0] + "~" + sl[1] + "시", amount: (r.hours || []).filter(function (x) { return x.hour >= sl[0] && x.hour < sl[1]; }).reduce(function (a, x) { return a + x.amount; }, 0) };
    });
    var mx = Math.max.apply(null, byslot.map(function (x) { return x.amount; })) || 1;
    var sSlots = '<section class="dcard"><div class="dtop"><h2>시간대별 지급액</h2></div><div class="dbars">' +
      byslot.map(function (x) { return barRow(x.label, x.amount, mx, x.amount === mx ? "var(--amber)" : "var(--sky-soft)", won(x.amount)); }).join("") +
      '</div><p class="note foot">보전 대상 시간대는 06~22시예요. 22~6시는 대상이 아니에요.</p></section>';

    h += '<div class="dash-lower">' +
      '<div class="dcol wide">' + sMap + sSlots + '</div>' +
      '<div class="dcol">' + sRank + '</div>' +
      '<div class="dcol">' + sSeason + sVerify + '</div>' +
      '</div>';


    h += '<details class="fold"><summary>읽는 법</summary><ul class="read">' +
      '<li><b>체감온도</b>는 행정동 체감온도 모델 값이에요. ' + H + '도는 모델 값 전용 판정선(33도 − 모델 불확도)이에요.</li>' +
      '<li><b>폭염 속 운행 시간</b>은 그 시각 가장 오래 달린 동이 ' + H + '도 이상일 때 쉬지 않고 일한 라이더 시간의 합이에요. 많은 동부터 쉼터와 안내를 늘리면 돼요.</li>' +
      '<li><b>오늘 지급 예정</b>은 라이더마다 평소 시간당 수입(최근 4주 같은 요일·같은 시각 평균, 최대 2만 원)에 쉰 분(최대 30분)을 곱한 값이에요. 20분 넘게 쉰 경우만, 한 번 최대 1만 원·하루 4번까지 셉니다.</li>' +
      '<li>보전 대상은 그 시간대에 최근 28일 중 12일 이상 일했고, 최근 2시간 배달 이동이 60분 이상이고, 쉬기 직전 1시간 가장 오래 달린 동이 ' + H + '도 이상인 라이더예요.</li>' +
      '<li>판정은 가장 오래 달린 동으로, 재원은 라이더 거주지 지자체로 나눠요.</li></ul></details>';
    h += '<details class="fold"><summary>자료 출처</summary><ol class="src">' +
      '<li>체감온도: 쉼표 행정동 체감온도 모델(2026 여름 예측, 팀 작성). 입력은 기상청 AWS·ASOS 시간자료(기상자료개방포털), 학습 정답은 서울시 S-DoT 도시데이터 센서(서울 열린데이터광장 OA-15969).</li>' +
      '<li>동 경계: 통계청 경계 기반 행정동 경계(ver20261001), 관악구 21개 동. 쉼터: 행정안전부 무더위쉼터 · 서울노동포털 이동노동자 쉼터.</li>' +
      '<li>라이더·콜·지급: ' + (r.virtual ? '가상 라이더 ' + num(r.virtual_riders) + '명의 지어낸 콜 기록(팀 생성, 실제 플랫폼 기록 아님). 배달을 마칠 때마다 조건이 되면 정해진 비율이 30분 쉰다고 가정했어요(팀 분석 4와 같은 방식). 근거로 인용하지 마세요. 단계 배정(B 70%, C 30%)과 대조 상태도 시연용이에요.' : 'DB의 실제 쉼 기록.') + '</li>' +
      '<li>판정 기준: 팀 확정안(2026.11.9). 33도·2시간마다 20분 휴식은 산업안전보건기준에 관한 규칙(2025.7.17 시행).</li></ol></details>';
    return h;
  }

  // 리포트 계산이 시연 시계(0.7초마다)보다 느릴 수 있다. 응답을 버리지 않고 그리고 나서, 그사이 시각이 바뀌었으면 한 번 더 부른다.
  var loading = false, again = false;
  function render() {
    sync.textContent = !S.cfg.demo ? "1분마다 새로 불러와요."
      : S.linked ? "라이더 앱 시연 시각을 따라가고 있어요." : "라이더 앱 시연 패널에서 이 창을 열면 그 시각을 따라가요.";
    sync.className = "sync" + (S.linked ? " on" : "");
    if (loading) { again = true; return; }
    loading = true;
    api("report", { lat: S.cfg.demo_lat, lon: S.cfg.demo_lon }).then(function (r) {
      when.textContent = r.time.slice(11) + " 기준";
      S.last = r;
      board.innerHTML = view(r);
      fitLabels(r);
    }).catch(function (e) {
      board.innerHTML = '<div class="banner" role="alert"><b>현황을 불러오지 못했어요.</b> ' + esc(e.message) + ' 서버가 켜져 있는지 확인하세요.</div>';
    }).then(function () {
      loading = false;
      if (again) { again = false; render(); }
    });
  }

  drawLogo(document.getElementById("miniLogo"), false);
  Promise.all([fetch("/api/config").then(function (r) { return r.json(); }), fetch("/api/dongs").then(function (r) { return r.json(); })]).then(function (x) {
    var cfg = x[0]; S.cfg = cfg; S.geo = project(x[1]);
    S.unitPx = Math.min(board.clientWidth || 390, 560) * 0.9 / (S.geo.w + 20);
    window.addEventListener("resize", function () { if (S.last) fitLabels(S.last); });
    if (cfg.demo) {
      var t = cfg.demo_start.split(":"); S.min = +t[0] * 60 + +t[1];
      if ("BroadcastChannel" in window) {
        var chan = new BroadcastChannel("shimpyo-demo");
        chan.onmessage = function (e) {
          if (!e.data || typeof e.data.min !== "number") return;
          S.min = e.data.min; S.linked = true; render();
        };
        chan.postMessage({ ask: true });   // 이미 열린 라이더 앱이 있으면 지금 시각을 바로 알려준다
      }
    } else setInterval(render, 60000);
    render();
  }).catch(function () { board.innerHTML = '<div class="banner" role="alert">서버에 연결되지 않아요. 터미널에서 백엔드를 실행했는지 확인하세요.</div>'; });
})();
