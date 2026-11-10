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
  function heat(t) { return t == null ? "var(--cool)" : t >= 38 ? "var(--ember)" : t >= 35 ? "var(--amber)" : t >= 32 ? "var(--sun)" : t >= 31 ? "var(--warm)" : "var(--cool)"; }
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
      var path = '<path d="' + f.d + '" fill="' + heat(t) + '" class="dong' + (d.me ? " me" : "") + '"><title>' + esc(tip) + '</title></path>';
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

  function view(r) {
    var me = r.dongs.filter(function (d) { return d.me; })[0], hot = r.dongs.filter(function (d) { return d.hot; }).length, H = r.heat_min;
    var h = '<p class="eyebrow">관악구 21개 동, ' + r.time.slice(0, 10) + '</p>' +
      '<h1 class="title">' + (r.missed_hours > 0 ? "오늘 체감 " + H + "도 넘는 시간에 쉬지 않고 일한 라이더 시간이 " + num(r.missed_hours) + "시간이에요"
        : hot ? H + "도를 넘은 동이 " + hot + "곳이에요. 아직 못 쉰 시간은 없어요" : "지금은 모든 동이 " + H + "도 아래예요") + '</h1>';
    h += '<div class="kpis">' +
      '<div><span>지금 쉬는 라이더</span><b class="fig">' + r.resting + '<small>명</small></b></div>' +
      '<div><span>오늘 보전 시간</span><b class="fig">' + r.paid_hours + '<small>시간</small></b></div>' +
      '<div><span>오늘 지급 예정<sup>3</sup></span><b class="fig amt">' + won(r.amount) + '</b></div>' +
      '<div class="warn"><span>못 쉰 위험 시간</span><b class="fig">' + num(r.missed_hours) + '<small>시간</small></b></div></div>';
    h += '<div class="admin-body"><section class="hero admin-map" aria-label="행정동별 체감온도">' +
      '<div class="hero-top"><span class="chip"><i style="background:' + heat(me && me.temp) + '"></i>' + (me ? esc(me.name) + " " + (me.temp == null ? "-" : me.temp.toFixed(1) + "도, " + esc(me.stage) + " 단계") : "관악구") + '</span>' +
      '<span class="hero-time fig">' + H + '도 이상 ' + hot + '곳 / 21곳<sup>1·2</sup></span></div>' +
      (S.geo ? mapSvg(r) : '<p class="note">지도 경계를 불러오는 중이에요.</p>') +
      '<div class="legend"><span><i style="background:var(--sun)"></i>' + H + '도 이상: 보전 기준 (모델 값)<sup>1</sup></span><span><i style="background:var(--amber)"></i>35도 이상</span><span><i style="background:var(--ember)"></i>38도 이상</span><span>흰 테두리: ' + esc(me ? me.name : "") + ' (시연 위치)</span></div>' +
      '</section>';
    var top = r.dongs.slice().sort(function (a, b) { return b.missed_hours - a.missed_hours; }).slice(0, 5);
    h += '<div class="admin-side">';
    if (r.season) {
      var se = r.season;
      h += '<div class="sec"><h2>2026 여름 합계</h2></div><p class="note">' + se.season[0].slice(5).replace("-", "/") + '~' + se.season[1].slice(5).replace("-", "/") + ', 가상 라이더 ' + num(se.riders) + '명</p>' +
        '<div class="kpis season"><div><span>보전 인원</span><b class="fig">' + num(se.paid_riders) + '<small>명</small></b></div>' +
        '<div><span>보전 시간</span><b class="fig">' + num(se.paid_hours) + '<small>시간</small></b></div>' +
        '<div><span>지급액</span><b class="fig amt">' + won(se.amount) + '</b></div>' +
        '<div class="warn"><span>못 쉰 위험 시간</span><b class="fig">' + num(Math.round(se.missed_hours)) + '<small>시간</small></b></div></div>';
      var sc = se.scenarios || {};
      if (sc["1.0"] && sc["0.25"]) h += '<p class="note">자격이 될 때 ' + Math.round((se.rest_p || 0.5) * 100) + '%가 쉰다고 본 값이에요. 모두 쉬면 ' + won(sc["1.0"].amount) +
        ', 4분의 1만 쉬면 ' + won(sc["0.25"].amount) + '이에요.<sup>3</sup></p>';
    }
    h += '<div class="sec"><h2>오늘 못 쉰 시간이 많은 동</h2></div><ol class="read rank">' + top.map(function (d) {
      return '<li><b>' + esc(d.name) + '</b> ' + num(d.missed_hours) + '시간, 보전 ' + d.paid_hours + '시간 ' + won(d.amount) + '</li>';
    }).join("") + '</ol>';
    h += '<div class="sec"><h2>읽는 법</h2></div><ul class="read">' +
      '<li><b>체감온도</b>는 행정동 체감온도 모델 값이에요. ' + H + '도는 모델 값 전용 판정선(33도 − 모델 불확도)이에요.</li>' +
      '<li><b>못 쉰 위험 시간</b>은 그 시각 가장 오래 달린 동이 ' + H + '도 이상일 때 쉬지 않고 일한 라이더 시간의 합이에요. 많은 동부터 쉼터와 안내를 늘리면 돼요.</li>' +
      '<li><b>오늘 지급 예정</b>은 라이더마다 평소 시간당 수입(최근 4주 같은 요일·같은 시각 평균, 최대 2만 원)에 쉰 분(최대 30분)을 곱한 값이에요. 20분 넘게 쉰 경우만, 한 번 최대 1만 원·하루 4번까지 셉니다.</li>' +
      '<li>보전 대상은 그 시간대에 최근 28일 중 12일 이상 일했고, 최근 2시간 배달 이동이 60분 이상이고, 쉬기 직전 1시간 가장 오래 달린 동이 ' + H + '도 이상인 라이더예요. 22~6시는 대상이 아니에요.</li>' +
      '<li>판정은 가장 오래 달린 동으로, 재원은 라이더 거주지 지자체로 나눠요.</li></ul>';
    h += '<div class="sec"><h2>자료 출처</h2></div><ol class="src">' +
      '<li>체감온도: 쉼표 행정동 체감온도 모델(2026 여름 예측, 팀 작성). 입력은 기상청 AWS·ASOS 시간자료(기상자료개방포털), 학습 정답은 서울시 S-DoT 도시데이터 센서(서울 열린데이터광장 OA-15969).</li>' +
      '<li>동 경계: 통계청 경계 기반 행정동 경계(ver20261001), 관악구 21개 동.</li>' +
      '<li>라이더·콜·지급: ' + (r.virtual ? '가상 라이더 ' + num(r.virtual_riders) + '명의 지어낸 콜 기록(팀 생성, 실제 플랫폼 기록 아님). 배달을 마칠 때마다 조건이 되면 정해진 비율이 30분 쉰다고 가정했어요(팀 분석 4와 같은 방식). 근거로 인용하지 마세요.' : 'DB의 실제 쉼 기록.') + '</li>' +
      '<li>판정 기준: 팀 확정안(2026.11.9). 33도·2시간마다 20분 휴식은 산업안전보건기준에 관한 규칙(2025.7.17 시행).</li></ol>';
    return h + '</div></div>';
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
