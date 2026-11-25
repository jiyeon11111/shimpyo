/* 쉼표 앱. 화면마다 백엔드 API를 부른다.
   흐름: 지금(홈) → 쉬는 중(몰입 화면, 탭 숨김) → 적립 완료(몰입 화면) → 내역.
   지역 현황은 라이더 화면이 아니라서 admin.html(지자체·보험사용)로 뺐다.
   시연 모드에서는 모든 요청에 at=HH:MM(시연 시각)을 붙이고 위치는 관악구청(청룡동)으로 고정한다. */
(function () {
  "use strict";
  var S = { cfg: null, view: "splash", min: 840, filter: "near", done: null, banner: null, from: null, lat: null, lon: null, busy: false };
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
  // 색: 32도 구간은 서버가 반올림 전 값으로 정한 hot을 쓴다 (화면의 32.0이 31.96일 수 있다)
  function heat(t, hot) { return t >= 38 ? "var(--ember)" : t >= 35 ? "var(--amber)" : hot ? "var(--sun)" : t >= 31 ? "var(--warm)" : "var(--cool)"; }
  var DOW = ["일", "월", "화", "수", "목", "금", "토"];
  // 오류 안내: 닫을 수 있고, 탭을 옮기면 사라진다
  function bannerH() { return S.banner ? '<div class="banner" role="alert"><span>' + S.banner + '</span><button class="banner-x" id="bannerX" aria-label="안내 닫기">' + ic("close") + '</button></div>' : ''; }
  function mins(m) { return m < 60 ? m + '<small>분</small>' : Math.floor(m / 60) + '<small>시간</small> ' + (m % 60) + '<small>분</small>'; }

  var ICON = {
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    chev: '<path d="M9 5l7 7-7 7"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    pin: '<path d="M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0113 0c0 4.8-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
    up: '<path d="M12 16V5M7.5 9.5L12 5l4.5 4.5M5 19h14"/>',
    dash: '<path d="M7 12h10"/>',
    doc: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h5M10 16h5"/>',
    back: '<path d="M15 5l-7 7 7 7"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.2"/>'
  };
  function ic(n, cls) { return '<svg class="ic ' + (cls || "") + '" viewBox="0 0 24 24" aria-hidden="true">' + ICON[n] + '</svg>'; }

  // 하루 체감온도 막대: 레퍼런스의 사진 자리. 한 칸이 한 시간, 높이와 색이 체감온도, 밑줄이 기준(32도, 모델 값) 넘는 시간.
  function bars(now, cur) {
    var nowH = +now.time.slice(11, 13), from = cur && cur.resting ? +cur.start.slice(11, 13) : null;
    var lo = 26, hi = 40;
    return '<div class="bars" aria-label="오늘 시간대별 체감온도">' + now.hours.map(function (x) {
      var hgt = Math.max(8, Math.min(100, (x.temp - lo) / (hi - lo) * 100));
      var cls = (x.h === nowH ? " now" : "") + (x.h > nowH ? " later" : "") + (from !== null && x.h >= from && x.h <= nowH ? " rest" : "");
      return '<div class="bar' + cls + '" title="' + x.h + '시 ' + x.temp + '도"><i style="height:' + hgt + '%;background:' + heat(x.temp, x.hot) + '"></i><b class="' + (x.hot ? "pay" : "") + '"></b></div>';
    }).join("") + '</div><div class="bars-axis fig"><span>6시</span><span>12</span><span>18</span><span>22시</span></div>';
  }
  function hotRange(now) {
    var p = now.hours.filter(function (x) { return x.hot; }).map(function (x) { return x.h; });
    return p.length ? p[0] + "~" + (p[p.length - 1] + 1) + "시" : null;
  }
  // 지급 기준 한 줄: 지급은 정산 내역 기반이라 늘 평소 이 시간 수입이다 (서버가 준 시급을 그대로 보여준다)
  function basisText(basis, hourly) { return "평소 이 시간 수입(시간당 " + won(hourly) + ")"; }
  var DEMO_SETTLE_FILE = "가상_정산내역_민수_2026-07.csv";   // 시연용: 가상 라이더 콜 기록으로 만든 정산 내역
  function rules() { var c = S.cfg || {}; return { heat: c.heat_min || 32, need: c.exposure_need_min || 60, rest: c.rest_min || 20, cap: c.pay_cap_min || 30, capWon: c.pay_cap_won || 10000, labor: c.labor_need_days || 10, times: c.daily_rests || 4 }; }

  // ---------- 시작 ----------
  function vSplash() {
    var R = rules();
    return '<div class="splash"><canvas id="bigLogo" width="280" height="340" aria-label="쉼표 로고"></canvas>' +
      '<h1>쉼표</h1><p class="lead">폭염 시간에 쉬어도<br>소득이 줄지 않게.</p>' +
      '<ol class="how">' +
      '<li><b>더운데 배달 중이면 쉬기 시작을 눌러요</b><span>달린 동 체감온도 ' + R.heat + '도 이상, 최근 2시간 배달 이동 ' + R.need + '분 이상, 이 시간대에 최근 4주 중 ' + R.labor + '일 이상 일했으면 돼요</span></li>' +
      '<li><b>' + R.rest + '분 넘게 쉬고 끝내기를 눌러요</b><span>쉬는 동안 콜이 꺼져요</span></li>' +
      '<li><b>평소 이 시간에 벌던 만큼 쌓여요</b><span>배달 앱 정산 내역을 한 번 등록하면 돼요. 한 번에 ' + R.cap + '분치(최대 ' + won(R.capWon) + ')까지, 하루 ' + R.times + '번까지</span></li></ol>' +
      '<div class="foot"><label class="agree"><input type="checkbox" id="agree"><span>위치 사용에 동의해요. 배달 이동과 체감온도 확인에 쓰고, <b>행정동 단위로만 보관</b>해요. 좌표는 저장하지 않아요.</span></label>' +
      '<button class="pillbtn dark full" id="goBtn" disabled>동의하고 시작하기</button></div></div>';
  }

  // ---------- 지금 (홈) ----------
  function verdict(now, hist) {
    var R = rules();
    if (hist.today_left_rests <= 0) return { h: "오늘 받을 만큼 다 받았어요", s: "하루 " + R.times + "번까지예요. 그래도 더우면 꼭 쉬세요." };
    if (now.pay_now) return { h: "지금 쉬면 돈을 받아요", s: R.rest + "분 넘게 쉬면 평소 이 시간 수입만큼 쌓여요" };
    return { h: "지금은 적립 대상이 아니에요", s: now.reasons[0] || "" };
  }

  function shelterRow(s, link) {
    var rider = s.rider;   // 이동노동자 쉼터 여부는 서버가 정한다
    var inner = '<span class="thumb' + (rider ? " rider" : "") + '"><b class="fig">' + s.walk_min + '</b><small>분</small></span>' +
      '<span class="txt"><span class="name">' + esc(s.name) + '</span><span class="sub">' + (rider ? "이동노동자 쉼터" : esc(s.kind)) + (s.hours ? ", " + esc(s.hours) : "") + '</span>' +
      (s.distance_m <= 150 ? '<span class="tag">여기서 쉬면 바로 인정</span>' : '') + '</span>' + ic("chev", "chev");
    if (link && s.lat) return '<a class="item" target="_blank" rel="noopener" href="https://map.kakao.com/link/to/' + encodeURIComponent(s.name) + ',' + s.lat + ',' + s.lon + '" aria-label="' + esc(s.name) + ' 길찾기">' + inner + '</a>';
    return '<button class="item" data-go="shelter">' + inner + '</button>';
  }

  // 조건 한 줄: 됐는지(체크), 이름, 설명, 오른쪽 값, (있으면) 진행 막대
  function check(ok, label, sub, val, frac) {
    return '<div class="ck' + (ok ? " ok" : " no") + '"><span class="ck-i">' + ic(ok ? "check" : "dash") + '</span>' +
      '<span class="ck-t"><b>' + label + '</b><small>' + sub + '</small>' +
      (frac == null ? '' : '<i class="meter"><i style="width:' + Math.round(Math.min(1, frac) * 100) + '%"></i></i>') + '</span>' +
      '<span class="ck-v fig">' + val + '</span></div>';
  }

  // 홈 맨 위 응원 한마디. 날씨와 오늘 쉰 기록에 맞춰 고른다. 같은 상황에서는 하루 동안 같은 문장이 나온다.
  function cheer(now, hist, L, payNow) {
    var name = L && L.rider_name ? esc(L.rider_name) + " 님, " : "", hr = Math.floor(S.cfg && S.cfg.demo ? S.min / 60 : new Date().getHours());
    var set = hist.today_paid_rests > 0 ? ["잘 쉬었어요. 남은 배달도 무리하지 말고 가요.", "쉬어 간 만큼 더 안전하게 달릴 수 있어요."]
      : payNow ? ["많이 덥죠. 쉬는 것도 일이에요.", "오늘 같은 날은 잠깐 쉬어 가도 괜찮아요."]
      : now.hot ? ["더운 날 달리느라 고생 많아요. 물 한 모금 하고 가요.", "뜨거운 길 위에서 오늘도 수고가 많아요."]
      : hr < 11 ? ["오늘도 안전하게 다녀와요.", "좋은 아침이에요. 천천히 시작해요."]
      : hr >= 19 ? ["오늘 하루도 수고 많았어요. 끝까지 안전하게.", "늦은 시간까지 고생이 많아요."]
      : ["오늘도 무리하지 말고 달려요.", "안전이 먼저예요. 오늘도 수고 많아요."];
    var day = S.cfg && S.cfg.demo ? 3 : new Date().getDate();
    return '<b>' + name + '</b>' + set[day % set.length];
  }
  function vHome(now, cur, hist, near) {
    var v = verdict(now, hist), R = rules(), L = now.link;
    var payNow = L.pays && now.pay_now && hist.today_left_rests > 0, mock = !L.pays && now.pay_now;   // mock: 등록 전이라 조건만 맞는 상태
    var expect = Math.min(R.cap / 60 * L.pay_hourly, R.capWon), night = now.reasons.some(function (x) { return /22시/.test(x); });
    var h = '<header class="brand"><span class="word"><canvas id="miniLogo" width="56" height="68" aria-hidden="true"></canvas>쉼표</span>' +
      '<span class="brand-r"><span class="loc">' + ic("pin") + now.place + '</span><button class="iconbtn lite" id="infoBtn" aria-label="판정 기준과 자료 안내">' + ic("info") + '</button></span></header>';
    h += '<p class="cheer">' + cheer(now, hist, L, payNow) + '</p>';
    h += bannerH();
    // 1) 지금 쉬면 받는지: 화면에서 가장 큰 한 덩어리
    h += payNow
      ? '<section class="verdict ok" aria-label="지금 쉬면 받는 돈"><p class="vk">지금 쉬면</p>' +
        '<h1><b class="fig">' + (expect > 0 ? won(expect) : "돈을") + '</b> 받아요</h1>' +
        '<p class="vs">' + R.cap + '분 쉬었을 때. ' + R.rest + '분은 넘겨야 쌓여요</p>' +
        '<span class="vtag">평소 이 시간 수입 시간당 ' + won(L.pay_hourly) + ' 기준</span></section>'
      : mock
      ? '<section class="verdict mock" aria-label="모의 판정"><p class="vk">모의 판정, ' + now.time.slice(11) + ' 기준</p>' +
        '<h1>지금은 쉬면 돈을 받는 조건이에요</h1><p class="vs">정산 내역을 등록하면 평소 이 시간에 벌던 만큼 받아요. 지금은 알림과 쉼터 안내만 해요.</p>' +
        '<button class="bigbtn dark" data-go="register">정산 내역 등록하기</button></section>'
      : '<section class="verdict" aria-label="지금 쉬면 받는 돈"><p class="vk">' + now.time.slice(11) + ' 기준</p>' +
        '<h1>' + v.h + '</h1><p class="vs">' + esc(v.s) + '</p></section>';
    // 2) 조건 세 가지: 서버가 준 값을 그대로 보여준다
    h += '<section class="card checks" aria-label="적립 조건">';
    if (now.has_record) {
      h += check(now.hot && !!now.judge_dong, "체감온도 " + R.heat + "도 이상", now.judge_dong ? esc(now.judge_dong.name) + (now.hot ? ", 최근 1시간 가장 오래 달린 동" : ", 지금은 " + R.heat + "도보다 낮아요") : "최근 1시간 달린 동이 없어요", now.temp.toFixed(1) + "°") +
        check(now.exposure_min >= R.need, "배달 이동 " + R.need + "분 이상", now.exposure_min >= R.need ? "최근 2시간" : "최근 2시간, " + (R.need - now.exposure_min) + "분 더 달리면 돼요", now.exposure_min + "분", now.exposure_min / R.need) +
        check(!night && now.worked_days >= R.labor, "이 시간대에 " + R.labor + "일 이상 근무", night ? "22시~6시는 적립 시간대가 아니에요" : now.worked_days >= R.labor ? "최근 4주" : "최근 4주, " + (R.labor - now.worked_days) + "일 더 일하면 돼요", night ? "-" : now.worked_days + "일");
    } else h += check(false, "운행 기록 연결 전", esc(now.reasons[0] || ""), "-");
    h += '</section>';
    // 3) 오늘 체감온도
    h += '<section class="card tempcard" aria-label="오늘 체감온도"><div class="card-h"><b>오늘 체감온도</b>' +
      '<span class="chip lite"><i style="background:' + heat(now.temp, now.hot) + '"></i>지금 ' + now.temp.toFixed(1) + '° ' + now.stage.name + '</span></div>' +
      bars(now, null) + (hotRange(now) ? '<p class="card-s">밑줄 친 ' + hotRange(now) + '가 ' + R.heat + '도 이상이에요</p>' : '<p class="card-s">오늘은 ' + R.heat + '도를 넘는 시간이 없어요</p>') + '</section>';
    // 4) 오늘 현황
    h += '<div class="duo"><div class="card"><span>오늘 받은 돈</span><b class="fig">' + won(hist.today_amount) + '</b></div>' +
      '<div class="card"><span>오늘 남은 횟수</span><b class="fig">' + hist.today_left_rests + '<small> / ' + R.times + '번</small></b></div></div>';
    if (L.can_upload && !mock) h += '<button class="rowlink" data-go="register"><span><b>정산 내역을 등록하면 쉴 때 돈을 받아요</b><small>지금은 폭염 알림과 쉼터 안내만 해요</small></span>' + ic("chev", "chev") + '</button>';
    if (near.items.length) h += '<div class="sec"><h2>가까운 쉼터</h2><button class="more" data-go="shelter">전체 보기</button></div>' +
      '<div class="list">' + shelterRow(near.items[0], false) + '</div>';
    // 5) 아래 고정 버튼
    h += '<div class="cta"><button class="bigbtn ' + (payNow ? "go" : "line") + '" id="startBtn"' + (S.busy ? " disabled" : "") + '>' +
      (S.busy ? "시작하는 중" : payNow ? "쉬기 시작" : "적립 없이 쉬기") + '</button></div>';
    return h;
  }

  // ---------- 정산 내역 등록 (가입 2단계) ----------
  function vRegister() {
    var demo = S.cfg.demo;
    return '<div class="onb">' + (S.from ? backH() : '<p class="onb-step">2 / 2 단계</p>') + '<h1 class="title">정산 내역을 한 번 등록해 주세요</h1>' +
      '<p class="onb-lead">쉬는 동안 못 번 돈을 드리려면 평소에 얼마를 버는지 알아야 해요. 배달 앱의 정산 내역(최근 4주)을 올려 주세요.</p>' +
      '<ul class="onb-list"><li>' + ic("check") + '<span><b>평소 이 시간에 벌던 만큼 받아요</b>같은 요일, 같은 시각의 최근 4주 평균이에요</span></li>' +
      '<li>' + ic("check") + '<span><b>한 번만 등록하면 돼요</b>한 달에 한 번 위치 기록과 대조해요</span></li>' +
      '<li>' + ic("check") + '<span><b>등록 전에도 쓸 수 있어요</b>폭염 알림, 쉼터 안내, 모의 판정은 그대로예요. 돈은 등록한 뒤부터 쌓여요</span></li></ul>' +
      (demo ? '<div class="filecard"><span class="file-i">' + ic("doc") + '</span><span class="txt"><span class="name">' + DEMO_SETTLE_FILE + '</span><span class="sub">시연용 가상 정산 내역 (가상 라이더 콜 기록으로 만든 값)</span></span></div>' : '') +
      '<div class="foot"><button class="bigbtn go" id="regBtn"' + (S.busy ? " disabled" : "") + '>' + ic("up") + (S.busy ? "등록하는 중" : demo ? "가상 정산 내역 등록하기" : "정산 내역 올리기") + '</button>' +
      '<button class="textbtn dim" id="regSkip">' + (S.from ? "취소" : "나중에 할게요") + '</button></div></div>';
  }

  function backH() { return '<button class="backbtn" id="onbBack" aria-label="뒤로">' + ic("back") + '뒤로</button>'; }

  // ---------- 평소 수입 확인 (정산 내역에서 읽은 값) ----------
  var WD = ["월", "화", "수", "목", "금", "토", "일"];
  function vSettle(sm) {
    var R = rules(), mx = Math.max.apply(null, sm.hours.map(function (x) { return x.usual_hourly; }).concat([1]));
    var chart = '<div class="ubars" aria-label="시간대별 평소 시간당 수입">' + sm.hours.map(function (x) {
      return '<div class="ubar' + (x.h === sm.hour ? " now" : "") + '" title="' + x.h + '시 ' + won(x.usual_hourly) + '"><i style="height:' + Math.max(3, x.usual_hourly / mx * 100) + '%"></i></div>';
    }).join("") + '</div><div class="bars-axis fig"><span>6시</span><span>12</span><span>18</span><span>22시</span></div>';
    return '<div class="onb">' + (S.from === "me" ? backH() : '') + '<div class="okmark sm">' + ic("check") + '</div>' +
      '<h1 class="title">' + (sm.registered ? "정산 내역에서 평소 수입을 읽었어요" : "아직 정산 내역이 없어요") + '</h1>' +
      '<p class="onb-lead">' + (sm.file ? esc(sm.file) + ', 최근 ' + sm.weeks + '주' + (sm.status_name ? ', ' + esc(sm.status_name) : '') : '플랫폼 운행 기록, 최근 ' + sm.weeks + '주') + '</p>' +
      '<section class="card usual"><p class="sc-k">' + WD[sm.weekday] + '요일 ' + sm.hour + '시, 평소 시간당 수입</p>' +
      '<p class="usual-v fig">' + won(sm.usual_hourly) + '</p>' +
      '<div class="kv"><span>' + R.cap + '분 쉬면 받는 돈</span><b class="fig">' + won(sm.per_rest) + '</b></div>' +
      '<div class="kv"><span>계산</span><b>최근 4주 같은 요일·같은 시각 평균</b></div></section>' +
      '<section class="card"><div class="card-h"><b>' + WD[sm.weekday] + '요일 시간대별 평소 수입</b></div>' + chart +
      '<p class="card-s">일하지 않던 시간은 0원이라, 그 시간에 쉬면 돈이 쌓이지 않아요</p></section>' +
      (sm.virtual ? '<p class="note">시연용 가상 정산 내역이에요. 실제 라이더의 수입이 아니에요.</p>' : '') +
      '<div class="foot"><button class="bigbtn go" id="settleOk">' + (S.from === "me" ? "확인" : "홈으로 가기") + '</button></div></div>';
  }

  // ---------- 판정 기준·자료 안내 (정보 버튼) ----------
  function vInfo(now) {
    var R = rules();
    return '<div class="msheet" role="dialog" aria-modal="true" aria-label="판정 기준과 자료 안내"><i class="grab"></i>' +
      '<header class="m-h"><h2>이렇게 판정해요</h2><button class="iconbtn lite" id="infoX" aria-label="닫기">' + ic("close") + '</button></header>' +
      '<ul class="m-list">' +
      '<li><b>언제 받나요</b>최근 1시간 가장 오래 달린 동의 체감온도가 ' + R.heat + '도 이상이고, 최근 2시간 배달 이동이 ' + R.need + '분 이상이고, 이 시간대에 최근 4주 중 ' + R.labor + '일 이상 일했을 때예요.</li>' +
      '<li><b>얼마를 받나요</b>' + R.rest + '분 넘게 쉬면 평소 이 시간에 벌던 만큼(최근 4주 같은 요일·같은 시각 평균)을 쉰 분만큼 받아요. 한 번에 ' + R.cap + '분치(최대 ' + won(R.capWon) + ')까지, 하루 ' + R.times + '번까지예요.</li>' +
      '<li><b>정산 내역</b>평소 수입은 가입할 때 한 번 등록한 배달 앱 정산 내역으로 확인해요. 등록 전에는 폭염 알림, 쉼터 안내, 모의 판정만 해요. 플랫폼이 연결되면 등록 없이 자동으로 들어와요.</li>' +
      '<li><b>체감온도</b>' + (now && now.judge_dong ? '지금은 ' + esc(now.judge_dong.name) + ' 값이에요. ' : '') + '쉼표 행정동 모델 값이에요(기상청 AWS·ASOS 관측과 서울시 S-DoT 센서로 학습).</li>' +
      '<li><b>위치</b>배달 이동과 체감온도 확인에만 쓰고, 행정동 단위로만 보관해요. 좌표는 저장하지 않아요.</li>' +
      (now && now.virtual_rider ? '<li><b>시연 안내</b>운행 기록과 평소 수입은 시연용 가상 라이더 값이에요.</li>' : '') +
      '</ul><p class="m-src">동 경계: 통계청 기반 행정동 경계. 판정 기준: 팀 확정안(2026.11.9).</p></div>';
  }

  // ---------- 내 정보 ----------
  function vMe(L, hist) {
    var steps = (S.cfg.stages || []).map(function (x, i, arr) {
      var idx = arr.map(function (y) { return y.stage; }).indexOf(L.stage);
      return '<li class="' + (i < idx ? "done" : i === idx ? "now" : "") + '"><i>' + (i < idx ? ic("check") : x.stage) + '</i><span>' + esc(x.name) + '</span></li>';
    }).join("");
    var h = '<h1 class="title top">내 정보</h1>' + bannerH() +
      '<section class="card me"><span class="avatar">' + esc((L.rider_name || "라").slice(0, 1)) + '</span><span class="txt"><span class="name">' + esc(L.rider_name || "라이더") + '</span>' +
      '<span class="sub">이번 달 ' + hist.month.count + '번 쉬고 ' + won(hist.month.amount) + ' 받았어요</span></span></section>';
    h += '<div class="sec"><h2>지급 기준</h2></div><section class="card stagecard">' +
      '<ol class="steps">' + steps + '</ol>' +
      '<p class="sc-k">' + L.stage + '단계 ' + esc(L.name) + '</p>' +
      '<p class="sc-v">' + (L.pays ? "평소 이 시간에 벌던 만큼" : "지급 없음, 모의 판정만") + '</p>' +
      (L.can_upload
        ? '<p class="sc-s">정산 내역을 등록하면 쉴 때 평소 이 시간 수입만큼 받아요. 지금은 폭염 알림과 쉼터 안내만 해요.</p>' +
          '<button class="bigbtn dark" data-go="register">' + ic("up") + '정산 내역 등록하기</button>'
        : L.stage === "B"
          ? '<p class="sc-s">등록한 정산 내역으로 평소 수입을 확인해요. 한 달에 한 번 위치 기록과 대조해요.</p>' +
            '<div class="kv"><span>정산 내역</span><b>' + esc(L.settle_file || "등록됨") + '</b></div><div class="kv"><span>대조 상태</span><b>' + esc(L.settle_name || "확인 완료") + '</b></div>' +
            '<button class="kv nav" data-go="settle"><span>시간대별 평소 수입 보기</span>' + ic("chev", "chev") + '</button>'
          : '<p class="sc-s">배달 플랫폼 운행 기록이 자동으로 들어와요. 정산 내역을 올리지 않아도 돼요.</p>' +
            '<button class="kv nav" data-go="settle"><span>시간대별 평소 수입 보기</span>' + ic("chev", "chev") + '</button>') +
      '</section>';
    h += '<div class="sec"><h2>설정</h2></div><div class="card rows">' +
      '<div class="kv"><span>위치 사용 동의</span><b>' + (L.consent ? "동의함" : "동의 전") + '</b></div>' +
      '<div class="kv"><span>위치 보관</span><b>행정동 단위</b></div>' +
      '<button class="kv nav" id="infoBtn"><span>판정 기준과 자료 안내</span>' + ic("chev", "chev") + '</button></div>';
    return h + (S.cfg.demo ? '<p class="note">시연 모드예요. 라이더 정보와 운행 기록은 지어낸 값이에요.</p>' : '');
  }

  // ---------- 쉬는 중 (몰입 화면) ----------
  function vResting(now, cur, hist, near) {
    var Q = rules(), times = Q.times, done = hist.today_paid_rests, counting = cur.eligible && done < times;
    var frac = counting ? Math.min(cur.rested_min, Q.cap) / Q.cap : 0, R = 92, C = 2 * Math.PI * R;
    var ta = 2 * Math.PI * Q.rest / Q.cap, tx = 110 + R * Math.cos(ta), ty = 110 + R * Math.sin(ta);   // 적립이 시작되는 20분 자리
    var sh = cur.place !== "shelter" && near && near.items.length ? near.items[0] : null;
    // 적립 대상이 아니거나 오늘 횟수를 다 썼으면 맨 위 알림으로 알린다. 아래 한 줄은 다음 적립까지 남은 분만 말한다.
    var notice = !cur.eligible ? ["이번 쉼은 돈이 쌓이지 않아요", esc(cur.reason || "") + ". 그래도 더우면 쉬어 가세요."]
      : done >= times ? ["오늘 " + times + "번을 다 받았어요", "이번 쉼은 돈이 쌓이지 않아요. 편하게 쉬다 가세요."] : null;
    var msg = !counting ? ""
      : cur.rested_min < Q.rest ? (Q.rest - cur.rested_min) + "분 더 쉬면 적립돼요"
      : cur.rested_min < Q.cap ? (Q.cap - cur.rested_min) + "분 더 쉬면 " + won(Math.min(Q.cap / 60 * cur.pay_hourly, Q.capWon)) + "까지 쌓여요"
      : "이번 쉼은 최대치를 채웠어요. 끝내도 돼요.";
    var used = done + (cur.paid_min > 0 ? 1 : 0);
    var segs = ""; for (var i = 0; i < times; i++) segs += '<i class="' + (i < done ? "full" : i < used ? "part" : "") + '"></i>';
    return '<div class="immersive">' +
      '<header class="ibar"><span></span><h1>쉬는 중</h1><span></span></header>' + bannerH() +
      (notice ? '<div class="inotice" role="status">' + ic("info") + '<span><b>' + notice[0] + '</b>' + notice[1] + '</span></div>' : '') +
      '<div class="ichip">' + cur.start.slice(11) + '부터, ' + (cur.place === "shelter" ? "쉼터에서 확인됨" : "자리 확인 중") + '</div>' +
      // 원 전체가 끝내기 버튼이다
      '<button class="ring" id="stopBtn"' + (S.busy ? " disabled" : "") + ' aria-label="' + cur.rested_min + '분 쉬었어요. 눌러서 쉼 끝내기">' +
      '<svg viewBox="0 0 220 220" aria-hidden="true"><circle cx="110" cy="110" r="' + R + '" class="track"/>' +
      '<circle cx="110" cy="110" r="' + R + '" class="prog" stroke-dasharray="' + C + '" stroke-dashoffset="' + (C * (1 - frac)) + '"/>' +
      (counting ? '<circle cx="' + tx.toFixed(1) + '" cy="' + ty.toFixed(1) + '" r="5" class="tick' + (cur.rested_min >= Q.rest ? " on" : "") + '"/>' : '') + '</svg>' +
      '<span class="ring-in"><b class="fig' + (cur.rested_min >= 60 ? " long" : "") + '">' + mins(cur.rested_min) + '</b><em>' + (S.busy ? "끝내는 중" : "눌러서 끝내기") + '</em></span></button>' +
      '<div class="earned"><span>지금까지</span><b class="fig">' + won(cur.amount) + '</b></div>' +
      (cur.eligible ? '<p class="ibasis">' + basisText(cur.basis, cur.pay_hourly) + ' 기준</p>' : '') +
      (msg ? '<p class="inext">' + msg + '</p>' : '') +
      '<div class="iday"><div class="segs">' + segs + '</div><span class="fig">오늘 ' + used + '번 / ' + times + '번</span></div>' +
      (sh && sh.lat ? '<a class="sheet-link" target="_blank" rel="noopener" href="https://map.kakao.com/link/to/' + encodeURIComponent(sh.name) + ',' + sh.lat + ',' + sh.lon + '"><span><b>' + esc(sh.name) + '</b><small>걸어서 ' + sh.walk_min + '분, 길찾기</small></span>' + ic("chev", "chev") + '</a>' : '') +
      '<section class="card itemp" aria-label="오늘 체감온도"><div class="card-h"><b>오늘 체감온도</b>' +
      '<span class="chip lite"><i style="background:' + heat(now.temp, now.hot) + '"></i>지금 ' + now.temp.toFixed(1) + '°</span></div>' + bars(now, cur) +
      '<p class="card-s">줄무늬는 쉬고 있는 시간이에요.' + (S.cfg.demo ? '' : ' 앱을 닫아도 계속 기록돼요.') + '</p></section>' +
      '</div>';
  }

  // ---------- 적립 완료 (몰입 화면) ----------
  function vDone(d, now, hist) {
    var s = +d.start.slice(11, 13), e = +d.end.slice(11, 13), peak = 0;
    now.hours.forEach(function (x) { if (x.h >= s && x.h <= e) peak = Math.max(peak, x.temp); });
    var paid = d.paid_min > 0;
    return '<div class="immersive done-screen">' +
      '<header class="ibar"><span></span><span></span><span></span></header>' +
      '<div class="okmark' + (paid ? "" : " muted") + '">' + ic("check") + '</div>' +
      '<h1 class="done-title">' + (paid ? won(d.amount) + " 적립됐어요" : "쉼을 끝냈어요") + '</h1>' +
      '<p class="done-sub fig">' + d.start.slice(11) + ' ~ ' + d.end.slice(11) + ', ' + now.place + '</p>' +
      (paid ? '<p class="done-basis">' + basisText(d.basis, d.pay_hourly) + ' 기준 ' + d.paid_min + '분치</p>' : '') +
      '<div class="trio"><div><b class="fig">' + d.rested_min + '<small>분</small></b><span>쉰 시간</span></div>' +
      '<div><b class="fig">' + peak.toFixed(1) + '<small>°</small></b><span>최고 체감온도</span></div>' +
      '<div><b class="fig">' + hist.today_left_rests + '<small>번</small></b><span>오늘 남은 횟수</span></div></div>' +
      (paid ? '' : '<p class="done-note">이번엔 돈이 쌓이지 않았어요. ' + esc(d.reason || "") + '.</p>') +
      '<p class="done-k">이번 주 쉰 날</p><div class="weekdots">' + hist.week.map(function (w) {
        var dd = new Date(w.date + "T00:00");
        return '<div class="' + (w.today ? "t" : "") + '"><i class="' + (w.rested ? "y" : "") + '">' + (w.rested ? ic("check") : "") + '</i>' + DOW[dd.getDay()] + '</div>';
      }).join("") + '</div>' +
      '<div class="done-actions"><button class="pillbtn light full" id="doneOk">확인</button><button class="textbtn" id="toHistory">내역 보기</button></div></div>';
  }

  // ---------- 쉼터 ----------
  function vShelter(list) {
    return '<h1 class="title top">쉼터</h1><p class="eyebrow">가까운 순, 누르면 카카오맵 길찾기</p>' +
      '<div class="chips" role="group" aria-label="쉼터 종류"><button id="f-near" aria-pressed="' + (S.filter === "near") + '">전체</button><button id="f-rider" aria-pressed="' + (S.filter === "rider") + '">이동노동자 쉼터</button></div>' +
      (list.items.length ? '<div class="list">' + list.items.map(function (s) { return shelterRow(s, true); }).join("") + '</div>'
        : '<p class="empty">반경 안에 등록된 쉼터가 없어요. 아무 데서나 쉬기 시작해도 자리 확인 뒤 인정돼요.</p>') +
      '<p class="note">쉼터 150m 안에서 쉬기 시작하면 바로 인정돼요.' + (list.virtual ? " 지금 목록은 시연용 예시예요. 실제 운영 때는 행정안전부 무더위쉼터 목록을 써요." : " 자료: 행정안전부 무더위쉼터 · 서울노동포털 이동노동자 쉼터.") + '</p>';
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
        '<span class="txt"><span class="name fig">' + r.start.slice(11) + ' ~ ' + r.end.slice(11) + '</span><span class="sub">' + (r.place === "shelter" ? "쉼터" : "그 밖의 곳") + ', ' + (r.paid_min ? r.paid_min + "분치 적립" : "적립 안 됨") + '</span>' +
        (r.paid_min ? '<span class="tag">평소 수입 시간당 ' + won(r.pay_hourly != null ? r.pay_hourly : r.usual_hourly) + '</span>' : '') + '</span>' +
        '<b class="amt fig">' + won(r.amount) + '</b></div>';
    }).join("") + '</div>';
    return h + (hist.has_virtual ? '<p class="note">이번 달 합계에는 시연용 가상 기록이 들어 있어요.</p>' : '');
  }


  // ---------- 렌더 ----------
  var seq = 0, lastKey = null, lastNow = null;
  var themeMeta = document.querySelector('meta[name="theme-color"]');
  var ONBOARD = { splash: 1, register: 1, settle: 1 };   // 가입 흐름 화면: 아래 탭을 숨긴다
  var modal = document.getElementById("modal");
  var modalKind = null, modalFrom = null, lastCur = null;
  function openModal(kind, html, focusId) {
    modalFrom = document.activeElement; modalKind = kind; modal.innerHTML = html; modal.hidden = false;
    var f = document.getElementById(focusId); if (f) f.focus();
  }
  function openInfo() { openModal("info", vInfo(lastNow), "infoX"); bind("infoX", closeInfo); }
  function closeInfo() {
    if (modal.hidden) return;
    modal.hidden = true; modal.innerHTML = ""; modalKind = null;
    if (modalFrom && document.contains(modalFrom)) modalFrom.focus(); modalFrom = null;
  }
  modal.onclick = function (e) { if (e.target === modal) closeInfo(); };
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeInfo(); });
  // 20분 전에 끝내면 돈이 안 쌓인다. 실수로 누르지 않게 한 번 묻는다.
  function doStop() {
    if (S.busy) return; closeInfo(); S.busy = true; render();
    api("rest/stop", null, { rider_id: 1 }).then(function (r) { S.busy = false; S.done = r; render(); }).catch(showErr);
  }
  function askStop(left) {
    openModal("stop", '<div class="msheet" role="alertdialog" aria-modal="true" aria-labelledby="askT"><i class="grab"></i>' +
      '<h2 class="ask-t" id="askT">지금 끝내면 돈이 안 쌓여요</h2>' +
      '<p class="ask-s"><b>' + left + '분</b>만 더 쉬면 적립돼요. ' + rules().rest + '분을 넘겨야 쌓이기 시작해요.</p>' +
      '<button class="bigbtn go" id="askKeep">계속 쉬기</button><button class="textbtn dim" id="askStop">그래도 끝내기</button></div>', "askKeep");
    bind("askKeep", closeInfo); bind("askStop", doStop);
  }
  // 서버 응답이 느려도 화면이 멈추지 않게 한다: 그리는 중에 또 부르면 버리지 않고, 끝난 뒤 최신 상태로 한 번 더 그린다.
  // (예전에는 새 요청이 올 때마다 앞 결과를 버려서, 응답이 시계 재생 간격보다 느리면 화면이 영영 안 바뀌었다.)
  var drawing = false, again = false;
  function clocks() {
    if (S.cfg && S.cfg.demo) { document.getElementById("clockT").textContent = hhmm(S.min); document.getElementById("clockR").value = S.min; }
    document.getElementById("barTime").textContent = S.cfg && S.cfg.demo ? hhmm(S.min) : new Date().toTimeString().slice(0, 5);
  }
  function render() {
    clocks();
    if (drawing) { again = true; return; }
    drawing = true;
    var done = function () { drawing = false; if (again) { again = false; render(); } };
    renderNow().then(done, done);
  }
  function renderNow() {
    var my = ++seq, v = S.view, p = pos();
    share();
    var job, immersive = false;
    if (v === "splash") job = Promise.resolve(vSplash());
    else if (v === "register") job = Promise.resolve(vRegister());
    else if (v === "settle") job = api("settlement", { rider_id: 1 }).then(vSettle);
    else if (v === "home") job = Promise.all([api("now", p), api("rest/current", { rider_id: 1 }), api("history", { rider_id: 1 }), api("shelters", p)]).then(function (x) {
      lastNow = x[0];
      if (S.done) { immersive = true; return vDone(S.done, x[0], x[2]); }
      lastCur = x[1];
      if (x[1].resting) { immersive = true; return vResting(x[0], x[1], x[2], x[3]); }
      return vHome(x[0], x[1], x[2], x[3]);
    });
    else if (v === "shelter") job = api("shelters", Object.assign({}, p, S.filter === "rider" ? { kind: "rider" } : {})).then(vShelter);
    else if (v === "me") job = Promise.all([api("rider", { rider_id: 1 }), api("history", { rider_id: 1 })]).then(function (x) { return vMe(x[0], x[1]); });
    else job = api("history", { rider_id: 1 }).then(vHistory);
    return job.then(function (html) {
      if (my !== seq) return;
      phone.classList.toggle("dark", immersive);
      // 화면 온도: 폭염이면 따뜻한 색, 쉬기 시작하면 하늘색으로 식는다 (style.css의 data-mood)
      var mood = immersive ? "cool" : ONBOARD[v] ? "" : lastNow && lastNow.hot ? "hot" : "";
      if (phone.dataset.mood !== mood) { phone.dataset.mood = mood; themeMeta && themeMeta.setAttribute("content", mood === "hot" ? "#ffe6cc" : mood === "cool" ? "#c4e0fb" : "#e2effc"); }
      dock.hidden = !!ONBOARD[v] || immersive;
      dock.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-selected", b.dataset.v === v ? "true" : "false"); });
      // 화면이 바뀔 때만 들어오는 움직임을 준다 (시연 시계가 돌 때마다 깜빡이지 않게)
      var key = v + (immersive ? (S.done ? ":done" : ":rest") : ""), keep = key === lastKey ? screen.scrollTop : 0;
      screen.classList.toggle("enter", key !== lastKey); lastKey = key;
      screen.innerHTML = html; screen.scrollTop = keep; bindScreen(); syncStage();
      if ((immersive || ONBOARD[v]) && modalKind === "info") closeInfo();
      if (modalKind === "stop" && !(lastCur && lastCur.resting && v === "home")) closeInfo();
    }).catch(function (e) {
      if (my !== seq) return;
      phone.classList.remove("dark"); dock.hidden = !!ONBOARD[v];
      screen.innerHTML = '<div class="state"><b>화면을 불러오지 못했어요</b><p>' + esc(e.message) + '</p><button class="pillbtn dark" id="retry">다시 불러오기</button></div>';
      document.getElementById("retry").onclick = render;
    });
  }
  function bind(id, fn) { var e = document.getElementById(id); if (e) e.onclick = fn; }
  function bindScreen() {
    var bl = document.getElementById("bigLogo"); if (bl) drawLogo(bl, false);
    var ml = document.getElementById("miniLogo"); if (ml) drawLogo(ml, false);
    var ag = document.getElementById("agree"), go = document.getElementById("goBtn");
    if (ag && go) ag.onchange = function () { go.disabled = !ag.checked; };
    bind("goBtn", function () {
      api("consent", null, { rider_id: 1 }).then(function (r) { S.view = r.pays ? "home" : "register"; render(); }).catch(showErr);
    });
    bind("regBtn", function () { if (S.busy) return; if (S.cfg.demo) registerSettle(DEMO_SETTLE_FILE); else fileIn.click(); });
    bind("regSkip", function () { S.view = S.from || "home"; S.from = null; render(); });
    bind("settleOk", function () { S.view = S.from === "me" ? "me" : "home"; S.from = null; render(); });
    bind("infoBtn", openInfo);
    bind("startBtn", function () {
      if (S.busy) return; S.busy = true; S.banner = null; render();
      api("rest/start", null, { rider_id: 1, lat: S.lat, lon: S.lon, place: "auto" }).then(function () { S.busy = false; render(); }).catch(showErr);
    });
    bind("stopBtn", function () {
      if (S.busy) return;
      var c = lastCur, R = rules(), paidToday = c && c.eligible && c.rested_min < R.rest;
      if (paidToday) askStop(R.rest - c.rested_min); else doStop();
    });
    bind("bannerX", function () { S.banner = null; render(); });
    bind("onbBack", function () { S.view = S.from || "home"; S.from = null; render(); });
    bind("doneOk", function () { S.done = null; render(); });
    bind("toHistory", function () { S.done = null; S.view = "history"; render(); });
    bind("f-near", function () { S.filter = "near"; render(); });
    bind("f-rider", function () { S.filter = "rider"; render(); });
    screen.querySelectorAll("[data-go]").forEach(function (b) { b.onclick = function () { if (ONBOARD[b.dataset.go]) S.from = S.view; S.view = b.dataset.go; render(); }; });
  }
  function showErr(e) { S.busy = false; S.banner = "<b>처리하지 못했어요.</b> " + esc(e.message); if (ONBOARD[S.view]) S.view = "home"; render(); }

  // ---------- 정산 내역 등록 (가입할 때 한 번, A단계 → B단계) ----------
  // MVP는 파일 이름만 서버에 남긴다. 사진 판독은 하지 않는다. 시연 모드는 가상 정산 내역을 바로 등록한다.
  var fileIn = document.getElementById("settleFile");
  function registerSettle(name) {
    S.busy = true; render();
    api("settlement", null, { rider_id: 1, filename: name }).then(function () { S.busy = false; S.banner = null; S.view = "settle"; render(); }).catch(showErr);
  }
  fileIn.onchange = function () {
    var f = fileIn.files && fileIn.files[0]; fileIn.value = "";
    if (f) registerSettle(f.name);
  };

  // ---------- 시연: 연동 단계 바꾸기 ----------
  var stageCtl = document.getElementById("stageCtl");
  function syncStage() {
    if (!S.cfg || !S.cfg.demo) return;
    api("rider", { rider_id: 1 }).then(function (r) {
      stageCtl.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.stage === r.stage ? "true" : "false"); });
    }).catch(function () {});
  }
  stageCtl.querySelectorAll("button").forEach(function (b) {
    b.onclick = function () { api("demo/stage", null, { rider_id: 1, stage: b.dataset.stage }).then(function () { S.banner = null; render(); }).catch(showErr); };
  });

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
    if (ONBOARD[S.view]) S.view = "home";
    playBtn.textContent = "멈춤";
    timer = setInterval(function () { if (drawing) return; if (S.min >= 1200) return stop(); setMin(S.min + 10); }, 700);   // 앞 화면을 다 그린 뒤에 다음 10분으로 넘어간다
  };
  document.getElementById("clockR").oninput = function (e) { setMin(+e.target.value); };
  document.getElementById("toSplash").onclick = function () { stop(); closeInfo(); S.done = null; S.from = null; S.view = "splash"; render(); };
  document.getElementById("jump14").onclick = function () { stop(); setMin(840); };
  document.getElementById("reset").onclick = function () { stop(); api("demo/reset", null, {}).then(function () { S.done = null; S.banner = null; setMin(840); }).catch(showErr); };
  dock.querySelectorAll("button").forEach(function (b) { b.onclick = function () { S.banner = null; S.from = null; S.view = b.dataset.v; render(); }; });
  // 시연 패널 숨기기: 화면을 녹화하거나 캡처할 때 앱만 보이게. 키보드 D로도 여닫는다.
  var demoEl = document.getElementById("demo"), demoShow = document.getElementById("demoShow");
  function demoVis(on) { if (!S.cfg || !S.cfg.demo) return; demoEl.hidden = !on; demoShow.hidden = on; }
  document.getElementById("demoHide").onclick = function () { demoVis(false); };
  demoShow.onclick = function () { demoVis(true); };
  document.addEventListener("keydown", function (e) { if ((e.key === "d" || e.key === "D") && !e.ctrlKey && !e.metaKey && !/INPUT|TEXTAREA/.test(e.target.tagName)) demoVis(demoEl.hidden); });

  // ---------- 시작 ----------
  fetch("/api/config").then(function (r) { return r.json(); }).then(function (cfg) {
    S.cfg = cfg; S.lat = cfg.demo_lat; S.lon = cfg.demo_lon;
    if (cfg.demo) {
      var p = cfg.demo_start.split(":"); S.min = +p[0] * 60 + +p[1];
      document.getElementById("demo").hidden = false;
      document.getElementById("demoDate").textContent = cfg.demo_date;
      if (cfg.real_shelters) {
        var dn = document.getElementById("demoNote");
        if (dn) dn.textContent = "지난 기록, 라이더 민수의 운행 기록·평소 수입, 지자체 화면의 라이더 1,000명은 시연용 가상 데이터입니다. 쉼터 목록은 실제 공공데이터(행정안전부 무더위쉼터 · 서울노동포털 이동노동자 쉼터)입니다. 체감온도는 행정동 모델 값입니다.";
      }
      start();
    } else if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(function (g) { S.lat = g.coords.latitude; S.lon = g.coords.longitude; render(); },
        function () { S.banner = "<b>위치를 못 받았어요.</b> 관악구청 기준으로 보여드려요. 브라우저에서 위치 권한을 켜 주세요."; render(); }, { timeout: 8000 });
      start();
    } else start();
  }).catch(function () {
    screen.innerHTML = '<div class="state"><b>서버에 연결되지 않아요</b><p>서버가 꺼져 있거나 켜지는 중이에요. 잠시 뒤 다시 시도해 주세요.</p><button class="pillbtn dark" id="retry">다시 시도</button></div>';
    document.getElementById("retry").onclick = function () { location.reload(); };
  });
  // 이미 위치 동의를 한 라이더는 시작 화면을 건너뛰고 바로 홈으로 간다
  function start() {
    api("rider", { rider_id: 1 }).then(function (r) { if (r.consent) S.view = "home"; }).catch(function () {}).then(render);
  }

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(function () {});
})();
