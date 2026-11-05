/* 쉼표 지역 현황 (지자체·보험사 담당자용). 라이더 앱과 같은 /api/report, /api/now를 부른다.
   시연 모드에서는 라이더 앱(index.html) 시연 패널의 시각을 BroadcastChannel로 받아 따라간다.
   두 창을 나란히 띄우면 시각을 옮기거나 쉼을 시작·끝낼 때마다 이 화면도 다시 그린다. */
(function () {
  "use strict";
  var S = { cfg: null, min: 840, linked: false };
  var board = document.getElementById("board"), when = document.getElementById("when"), sync = document.getElementById("sync");

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function hhmm(m) { return pad(Math.floor(m / 60)) + ":" + pad(m % 60); }
  function won(x) { return Math.round(x).toLocaleString("ko-KR") + "원"; }
  function esc(t) { return String(t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function heat(t) { return t >= 38 ? "var(--ember)" : t >= 35 ? "var(--amber)" : t >= 33 ? "var(--sun)" : t >= 31 ? "var(--warm)" : "var(--cool)"; }
  function api(path, params) {
    if (S.cfg.demo) params.at = hhmm(S.min);
    var qs = Object.keys(params).map(function (k) { return k + "=" + encodeURIComponent(params[k]); }).join("&");
    return fetch("/api/" + path + "?" + qs).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || "요청을 처리하지 못했어요."); return j; });
    });
  }
  function hotRange(now) {
    var p = now.hours.filter(function (x) { return x.hot; }).map(function (x) { return x.h; });
    return p.length ? p[0] + "~" + (p[p.length - 1] + 1) + "시" : "없음";
  }

  function view(r, now) {
    var h = '<p class="eyebrow">' + esc(now.place) + ' 주변 5km 격자 49칸, 오늘 ' + r.time.slice(0, 10) + '</p>' +
      '<h1 class="title">' + (r.missed_hours > 0 ? "오늘 체감 33도 넘는 시간에 못 쉰 라이더 시간이 " + r.missed_hours + "시간이에요"
        : now.hot ? "33도를 넘었어요. 아직 못 쉰 시간은 없어요" : "지금은 33도 아래예요") + '</h1>';
    h += '<div class="kpis">' +
      '<div><span>지금 쉬는 라이더</span><b class="fig">' + r.resting + '<small>명</small></b></div>' +
      '<div><span>오늘 보전 시간</span><b class="fig">' + r.paid_hours + '<small>시간</small></b></div>' +
      '<div><span>오늘 지급 예정</span><b class="fig amt">' + won(r.amount) + '</b></div>' +
      '<div class="warn"><span>못 쉰 위험 시간</span><b class="fig">' + r.missed_hours + '<small>시간</small></b></div></div>';
    h += '<div class="admin-body"><section class="hero admin-map" aria-label="격자별 체감온도">' +
      '<div class="hero-top"><span class="chip"><i style="background:' + heat(now.temp) + '"></i>기준 칸 ' + now.temp.toFixed(1) + '도, ' + esc(now.stage.name) + ' 단계</span>' +
      '<span class="hero-time fig">33도 이상 ' + hotRange(now) + '</span></div>' +
      '<div class="map">' + r.grid.map(function (c) {
        return '<i style="background:' + heat(c.temp) + '" class="' + (c.me ? "me" : "") + (c.temp < 31 ? " cool" : "") + '" title="격자 ' + c.nx + ',' + c.ny + ' ' + c.temp + '도">' + c.temp.toFixed(1) + '</i>';
      }).join("") + '</div>' +
      '<div class="legend"><span><i style="background:var(--sun)"></i>33도 이상: 보전 기준</span><span><i style="background:var(--amber)"></i>35도 이상</span><span><i style="background:var(--ember)"></i>38도 이상</span><span>흰 테두리: ' + esc(now.place) + '</span></div>' +
      '</section>';
    h += '<div class="admin-side"><div class="sec"><h2>읽는 법</h2></div><ul class="read">' +
      '<li><b>못 쉰 위험 시간</b>은 체감 33도를 넘은 시간에 쉼을 기록하지 않은 라이더 시간의 합이에요. 많은 곳부터 쉼터와 안내를 늘리면 돼요.</li>' +
      '<li><b>오늘 지급 예정</b>은 라이더마다 평소 그 시간대 수입에 쉰 분을 비례한 값이에요. 20분 넘게 쉰 경우만, 한 번에 30분치·하루 4번까지 셉니다.</li>' +
      '<li>보전 대상은 최근 4주 그 시간대에 일했고, 최근 2시간 배달 이동이 80분 이상인 라이더예요. 가상 라이더는 이 조건을 채웠다고 가정했어요.</li>' +
      '<li>판정은 쉼을 시작한 격자로, 재원은 라이더 거주지 지자체로 나눠요.</li></ul>';
    return h + '<p class="note">' + (r.virtual ? "가상 라이더 " + r.virtual_riders + "명과 시연용 기상값으로 계산한 값이에요. 근거로 인용하지 마세요." : "실제 쉼 기록만 집계했어요.") + '</p></div></div>';
  }

  // 리포트 계산이 시연 시계(0.7초마다)보다 느릴 수 있다. 응답을 버리지 않고 그리고 나서, 그사이 시각이 바뀌었으면 한 번 더 부른다.
  var loading = false, again = false;
  function render() {
    sync.textContent = !S.cfg.demo ? "1분마다 새로 불러와요."
      : S.linked ? "라이더 앱 시연 시각을 따라가고 있어요." : "라이더 앱 시연 패널에서 이 창을 열면 그 시각을 따라가요.";
    sync.className = "sync" + (S.linked ? " on" : "");
    if (loading) { again = true; return; }
    loading = true;
    var p = { lat: S.cfg.demo_lat, lon: S.cfg.demo_lon };
    Promise.all([api("report", Object.assign({}, p)), api("now", Object.assign({}, p))]).then(function (x) {
      when.textContent = x[0].time.slice(11) + " 기준";
      board.innerHTML = view(x[0], x[1]);
    }).catch(function (e) {
      board.innerHTML = '<div class="banner" role="alert"><b>현황을 불러오지 못했어요.</b> ' + esc(e.message) + ' 서버가 켜져 있는지 확인하세요.</div>';
    }).then(function () {
      loading = false;
      if (again) { again = false; render(); }
    });
  }

  drawLogo(document.getElementById("miniLogo"), false);
  fetch("/api/config").then(function (r) { return r.json(); }).then(function (cfg) {
    S.cfg = cfg;
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
