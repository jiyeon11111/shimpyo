/* 쉼표 앱. 화면마다 백엔드 API를 부른다.
   흐름: 지금(홈) → 쉬는 중(몰입 화면, 탭 숨김) → 적립 완료(몰입 화면) → 내역.
   지역 현황은 라이더 화면이 아니라서 admin.html(지자체·보험사용)로 뺐다.
   시연 모드에서는 모든 요청에 at=HH:MM(시연 시각)을 붙이고 위치는 관악구청(청룡동)으로 고정한다. */
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
  function heat(t) { return t >= 38 ? "var(--ember)" : t >= 35 ? "var(--amber)" : t >= 32 ? "var(--sun)" : t >= 31 ? "var(--warm)" : "var(--cool)"; }
  var DOW = ["일", "월", "화", "수", "목", "금", "토"];

  var ICON = {
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    chev: '<path d="M9 5l7 7-7 7"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    pin: '<path d="M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0113 0c0 4.8-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>'
  };
  function ic(n, cls) { return '<svg class="ic ' + (cls || "") + '" viewBox="0 0 24 24" aria-hidden="true">' + ICON[n] + '</svg>'; }

  // 하루 체감온도 막대: 레퍼런스의 사진 자리. 한 칸이 한 시간, 높이와 색이 체감온도, 밑줄이 기준(32도, 모델 값) 넘는 시간.
  function bars(now, cur) {
    var nowH = +now.time.slice(11, 13), from = cur && cur.resting ? +cur.start.slice(11, 13) : null;
    var lo = 26, hi = 40;
    return '<div class="bars" aria-label="오늘 시간대별 체감온도">' + now.hours.map(function (x) {
      var hgt = Math.max(8, Math.min(100, (x.temp - lo) / (hi - lo) * 100));
      var cls = (x.h === nowH ? " now" : "") + (x.h > nowH ? " later" : "") + (from !== null && x.h >= from && x.h <= nowH ? " rest" : "");
      return '<div class="bar' + cls + '" title="' + x.h + '시 ' + x.temp + '도"><i style="height:' + hgt + '%;background:' + heat(x.temp) + '"></i><b class="' + (x.hot ? "pay" : "") + '"></b></div>';
    }).join("") + '</div><div class="bars-axis fig"><span>6시</span><span>12</span><span>18</span><span>22시</span></div>';
  }
  function hotRange(now) {
    var p = now.hours.filter(function (x) { return x.hot; }).map(function (x) { return x.h; });
    return p.length ? p[0] + "~" + (p[p.length - 1] + 1) + "시" : null;
  }
  function rules() { var c = S.cfg || {}; return { heat: c.heat_min || 32, need: c.exposure_need_min || 60, rest: c.rest_min || 20, cap: c.pay_cap_min || 30, capWon: c.pay_cap_won || 10000, labor: c.labor_need_days || 12, times: c.daily_rests || 4 }; }

  // ---------- 시작 ----------
  function vSplash() {
    var R = rules();
    return '<div class="splash"><canvas id="bigLogo" width="280" height="340" aria-label="쉼표 로고"></canvas>' +
      '<h1>쉼표</h1><p class="lead">폭염 시간에 쉬어도<br>소득이 줄지 않게.</p>' +
      '<ol class="how">' +
      '<li><b>더운데 배달 중이면 쉬기 시작을 눌러요</b><span>달린 동 체감온도 ' + R.heat + '도 이상, 최근 2시간 배달 이동 ' + R.need + '분 이상, 이 시간대에 최근 4주 중 ' + R.labor + '일 이상 일했으면 돼요</span></li>' +
      '<li><b>' + R.rest + '분 넘게 쉬고 끝내기를 눌러요</b><span>쉬는 동안 콜이 꺼져요</span></li>' +
      '<li><b>평소 이 시간에 벌던 만큼 쌓여요</b><span>한 번에 ' + R.cap + '분치(최대 ' + won(R.capWon) + ')까지, 하루 ' + R.times + '번까지</span></li></ol>' +
      '<div class="foot"><button class="pillbtn dark full" id="goBtn">시작하기</button>' +
      '<span class="note center">위치로 체감온도를 확인해요. 위치는 쉼을 기록할 때만 저장해요.</span></div></div>';
  }

  // ---------- 지금 (홈) ----------
  function verdict(now, hist) {
    var R = rules();
    if (hist.today_left_rests <= 0) return { h: "오늘 받을 만큼 다 받았어요", s: "하루 " + R.times + "번까지예요. 그래도 더우면 꼭 쉬세요." };
    if (now.pay_now) return { h: "지금 쉬면 돈을 받아요", s: R.rest + "분 넘게 쉬면 평소 이 시간 수입만큼 쌓여요" };
    return { h: "지금 쉬면 돈은 안 나와요", s: now.reasons[0] || "" };
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
    var v = verdict(now, hist), payNow = now.pay_now && hist.today_left_rests > 0, R = rules();
    var foot = now.has_record
      ? '<b>배달 이동 ' + now.exposure_min + '분 / ' + R.need + '분</b><span>' + (now.usual_hourly ? "평소 이 시간 시간당 " + won(now.usual_hourly) : "평소 이 시간엔 일하지 않았어요") + '</span>'
      : '<b>운행 기록 연결 전</b><span>' + (hotRange(now) ? hotRange(now) + " " + R.heat + "도 이상" : "오늘 " + R.heat + "도 넘는 시간 없음") + '</span>';
    var h = '<header class="brand"><span class="word"><canvas id="miniLogo" width="56" height="68" aria-hidden="true"></canvas>쉼표</span>' +
      '<span class="loc">' + ic("pin") + now.place + '</span></header>';
    if (S.banner) h += '<div class="banner" role="alert">' + S.banner + '</div>';
    h += '<p class="eyebrow">' + v.s + '</p><h1 class="title">' + v.h + '</h1>';
    h += '<section class="hero" aria-label="지금 체감온도">' +
      '<div class="hero-top"><span class="chip"><i style="background:' + heat(now.temp) + '"></i>' + now.stage.name + ' 단계</span><span class="hero-time fig">' + now.time.slice(11) + '</span></div>' +
      '<div class="hero-temp fig">' + now.temp.toFixed(1) + '<sup>°</sup><small>체감온도</small></div>' +
      bars(now, null) +
      '<div class="hero-foot"><div>' + foot + '</div>' +
      '<button class="pillbtn ' + (payNow ? "amber" : "ghost") + '" id="startBtn"' + (S.busy ? " disabled" : "") + '>' + (S.busy ? "시작하는 중" : payNow ? "쉬기 시작" : "그래도 쉬기") + '</button></div>' +
      '</section>';
    if (!payNow) h += '<p class="note">지금 쉬면 기록만 남고 돈은 쌓이지 않아요.' + (now.reasons.length > 1 ? " " + now.reasons.slice(1).map(esc).join(". ") + "." : "") + '</p>';
    if (now.judge_dong) h += '<p class="note">체감온도는 최근 1시간 가장 오래 달린 ' + esc(now.judge_dong.name) + ' 값이에요(행정동 모델).</p>';
    if (now.virtual_rider) h += '<p class="note">운행 기록과 평소 수입은 시연용 가상 라이더 값이에요.</p>';
    h += '<p class="note src">자료: 체감온도는 쉼표 행정동 모델(기상청 AWS·ASOS 관측과 서울시 S-DoT 센서로 학습), 동 경계는 통계청 기반 행정동 경계, 판정 기준은 팀 확정안(2026.11.9)이에요.</p>';
    h += '<div class="sec"><h2>가까운 쉼터</h2><button class="more" data-go="shelter">전체 보기</button></div>' +
      '<div class="list">' + near.items.slice(0, 2).map(function (s) { return shelterRow(s, false); }).join("") + '</div>';
    h += '<div class="today"><span>오늘 받은 돈</span><b class="fig">' + won(hist.today_amount) + '</b></div>';
    return h;
  }

  // ---------- 쉬는 중 (몰입 화면) ----------
  function vResting(now, cur, hist) {
    var Q = rules(), times = Q.times, done = hist.today_paid_rests, counting = cur.eligible && done < times;
    var frac = counting ? Math.min(cur.rested_min, Q.cap) / Q.cap : 0, R = 92, C = 2 * Math.PI * R;
    var msg = !cur.eligible ? "이번 쉼은 적립 대상이 아니에요. " + esc(cur.reason || "") + ". 그래도 더우면 쉬어 가세요."
      : done >= times ? "오늘 " + times + "번을 다 받았어요. 이제 끝내도 돼요."
      : cur.rested_min < Q.rest ? (Q.rest - cur.rested_min) + "분 더 쉬면 적립돼요"
      : cur.rested_min < Q.cap ? (Q.cap - cur.rested_min) + "분 더 쉬면 " + won(Math.min(Q.cap / 60 * cur.usual_hourly, Q.capWon)) + "까지 쌓여요"
      : "이번 쉼은 최대치를 채웠어요. 끝내도 돼요.";
    var used = done + (cur.paid_min > 0 ? 1 : 0);
    var segs = ""; for (var i = 0; i < times; i++) segs += '<i class="' + (i < done ? "full" : i < used ? "part" : "") + '"></i>';
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
      '<div class="segs">' + segs + '</div><p class="sheet-s fig">오늘 ' + used + '번 / ' + times + '번</p>' +
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
      '<div><b class="fig">' + hist.today_left_rests + '<small>번</small></b><span>오늘 남은 횟수</span></div></div>' +
      (paid ? '' : '<p class="done-note">이번엔 돈이 쌓이지 않았어요. ' + esc(d.reason || "") + '.</p>') +
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
      '<p class="note">쉼터 150m 안에서 쉬기 시작하면 바로 인정돼요.' + (list.virtual ? " 지금 목록은 시연용 예시예요. 실제 운영 때는 서울 열린데이터광장 무더위쉼터 목록을 써요." : " 자료: 서울 열린데이터광장 무더위쉼터.") + '</p>';
  }

  // ---------- 내역 ----------
  function vHistory(hist) {
    var month = +(at() ? S.cfg.demo_date : new Date().toISOString()).slice(5, 7);
    var h = '<h1 class="title top">내역</h1><p class="eyebrow">' + month + '월에 쌓인 돈</p>' +
      '<section class="hero slim"><div class="hero-temp fig">' + won(hist.month.amount) + '</div>' +
      '<div class="trio in"><div><b class="fig">' + hist.month.count + '<small>번</small></b><span>쉰 횟수</span></div>' +
      '<div><b class="fig">' + hist.month.paid_min + '<small>분</small></b><span>적립 시간</span></div>' +
      '<div><b class="fig">' + hist.today_left_rests + '<small>번</small></b><span>오늘 남은 횟수</span></div></div></section>' +
      '<div class="sec"><h2>최근 7일</h2></div><div class="weekdots light">' + hist.week.map(function (w) {
        var d = new Date(w.date + "T00:00");
        return '<div class="' + (w.today ? "t" : "") + '"><i class="' + (w.rested ? "y" : "") + '">' + (w.rested ? ic("check") : d.getDate()) + '</i>' + DOW[d.getDay()] + '</div>';
      }).join("") + '</div>' +
      '<div class="sec"><h2>오늘</h2></div>';
    if (!hist.today.length) h += '<p class="empty">아직 쉰 기록이 없어요. 지금 탭에서 쉬기 시작을 눌러 보세요.</p>';
    else h += '<div class="list">' + hist.today.map(function (r) {
      return '<div class="item static"><span class="thumb ' + (r.paid_min ? "paid" : "") + '">' + ic(r.paid_min ? "check" : "close") + '</span>' +
        '<span class="txt"><span class="name fig">' + r.start.slice(11) + ' ~ ' + r.end.slice(11) + '</span><span class="sub">' + (r.place === "shelter" ? "쉼터" : "그 밖의 곳") + ', ' + (r.paid_min ? r.paid_min + "분치 적립" : "적립 안 됨") + '</span></span>' +
        '<b class="amt fig">' + won(r.amount) + '</b></div>';
    }).join("") + '</div>';
    return h + (hist.has_virtual ? '<p class="note">이번 달 합계에는 시연용 가상 기록이 들어 있어요.</p>' : '');
  }


  // ---------- 렌더 ----------
  var seq = 0;
  function render() {
    var my = ++seq, v = S.view, p = pos();
    share();
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
    else job = api("history", { rider_id: 1 }).then(vHistory);
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
  // 지자체 화면(admin.html)을 옆 창에 띄우면 이 시각을 따라간다. 쉼을 시작·끝낼 때도 다시 알린다.
  var chan = "BroadcastChannel" in window ? new BroadcastChannel("shimpyo-demo") : null;
  function share() { if (chan && S.cfg && S.cfg.demo) chan.postMessage({ min: S.min }); }
  if (chan) chan.onmessage = function (e) { if (e.data && e.data.ask) share(); };
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
        function () { S.banner = "<b>위치를 못 받았어요.</b> 관악구청 기준으로 보여드려요. 브라우저에서 위치 권한을 켜 주세요."; render(); }, { timeout: 8000 });
      render();
    } else render();
  }).catch(function () { screen.innerHTML = '<div class="banner" role="alert">서버에 연결되지 않아요. 터미널에서 백엔드를 실행했는지 확인하세요.</div>'; });

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(function () {});
})();
