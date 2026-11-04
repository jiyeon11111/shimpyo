/* 쉼표 앱. 화면마다 백엔드 API 하나를 부른다.
   시연 모드에서는 모든 요청에 at=HH:MM(시연 시각)을 붙이고, 위치는 서교동으로 고정한다. */
(function () {
  "use strict";
  var S = { cfg: null, view: "splash", min: 840, place: "shelter", filter: "near", toast: null, lat: null, lon: null, busy: false };
  var screen = document.getElementById("screen"), dock = document.getElementById("dock"), phone = document.getElementById("phone");

  // ---------- 공통 ----------
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function hhmm(m) { return pad(Math.floor(m / 60)) + ":" + pad(m % 60); }
  function won(x) { return Math.round(x).toLocaleString("ko-KR") + "원"; }
  function at() { return S.cfg && S.cfg.demo ? hhmm(S.min) : null; }
  function q(params) {
    var a = at(); if (a) params.at = a;
    return Object.keys(params).map(function (k) { return k + "=" + encodeURIComponent(params[k]); }).join("&");
  }
  function api(path, params, body) {
    var opt = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ at: at() }, body)) } : {};
    var url = "/api/" + path + (params ? "?" + q(params) : "");
    return fetch(url, opt).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || "요청 실패"); return j; });
    });
  }
  function pos() { return { lat: S.lat, lon: S.lon }; }
  var DOW = ["일", "월", "화", "수", "목", "금", "토"];

  // ---------- 화면 ----------
  function heat(t) { return t >= 38 ? "var(--ember)" : t >= 35 ? "var(--amber)" : t >= 33 ? "var(--sun)" : t >= 31 ? "var(--warm)" : "var(--cool)"; }
  var STAGE_WHY = {
    pay38: "38도 이상이라 지금 쉬면 시간과 상관없이 보전돼요.",
    pay35: "35도 이상이고 14~17시라 지금 쉬면 보전돼요.",
    no: "보전은 35도 이상인 14~17시, 38도 이상이면 하루 종일이에요."
  };
  function hm(min) { return Math.floor(min / 60) + ":" + pad(min % 60); }

  function vSplash() {
    return '<div class="splash"><canvas id="bigLogo" width="280" height="340" aria-label="쉼표 로고"></canvas>' +
      '<h1>쉼표</h1><p>폭염 시간에 쉬어도<br>소득이 줄지 않게.</p>' +
      '<ol class="how">' +
      '<li><b>더울 때 쉬기 시작을 눌러요</b><span>체감온도 35도 넘는 14~17시, 38도 넘으면 언제든</span></li>' +
      '<li><b>쉬고 나서 끝내기를 눌러요</b><span>쉼터 근처면 바로 인정돼요</span></li>' +
      '<li><b>쉰 만큼 돈이 쌓여요</b><span>1시간에 ' + won(S.cfg ? S.cfg.rate : 17210) + ', 하루 최대 4시간</span></li></ol>' +
      '<div class="foot"><button class="btn" id="goBtn">시작하기</button>' +
      '<span class="note">위치로 체감온도를 확인해요. 위치는 쉼을 기록할 때만 저장해요.</span></div></div>';
  }

  function strip(now, cur) {
    var nowH = +now.time.slice(11, 13), restFrom = cur && cur.resting ? +cur.start.slice(11, 13) : null;
    var pays = now.hours.filter(function (x) { return x.pay; }).map(function (x) { return x.h; });
    var range = pays.length ? pays[0] + "시~" + (pays[pays.length - 1] + 1) + "시" : "없음";
    return '<div class="strip" aria-label="오늘 시간대별 체감온도">' +
      '<div class="cells">' + now.hours.map(function (x) {
        var cls = (x.h === nowH ? "now " : "") + (restFrom !== null && x.h >= restFrom && x.h <= nowH ? "rest" : "");
        return '<i class="' + cls + '" style="background-color:' + heat(x.temp) + '" title="' + x.h + '시 ' + x.temp + '도"></i>';
      }).join("") + '</div>' +
      '<div class="pay">' + now.hours.map(function (x) { return '<b class="' + (x.pay ? "on" : "") + '"></b>'; }).join("") + '</div>' +
      '<div class="ticks fig"><span>6시</span><span>10</span><span>14</span><span>18</span><span>22시</span></div>' +
      '<div class="key"><b></b>오늘 쉬면 돈 받는 시간: ' + range + '</div></div>';
  }

  // 홈 맨 위 한 문장: 라이더가 제일 먼저 알아야 할 것 = 지금 쉬면 돈이 나오는가
  function verdict(now, hist) {
    if (hist.today_left_min <= 0) return { h: "오늘 받을 수 있는 만큼 다 받았어요", s: "하루 최대 4시간까지예요. 그래도 더우면 꼭 쉬세요." };
    if (now.pay_now) return { h: "지금 쉬면 돈을 받아요", s: (now.temp >= 38 ? "38도가 넘어서" : "35도가 넘는 오후라") + " " + now.pay_until + "시까지 쉰 만큼 받아요." };
    if (now.next_pay) return { h: "지금은 쉬어도 돈이 안 나와요", s: now.next_pay + "시부터 받을 수 있어요. " + (now.temp >= 33 ? "그래도 더우니 물 자주 드세요." : "") };
    return { h: "오늘은 돈 받는 시간이 끝났어요", s: "35도 넘는 14~17시, 38도 넘으면 언제든 받아요." };
  }

  function shelterLine(sh) {
    if (!sh) return "";
    return '<button class="row link" data-go="shelter"><span>' + (sh.inside ? "지금 쉼터 근처예요" : "가까운 쉼터") + '</span>' +
      '<span class="val">' + sh.name + ', 도보 ' + sh.walk_min + '분</span></button>';
  }

  function vHome(now, cur, hist) {
    var h = '<div class="home"><div class="head"><h1>' + now.place + '</h1><span class="side">' + now.stage.name + ' 단계</span></div>';
    if (S.toast) h += '<div class="done" role="status">' + S.toast + '</div>';
    if (!cur.resting) {
      var v = verdict(now, hist), payNow = now.pay_now && hist.today_left_min > 0;
      h += '<div class="reading"><div class="verdict' + (payNow ? " on" : "") + '">' + v.h + '</div><p class="why">' + v.s + '</p>' +
        '<div class="temp"><span class="sw big" style="background:' + heat(now.temp) + '"></span>' + now.temp.toFixed(1) + '<sup>°</sup><small>체감온도</small></div></div>';
      h += strip(now, null);
      h += '<div class="ledger">' + shelterLine(now.shelter) +
        '<div class="row"><span>오늘 받은 돈</span><span class="val">' + won(hist.today_paid_min / 60 * now.rate) + '</span></div>' +
        '<button class="btn big' + (payNow ? "" : " quiet") + '" id="startBtn"' + (S.busy ? " disabled" : "") + '>' +
        (S.busy ? "시작하는 중" : payNow ? "지금 쉬기 시작" : "그래도 쉬기 시작") +
        '<small>' + (payNow ? "1시간 쉬면 " + won(now.rate) + " 적립" : "돈 받는 시간이 아니라 기록만 남아요") + '</small></button></div>';
    } else {
      var left = Math.max(0, hist.today_left_min - cur.paid_min), msg;
      if (left <= 0) msg = "오늘 한도 4시간을 다 채웠어요. 이제 끝내도 돼요.";
      else if (now.pay_now) msg = "1시간 더 쉬면 " + won(Math.min(60, left) / 60 * now.rate) + " 더 쌓여요.";
      else msg = "지금은 돈 받는 시간이 아니에요. 끝내도 손해 없어요.";
      h += '<div class="reading"><div class="verdict on">쉬는 중이에요</div><p class="why">' + cur.start.slice(11) + '부터, ' +
        (cur.place === "shelter" ? "쉼터에서 쉬는 걸로 확인됐어요" : "자리에 멈춰 있는지 확인하고 있어요") + '</p>' +
        '<div class="timer">' + hm(cur.rested_min) + '<small>쉰 시간</small></div>' +
        '<div class="earned">지금까지 <span class="fig">' + won(cur.amount) + '</span></div><p class="why">' + msg + '</p></div>';
      h += strip(now, cur);
      h += '<div class="ledger"><button class="btn big stop" id="stopBtn"' + (S.busy ? " disabled" : "") + '>' +
        (S.busy ? "끝내는 중" : "다 쉬었어요, 끝내기") + '<small>' + (cur.amount ? "지금 끝내면 " + won(cur.amount) + " 적립" : "아직 쌓인 돈은 없어요") + '</small></button>' +
        (S.cfg.demo ? '<p class="note center">왼쪽 시연 패널에서 시간을 옮겨 보세요</p>' : '<p class="note center">앱을 닫아도 쉼은 계속 기록돼요</p>') + '</div>';
    }
    return h + '</div>';
  }

  function vShelter(list) {
    return '<div class="head"><h1>쉼터</h1><span class="side">가까운 순</span></div>' +
      '<div class="tabs" role="group" aria-label="쉼터 종류" style="margin-top:16px"><button id="f-near" aria-pressed="' + (S.filter === "near") + '">전체</button><button id="f-rider" aria-pressed="' + (S.filter === "rider") + '">이동노동자 쉼터</button></div>' +
      (list.items.length ? '<ul class="rows">' + list.items.map(function (s) {
        var rider = s.kind.indexOf("라이더") >= 0 || s.kind.indexOf("이동노동자") >= 0;
        return '<li class="' + (rider ? "rider" : "") + '"><div><div class="main">' + (rider ? '<span class="sw"></span>' : '') + s.name + '</div><div class="sub">' + s.kind + (s.hours ? ", " + s.hours : "") + (s.note ? ", " + s.note : "") + '</div></div><span class="val">도보 ' + s.walk_min + '분</span></li>';
      }).join("") + '</ul>' : '<p class="empty">반경 안에 등록된 쉼터가 없어요. 그 밖의 곳으로 쉼을 시작해도 위치 확인 뒤 인정돼요.</p>') +
      '<p class="note" style="margin-top:16px">쉼터 150m 안에서 쉼을 시작하면 바로 인정돼요.' + (list.virtual ? " 지금 목록은 시연용 예시예요." : "") + '</p>';
  }

  function vHistory(hist) {
    var month = +(at() ? S.cfg.demo_date : new Date().toISOString()).slice(5, 7);
    var h = '<div class="head"><h1>내역</h1><span class="side">' + month + '월</span></div>' +
      '<div class="total"><span class="note">이번 달 적립</span><span class="fig">' + won(hist.month.amount) + '</span>' +
      '<p class="note" style="margin-top:8px">' + hist.month.count + '번 쉬어서 ' + hist.month.paid_min + '분 보전, 한 달 한도 ' + S.cfg.monthly_cap_min + '분</p></div>' +
      '<div class="week" aria-label="최근 7일">' + hist.week.map(function (w) {
        var d = new Date(w.date + "T00:00");
        return '<div class="' + (w.today ? "t" : "") + '"><i class="' + (w.rested ? "y" : "") + '"></i>' + DOW[d.getDay()] + '</div>';
      }).join("") + '</div>' +
      '<div class="sect">오늘</div>';
    if (!hist.today.length) h += '<p class="empty">아직 쉰 기록이 없어요. 지금 탭에서 쉼을 시작하세요.</p>';
    else h += '<ul class="rows">' + hist.today.map(function (r) {
      return '<li><div><div class="main fig">' + r.start.slice(11) + ' ~ ' + r.end.slice(11) + '</div><div class="sub">' + (r.place === "shelter" ? "쉼터" : "그 밖의 곳") + ', ' + (r.paid_min ? r.paid_min + "분 보전" : "보전 구간 아님") + '</div></div><span class="val">' + won(r.amount) + '</span></li>';
    }).join("") + '</ul>';
    return h + (hist.has_virtual ? '<p class="note" style="margin-top:16px">이번 달 합계에는 시연용 가상 기록이 들어 있어요.</p>' : '');
  }

  function vReport(r) {
    return '<div class="head"><h1>지역 현황</h1><span class="side fig">' + r.time.slice(11) + ' 기준</span></div>' +
      '<p class="note" style="margin-top:6px">내 위치를 가운데 둔 5km 격자 49칸의 지금 체감온도</p>' +
      '<div class="map">' + r.grid.map(function (c) { return '<i style="background:' + heat(c.temp) + '" class="' + (c.me ? "me" : "") + '" title="' + c.temp + '도">' + c.temp.toFixed(1) + '</i>'; }).join("") + '</div>' +
      '<div class="legend"><span><span class="sw" style="background:var(--sun)"></span>33도</span><span><span class="sw" style="background:var(--amber)"></span>35도</span><span><span class="sw" style="background:var(--ember)"></span>38도 이상</span><span>굵은 테두리가 내 칸</span></div>' +
      '<ul class="rows" style="margin-top:12px">' +
      '<li><span>지금 쉬는 라이더</span><span class="val">' + r.resting + '명</span></li>' +
      '<li><span>오늘 보전한 시간</span><span class="val">' + r.paid_hours + '시간</span></li>' +
      '<li class="miss"><span>위험한데 쉬지 못한 시간</span><span class="val">' + r.missed_hours + '시간</span></li>' +
      '<li><span>오늘 지급 예정</span><span class="val">' + won(r.amount) + '</span></li></ul>' +
      '<p class="note" style="margin-top:14px">쉬지 못한 시간이 많은 곳이 지원이 먼저 필요한 곳이에요.' + (r.virtual ? " 가상 라이더 " + r.virtual_riders + "명으로 계산한 시연 값이에요." : "") + '</p>';
  }

  // ---------- 렌더 ----------
  var seq = 0;
  function render() {
    var my = ++seq, v = S.view, p = pos();
    dock.hidden = v === "splash";
        dock.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-selected", b.dataset.v === v ? "true" : "false"); });
    if (S.cfg && S.cfg.demo) { document.getElementById("clockT").textContent = hhmm(S.min); document.getElementById("clockR").value = S.min; }
    document.getElementById("barTime").textContent = S.cfg && S.cfg.demo ? hhmm(S.min) : new Date().toTimeString().slice(0, 5);
    var job;
    if (v === "splash") job = Promise.resolve(vSplash());
    else if (v === "home") job = Promise.all([api("now", p), api("rest/current", { rider_id: 1 }), api("history", { rider_id: 1 })]).then(function (x) { return vHome(x[0], x[1], x[2]); });
    else if (v === "shelter") job = api("shelters", Object.assign({}, p, S.filter === "rider" ? { kind: "rider" } : {})).then(vShelter);
    else if (v === "history") job = api("history", { rider_id: 1 }).then(vHistory);
    else job = api("report", p).then(vReport);
    return job.then(function (html) {
      if (my !== seq) return;           // 더 최근 요청이 있으면 버린다
      screen.innerHTML = html; bindScreen();
    }).catch(function (e) {
      if (my !== seq) return;
      screen.innerHTML = '<p class="err">' + e.message + '</p><button class="btn" id="retry" style="margin-top:16px">다시 불러오기</button>';
      document.getElementById("retry").onclick = render;
    });
  }
  function bind(id, fn) { var e = document.getElementById(id); if (e) e.onclick = fn; }
  function bindScreen() {
    var bl = document.getElementById("bigLogo"); if (bl) drawLogo(bl, false);
    var ml = document.getElementById("miniLogo"); if (ml) drawLogo(ml, false);
    bind("goBtn", function () { S.view = "home"; render(); });
    bind("startBtn", function () {
      if (S.busy) return; S.busy = true; render();
      api("rest/start", null, { rider_id: 1, lat: S.lat, lon: S.lon, place: "auto" }).then(function () { S.busy = false; S.toast = null; render(); }).catch(showErr);
    });
    bind("stopBtn", function () {
      if (S.busy) return; S.busy = true; render();
      api("rest/stop", null, { rider_id: 1 }).then(function (r) {
        S.busy = false;
        S.toast = r.paid_min ? "<strong>" + won(r.amount) + " 적립됐어요</strong>" + r.start.slice(11) + "부터 " + r.end.slice(11) + "까지 " + r.rested_min + "분 쉬었어요. 내역 탭에서 볼 수 있어요."
          : "<strong>쉼을 끝냈어요</strong>돈 받는 시간이 아니어서 이번엔 적립이 없어요.";
        render();
      }).catch(showErr);
    });
    bind("f-near", function () { S.filter = "near"; render(); });
    bind("f-rider", function () { S.filter = "rider"; render(); });
    screen.querySelectorAll("[data-go]").forEach(function (b) { b.onclick = function () { S.view = b.dataset.go; render(); }; });
  }
  function showErr(e) { S.busy = false; S.toast = "<strong>처리하지 못했어요</strong>" + e.message; render(); }

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
  document.getElementById("reset").onclick = function () { stop(); api("demo/reset", null, {}).then(function () { S.toast = null; setMin(840); }).catch(showErr); };
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
        function () { S.toast = "<strong>위치를 못 받았어요</strong>서교동 기준으로 보여드려요. 브라우저에서 위치 권한을 켜 주세요."; render(); }, { timeout: 8000 });
      render();
    } else render();
  }).catch(function () { screen.innerHTML = '<p class="err">서버에 연결되지 않아요. 터미널에서 백엔드를 실행했는지 확인하세요.</p>'; });

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(function () {});
})();
