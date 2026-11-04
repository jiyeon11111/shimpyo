/* 쉼표 앱. 화면마다 백엔드 API를 부른다.
   흐름: 지금(홈) → 쉬는 중(몰입 화면, 탭 숨김) → 적립 완료(몰입 화면) → 내역.
   시연 모드에서는 모든 요청에 at=HH:MM(시연 시각)을 붙이고 위치는 서교동으로 고정한다. */
(function () {
  "use strict";
  var S = { cfg: null, view: "splash", min: 840, filter: "near", done: null, banner: null, lat: null, lon: null, busy: false };
  var screen = document.getElementById("screen"), dock = document.getElementById("dock"), phone = document.getElementById("phone");

  // ---------- 공통 ----------
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function hhmm(m) { return pad(Math.floor(m / 60)) + ":" + pad(m % 60); }
  function hm(m) { return Math.floor(m / 60) + ":" + pad(m % 60); }
  function won(x) { return Math.round(x).toLocaleString("ko-KR") + "원"; }
  function at() { return S.cfg && S.cfg.demo ? hhmm(S.min) : null; }
  function esc(t) { return String(t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function q(params) {
    var a = at(); if (a) params.at = a;
    return Object.keys(params).map(function (k) { return k + "=" + encodeURIComponent(params[k]); }).join("&");
  }
  function api(path, params, body) {
    var opt = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ at: at() }, body)) } : {};
    return fetch("/api/" + path + (params ? "?" + q(params) : ""), opt).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || "요청을 처리하지 못했어요."); return j; });
    });
  }
  function pos() { return { lat: S.lat, lon: S.lon }; }
  function heat(t) { return t >= 38 ? "var(--ember)" : t >= 35 ? "var(--amber)" : t >= 33 ? "var(--sun)" : t >= 31 ? "var(--warm)" : "var(--cool)"; }
  var DOW = ["일", "월", "화", "수", "목", "금", "토"];

  var ICON = {
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    chev: '<path d="M9 5l7 7-7 7"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    pin: '<path d="M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0113 0c0 4.8-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>'
  };
  function ic(n, cls) { return '<svg class="ic ' + (cls || "") + '" viewBox="0 0 24 24" aria-hidden="true">' + ICON[n] + '</svg>'; }

  // 하루 체감온도 막대: 레퍼런스의 사진 자리. 한 칸이 한 시간, 높이와 색이 체감온도, 밑줄이 돈 받는 시간.
  function bars(now, cur) {
    var nowH = +now.time.slice(11, 13), from = cur && cur.resting ? +cur.start.slice(11, 13) : null;
    var lo = 26, hi = 40;
    return '<div class="bars" aria-label="오늘 시간대별 체감온도">' + now.hours.map(function (x) {
      var hgt = Math.max(8, Math.min(100, (x.temp - lo) / (hi - lo) * 100));
      var cls = (x.h === nowH ? " now" : "") + (x.h > nowH ? " later" : "") + (from !== null && x.h >= from && x.h <= nowH ? " rest" : "");
      return '<div class="bar' + cls + '" title="' + x.h + '시 ' + x.temp + '도"><i style="height:' + hgt + '%;background:' + heat(x.temp) + '"></i><b class="' + (x.pay ? "pay" : "") + '"></b></div>';
    }).join("") + '</div><div class="bars-axis fig"><span>6시</span><span>12</span><span>18</span><span>22시</span></div>';
  }
  function payRange(now) {
    var p = now.hours.filter(function (x) { return x.pay; }).map(function (x) { return x.h; });
    return p.length ? p[0] + "~" + (p[p.length - 1] + 1) + "시" : null;
  }

  // ---------- 시작 ----------
  function vSplash() {
    return '<div class="splash"><canvas id="bigLogo" width="280" height="340" aria-label="쉼표 로고"></canvas>' +
      '<h1>쉼표</h1><p class="lead">폭염 시간에 쉬어도<br>소득이 줄지 않게.</p>' +
      '<ol class="how">' +
      '<li><b>더울 때 쉬기 시작을 눌러요</b><span>체감온도 35도 넘는 14~17시, 38도 넘으면 언제든</span></li>' +
      '<li><b>다 쉬면 끝내기를 눌러요</b><span>쉼터 근처면 바로 인정돼요</span></li>' +
      '<li><b>쉰 만큼 돈이 쌓여요</b><span>1시간에 ' + won(S.cfg ? S.cfg.rate : 17210) + ', 하루 최대 4시간</span></li></ol>' +
      '<div class="foot"><button class="pillbtn dark full" id="goBtn">시작하기</button>' +
      '<span class="note center">위치로 체감온도를 확인해요. 위치는 쉼을 기록할 때만 저장해요.</span></div></div>';
  }

  // ---------- 지금 (홈) ----------
  function verdict(now, hist) {
    if (hist.today_left_min <= 0) return { h: "오늘 받을 만큼 다 받았어요", s: "하루 최대 4시간이에요. 그래도 더우면 꼭 쉬세요." };
    if (now.pay_now) return { h: "지금 쉬면 돈을 받아요", s: now.pay_until + "시까지 쉰 만큼 쌓여요" };
    if (now.next_pay) return { h: "아직은 적립 시간이 아니에요", s: now.next_pay + "시부터 쉬면 돈을 받아요" };
    return { h: "오늘 적립 시간이 끝났어요", s: "내일도 더우면 알려드릴게요" };
  }

  function shelterRow(s, link) {
    var rider = /라이더|이동노동자/.test(s.kind);
    var inner = '<span class="thumb' + (rider ? " rider" : "") + '"><b class="fig">' + s.walk_min + '</b><small>분</small></span>' +
      '<span class="txt"><span class="name">' + esc(s.name) + '</span><span class="sub">' + (rider ? "이동노동자 쉼터" : esc(s.kind)) + (s.hours ? ", " + esc(s.hours) : "") + '</span>' +
      (s.distance_m <= 150 ? '<span class="tag">여기서 쉬면 바로 인정</span>' : '') + '</span>' + ic("chev", "chev");
    if (link && s.lat) return '<a class="item" target="_blank" rel="noopener" href="https://map.kakao.com/link/to/' + encodeURIComponent(s.name) + ',' + s.lat + ',' + s.lon + '" aria-label="' + esc(s.name) + ' 길찾기">' + inner + '</a>';
    return '<button class="item" data-go="shelter">' + inner + '</button>';
  }

  function vHome(now, cur, hist, near) {
    var v = verdict(now, hist), payNow = now.pay_now && hist.today_left_min > 0, range = payRange(now);
    var h = '<header class="brand"><span class="word"><canvas id="miniLogo" width="56" height="68" aria-hidden="true"></canvas>쉼표</span>' +
      '<span class="loc">' + ic("pin") + now.place + '</span></header>';
    if (S.banner) h += '<div class="banner" role="alert">' + S.banner + '</div>';
    h += '<p class="eyebrow">' + v.s + '</p><h1 class="title">' + v.h + '</h1>';
    h += '<section class="hero" aria-label="지금 체감온도">' +
      '<div class="hero-top"><span class="chip"><i style="background:' + heat(now.temp) + '"></i>' + now.stage.name + ' 단계</span><span class="hero-time fig">' + now.time.slice(11) + '</span></div>' +
      '<div class="hero-temp fig">' + now.temp.toFixed(1) + '<sup>°</sup><small>체감온도</small></div>' +
      bars(now, null) +
      '<div class="hero-foot"><div><b>' + (range ? range + " 적립" : "오늘 적립 없음") + '</b><span>시간당 ' + won(now.rate) + '</span></div>' +
      '<button class="pillbtn ' + (payNow ? "amber" : "ghost") + '" id="startBtn"' + (S.busy ? " disabled" : "") + '>' + (S.busy ? "시작하는 중" : payNow ? "쉬기 시작" : "그래도 쉬기") + '</button></div>' +
      '</section>';
    if (!payNow) h += '<p class="note">지금 쉬면 기록만 남고 돈은 쌓이지 않아요.</p>';
    h += '<div class="sec"><h2>가까운 쉼터</h2><button class="more" data-go="shelter">전체 보기</button></div>' +
      '<div class="list">' + near.items.slice(0, 2).map(function (s) { return shelterRow(s, false); }).join("") + '</div>';
    h += '<div class="today"><span>오늘 받은 돈</span><b class="fig">' + won(hist.today_paid_min / 60 * now.rate) + '</b></div>';
    return h;
  }

  // ---------- 쉬는 중 (몰입 화면) ----------
  function vResting(now, cur, hist) {
    var capH = S.cfg.daily_cap_min / 60, used = hist.today_paid_min + cur.paid_min, left = Math.max(0, S.cfg.daily_cap_min - used);
    var inHour = cur.paid_min % 60, frac = left <= 0 ? 1 : inHour / 60, R = 92, C = 2 * Math.PI * R;
    var msg = left <= 0 ? "오늘 한도를 다 채웠어요. 이제 끝내도 돼요."
      : now.pay_now ? (60 - inHour) + "분 더 쉬면 " + won(now.rate) + " 더 쌓여요"
      : "지금은 적립 시간이 아니에요. 끝내도 손해 없어요.";
    var segs = ""; for (var i = 0; i < capH; i++) segs += '<i class="' + (used >= (i + 1) * 60 ? "full" : used > i * 60 ? "part" : "") + '"></i>';
    return '<div class="immersive">' +
      '<header class="ibar"><span></span><h1>쉬는 중</h1><span></span></header>' +
      '<div class="ichip">' + cur.start.slice(11) + '부터, ' + (cur.place === "shelter" ? "쉼터에서 확인됨" : "자리 확인 중") + '</div>' +
      '<div class="ring"><svg viewBox="0 0 220 220" aria-hidden="true"><circle cx="110" cy="110" r="' + R + '" class="track"/>' +
      '<circle cx="110" cy="110" r="' + R + '" class="prog" stroke-dasharray="' + C + '" stroke-dashoffset="' + (C * (1 - frac)) + '"/></svg>' +
      '<div class="ring-in"><b class="fig">' + hm(cur.rested_min) + '</b><span>쉰 시간</span></div></div>' +
      '<div class="earned"><span>지금까지</span><b class="fig">' + won(cur.amount) + '</b></div>' +
      '<div class="ibars">' + bars(now, cur) + '</div>' +
      '<section class="sheet"><i class="grab"></i>' +
      '<p class="sheet-k">다음 적립</p><p class="sheet-v">' + msg + '</p>' +
      '<div class="segs">' + segs + '</div><p class="sheet-s fig">오늘 ' + Math.floor(used / 60) + '시간 ' + (used % 60) + '분 / ' + capH + '시간</p>' +
      '<button class="pillbtn light full" id="stopBtn"' + (S.busy ? " disabled" : "") + '>' + (S.busy ? "끝내는 중" : "다 쉬었어요, 끝내기") + '</button>' +
      (S.cfg.demo ? '<p class="sheet-s center">시연 패널에서 시간을 옮겨 보세요</p>' : '<p class="sheet-s center">앱을 닫아도 계속 기록돼요</p>') +
      '</section></div>';
  }

  // ---------- 적립 완료 (몰입 화면) ----------
  function vDone(d, now, hist) {
    var s = +d.start.slice(11, 13), e = +d.end.slice(11, 13), peak = 0;
    now.hours.forEach(function (x) { if (x.h >= s && x.h <= e) peak = Math.max(peak, x.temp); });
    var paid = d.paid_min > 0;
    return '<div class="immersive done-screen">' +
      '<header class="ibar"><button class="iconbtn" id="doneX" aria-label="닫기">' + ic("close") + '</button><span></span><span></span></header>' +
      '<div class="okmark' + (paid ? "" : " muted") + '">' + ic("check") + '</div>' +
      '<h1 class="done-title">' + (paid ? won(d.amount) + " 적립됐어요" : "쉼을 끝냈어요") + '</h1>' +
      '<p class="done-sub fig">' + d.start.slice(11) + ' ~ ' + d.end.slice(11) + ', ' + now.place + '</p>' +
      '<div class="trio"><div><b class="fig">' + d.rested_min + '<small>분</small></b><span>쉰 시간</span></div>' +
      '<div><b class="fig">' + peak.toFixed(1) + '<small>°</small></b><span>최고 체감온도</span></div>' +
      '<div><b class="fig">' + hist.today_left_min + '<small>분</small></b><span>오늘 남은 한도</span></div></div>' +
      (paid ? '' : '<p class="done-note">적립 시간이 아니어서 이번엔 돈이 쌓이지 않았어요.</p>') +
      '<p class="done-k">이번 주 쉰 날</p><div class="weekdots">' + hist.week.map(function (w) {
        var dd = new Date(w.date + "T00:00");
        return '<div class="' + (w.today ? "t" : "") + '"><i class="' + (w.rested ? "y" : "") + '">' + (w.rested ? ic("check") : "") + '</i>' + DOW[dd.getDay()] + '</div>';
      }).join("") + '</div>' +
      '<div class="done-actions"><button class="pillbtn light full" id="toHistory">내역 보기</button><button class="textbtn" id="doneOk">확인</button></div></div>';
  }

  // ---------- 쉼터 ----------
  function vShelter(list) {
    return '<h1 class="title top">쉼터</h1><p class="eyebrow">가까운 순, 누르면 카카오맵 길찾기</p>' +
      '<div class="chips" role="group" aria-label="쉼터 종류"><button id="f-near" aria-pressed="' + (S.filter === "near") + '">전체</button><button id="f-rider" aria-pressed="' + (S.filter === "rider") + '">이동노동자 쉼터</button></div>' +
      (list.items.length ? '<div class="list">' + list.items.map(function (s) { return shelterRow(s, true); }).join("") + '</div>'
        : '<p class="empty">반경 안에 등록된 쉼터가 없어요. 아무 데서나 쉬기 시작해도 자리 확인 뒤 인정돼요.</p>') +
      '<p class="note">쉼터 150m 안에서 쉬기 시작하면 바로 인정돼요.' + (list.virtual ? " 지금 목록은 시연용 예시예요." : "") + '</p>';
  }

  // ---------- 내역 ----------
  function vHistory(hist) {
    var month = +(at() ? S.cfg.demo_date : new Date().toISOString()).slice(5, 7);
    var h = '<h1 class="title top">내역</h1><p class="eyebrow">' + month + '월에 쌓인 돈</p>' +
      '<section class="hero slim"><div class="hero-temp fig">' + won(hist.month.amount) + '</div>' +
      '<div class="trio in"><div><b class="fig">' + hist.month.count + '<small>번</small></b><span>쉰 횟수</span></div>' +
      '<div><b class="fig">' + hist.month.paid_min + '<small>분</small></b><span>적립 시간</span></div>' +
      '<div><b class="fig">' + Math.max(0, S.cfg.monthly_cap_min - hist.month.paid_min) + '<small>분</small></b><span>이달 남은 한도</span></div></div></section>' +
      '<div class="sec"><h2>최근 7일</h2></div><div class="weekdots light">' + hist.week.map(function (w) {
        var d = new Date(w.date + "T00:00");
        return '<div class="' + (w.today ? "t" : "") + '"><i class="' + (w.rested ? "y" : "") + '">' + (w.rested ? ic("check") : d.getDate()) + '</i>' + DOW[d.getDay()] + '</div>';
      }).join("") + '</div>' +
      '<div class="sec"><h2>오늘</h2></div>';
    if (!hist.today.length) h += '<p class="empty">아직 쉰 기록이 없어요. 지금 탭에서 쉬기 시작을 눌러 보세요.</p>';
    else h += '<div class="list">' + hist.today.map(function (r) {
      return '<div class="item static"><span class="thumb ' + (r.paid_min ? "paid" : "") + '">' + ic(r.paid_min ? "check" : "close") + '</span>' +
        '<span class="txt"><span class="name fig">' + r.start.slice(11) + ' ~ ' + r.end.slice(11) + '</span><span class="sub">' + (r.place === "shelter" ? "쉼터" : "그 밖의 곳") + ', ' + (r.paid_min ? r.paid_min + "분 적립" : "적립 시간 아님") + '</span></span>' +
        '<b class="amt fig">' + won(r.amount) + '</b></div>';
    }).join("") + '</div>';
    return h + (hist.has_virtual ? '<p class="note">이번 달 합계에는 시연용 가상 기록이 들어 있어요.</p>' : '');
  }

  // ---------- 지역 ----------
  function vReport(r) {
    return '<h1 class="title top">지역 현황</h1><p class="eyebrow fig">' + r.time.slice(11) + ' 기준, 내 위치 주변 5km 격자 49칸</p>' +
      '<section class="hero slim"><div class="map">' + r.grid.map(function (c) { return '<i style="background:' + heat(c.temp) + '" class="' + (c.me ? "me" : "") + '" title="' + c.temp + '도">' + c.temp.toFixed(1) + '</i>'; }).join("") + '</div>' +
      '<div class="legend"><span><i style="background:var(--sun)"></i>33도</span><span><i style="background:var(--amber)"></i>35도</span><span><i style="background:var(--ember)"></i>38도 이상</span><span>흰 테두리: 내 칸</span></div>' +
      '<div class="trio in"><div><b class="fig">' + r.resting + '<small>명</small></b><span>지금 쉬는 라이더</span></div>' +
      '<div><b class="fig">' + Math.round(r.paid_hours) + '<small>시간</small></b><span>오늘 적립</span></div>' +
      '<div class="warn"><b class="fig">' + r.missed_hours + '<small>시간</small></b><span>못 쉰 위험 시간</span></div></div></section>' +
      '<div class="today"><span>오늘 지급 예정</span><b class="fig">' + won(r.amount) + '</b></div>' +
      '<p class="note">못 쉰 시간이 많은 곳이 지원이 먼저 필요한 곳이에요.' + (r.virtual ? " 가상 라이더 " + r.virtual_riders + "명으로 계산한 시연 값이에요." : "") + '</p>';
  }

  // ---------- 렌더 ----------
  var seq = 0;
  function render() {
    var my = ++seq, v = S.view, p = pos();
    if (S.cfg && S.cfg.demo) { document.getElementById("clockT").textContent = hhmm(S.min); document.getElementById("clockR").value = S.min; }
    document.getElementById("barTime").textContent = S.cfg && S.cfg.demo ? hhmm(S.min) : new Date().toTimeString().slice(0, 5);
    var job, immersive = false;
    if (v === "splash") job = Promise.resolve(vSplash());
    else if (v === "home") job = Promise.all([api("now", p), api("rest/current", { rider_id: 1 }), api("history", { rider_id: 1 }), api("shelters", p)]).then(function (x) {
      if (S.done) { immersive = true; return vDone(S.done, x[0], x[2]); }
      if (x[1].resting) { immersive = true; return vResting(x[0], x[1], x[2]); }
      return vHome(x[0], x[1], x[2], x[3]);
    });
    else if (v === "shelter") job = api("shelters", Object.assign({}, p, S.filter === "rider" ? { kind: "rider" } : {})).then(vShelter);
    else if (v === "history") job = api("history", { rider_id: 1 }).then(vHistory);
    else job = api("report", p).then(vReport);
    return job.then(function (html) {
      if (my !== seq) return;
      phone.classList.toggle("dark", immersive);
      dock.hidden = v === "splash" || immersive;
      dock.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-selected", b.dataset.v === v ? "true" : "false"); });
      screen.innerHTML = html; bindScreen();
    }).catch(function (e) {
      if (my !== seq) return;
      phone.classList.remove("dark"); dock.hidden = v === "splash";
      screen.innerHTML = '<div class="banner" role="alert">' + esc(e.message) + '</div><button class="pillbtn dark full" id="retry">다시 불러오기</button>';
      document.getElementById("retry").onclick = render;
    });
  }
  function bind(id, fn) { var e = document.getElementById(id); if (e) e.onclick = fn; }
  function bindScreen() {
    var bl = document.getElementById("bigLogo"); if (bl) drawLogo(bl, false);
    var ml = document.getElementById("miniLogo"); if (ml) drawLogo(ml, false);
    bind("goBtn", function () { S.view = "home"; render(); });
    bind("startBtn", function () {
      if (S.busy) return; S.busy = true; S.banner = null; render();
      api("rest/start", null, { rider_id: 1, lat: S.lat, lon: S.lon, place: "auto" }).then(function () { S.busy = false; render(); }).catch(showErr);
    });
    bind("stopBtn", function () {
      if (S.busy) return; S.busy = true; render();
      api("rest/stop", null, { rider_id: 1 }).then(function (r) { S.busy = false; S.done = r; render(); }).catch(showErr);
    });
    bind("doneX", function () { S.done = null; render(); });
    bind("doneOk", function () { S.done = null; render(); });
    bind("toHistory", function () { S.done = null; S.view = "history"; render(); });
    bind("f-near", function () { S.filter = "near"; render(); });
    bind("f-rider", function () { S.filter = "rider"; render(); });
    screen.querySelectorAll("[data-go]").forEach(function (b) { b.onclick = function () { S.view = b.dataset.go; render(); }; });
  }
  function showErr(e) { S.busy = false; S.banner = "<b>처리하지 못했어요.</b> " + esc(e.message); render(); }

  // ---------- 시연 시계 ----------
  var timer = null, playBtn = document.getElementById("play");
  function stop() { clearInterval(timer); timer = null; playBtn.textContent = "재생"; }
  function setMin(m) { S.min = Math.max(540, Math.min(1200, m)); render(); }
  playBtn.onclick = function () {
    if (timer) return stop();
    if (S.view === "splash") S.view = "home";
    playBtn.textContent = "멈춤";
    timer = setInterval(function () { if (S.min >= 1200) return stop(); setMin(S.min + 10); }, 700);
  };
  document.getElementById("clockR").oninput = function (e) { setMin(+e.target.value); };
  document.getElementById("jump14").onclick = function () { stop(); setMin(840); };
  document.getElementById("reset").onclick = function () { stop(); api("demo/reset", null, {}).then(function () { S.done = null; S.banner = null; setMin(840); }).catch(showErr); };
  dock.querySelectorAll("button").forEach(function (b) { b.onclick = function () { S.view = b.dataset.v; render(); }; });

  // ---------- 시작 ----------
  fetch("/api/config").then(function (r) { return r.json(); }).then(function (cfg) {
    S.cfg = cfg; S.lat = cfg.demo_lat; S.lon = cfg.demo_lon;
    if (cfg.demo) {
      var p = cfg.demo_start.split(":"); S.min = +p[0] * 60 + +p[1];
      document.getElementById("demo").hidden = false;
      document.getElementById("demoDate").textContent = cfg.demo_date;
      render();
    } else if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(function (g) { S.lat = g.coords.latitude; S.lon = g.coords.longitude; render(); },
        function () { S.banner = "<b>위치를 못 받았어요.</b> 서교동 기준으로 보여드려요. 브라우저에서 위치 권한을 켜 주세요."; render(); }, { timeout: 8000 });
      render();
    } else render();
  }).catch(function () { screen.innerHTML = '<div class="banner" role="alert">서버에 연결되지 않아요. 터미널에서 백엔드를 실행했는지 확인하세요.</div>'; });

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(function () {});
})();
