// TireStorage Manager UI helpers
// - Position size zoom (A-/A+) with persistence (localStorage)

(function () {
  const KEY = "tsm.posZoom";               // 'normal' | '125' | '150'
  const SCALE = { normal: 1.00, "125": 1.15, "150": 1.30 };
  const root = document.documentElement;

  function setScale(mode) {
    const val = SCALE[mode] ?? 1.00;
    root.style.setProperty('--pos-scale', String(val));
    try { localStorage.setItem(KEY, mode); } catch (_) {}
  }
  function getMode() {
    try { return localStorage.getItem(KEY) || 'normal'; } catch (_) { return 'normal'; }
  }

  function initZoomButtons() {
    const minus = document.getElementById('posZoomMinus');
    const plus  = document.getElementById('posZoomPlus');
    if (minus) {
      minus.addEventListener('click', function () {
        const mode = getMode();
        setScale(mode === '150' ? '125' : 'normal');
      });
    }
    if (plus) {
      plus.addEventListener('click', function () {
        const mode = getMode();
        setScale(mode === 'normal' ? '125' : '150');
      });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    setScale(getMode());
    initZoomButtons();
  });
})();
