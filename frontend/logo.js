/* 쉼표 로고: 14×17 픽셀 쉼표. 머리가 가장 뜨겁고(38도+) 꼬리로 갈수록 식는다. */
(function () {
  var C = 14, R = 17, cx = 7.3, cy = 5.6, rad = 4.1, P0 = [9.2, 8.0], P1 = [9.6, 13.0], P2 = [4.4, 16.0], cells = [];
  function tail(x, y) {
    var best = 1e9, bt = 0;
    for (var k = 0; k <= 60; k++) {
      var t = k / 60, a = (1 - t) * (1 - t), b = 2 * (1 - t) * t, c = t * t;
      var px = a * P0[0] + b * P1[0] + c * P2[0], py = a * P0[1] + b * P1[1] + c * P2[1];
      var d = Math.hypot(x - px, y - py);
      if (d < best) { best = d; bt = t; }
    }
    return [best, bt];
  }
  for (var r = 0; r < R; r++) for (var c = 0; c < C; c++) {
    var x = c + .5, y = r + .5, dd = Math.hypot(x - cx, y - cy), q = tail(x, y), w = 2.4 * (1 - q[1]) + 0.9 * q[1], v = 0;
    if (dd <= rad) v = 39.4 - (dd / rad) * 5.2;
    else if (q[0] <= w) v = Math.max(33.3, 36.6 - q[1] * 3.2 - (q[0] / w) * 0.6);
    cells.push({ c: c, r: r, v: v ? v + Math.sin(c * 2.1 + r * 1.3) * 0.3 : 0, e: Math.min(dd - rad, q[0] - w) });
  }
  function css(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  window.drawLogo = function (cv, halo) {
    var s = Math.round(cv.width / C), g = Math.max(1, Math.round(s * 0.12)), x = cv.getContext("2d");
    x.clearRect(0, 0, cv.width, cv.height);
    cells.forEach(function (k) {
      var col = null;
      if (k.v) col = k.v >= 38 ? css("--ember") : k.v >= 35 ? css("--amber") : css("--sun");
      else if (halo) col = k.e < 0.9 ? css("--ring") : k.e < 1.9 ? css("--soft") : null;
      if (!col) return;
      x.fillStyle = col; x.fillRect(k.c * s + g / 2, k.r * s + g / 2, s - g, s - g);
    });
  };
})();
