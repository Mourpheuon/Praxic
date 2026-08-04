/* Praxic dev annotation probe v3
 * 激活条件（任一满足）：
 *   1. URL 带 ?annotate=1（强制，供调试/Hana 卡片）
 *   2. localStorage 标志 praxic_dev_annotate === '1'（设置面板 · 开发者模式开关）
 * 提供 window.__praxicAnnotateSetEnabled(bool) 供 React 设置面板即时切换。
 */
(function () {
  var FORCED = new URLSearchParams(location.search).get('annotate') === '1';
  var PANEL_CLS = 'praxic-annotate-panel';
  var MINI_CLS = 'praxic-annotate-mini';

  var active = false;
  var items = [];
  var current = null;
  var panel = null;
  var bodySel = null;
  var clickHandler = null;

  function flagEnabled() {
    try {
      var v = localStorage.getItem('praxic_dev_annotate');
      return v === '1' || v === 'true';
    } catch (e) { return false; }
  }

  function selectorPath(el) {
    var parts = [];
    while (el && el.nodeType === 1 && el !== document.body && el !== document.documentElement) {
      var s = el.tagName.toLowerCase();
      if (el.id) {
        s += '#' + el.id;
      } else {
        var cls = (typeof el.className === 'string' ? el.className : '')
          .split(/\s+/).filter(Boolean).slice(0, 2);
        if (cls.length) s += '.' + cls.join('.');
      }
      var parent = el.parentElement;
      if (parent) {
        var same = Array.prototype.filter.call(parent.children, function (c) {
          return c.tagName === el.tagName;
        });
        if (same.length > 1) s += ':nth-of-type(' + (same.indexOf(el) + 1) + ')';
      }
      parts.unshift(s);
      el = parent;
    }
    return parts.join(' > ');
  }

  function shortText(el) {
    var t = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
    return t.length > 60 ? t.slice(0, 60) + '…' : t;
  }

  function copyText(t) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(t);
    }
    return new Promise(function (resolve) {
      var ta = document.createElement('textarea');
      ta.value = t;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch (e) {}
      document.body.removeChild(ta);
      resolve();
    });
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function render() {
    if (!bodySel) return;
    if (!current) {
      bodySel.innerHTML = '<div style="padding:10px 12px;color:#6B6560;font-size:12px">点击页面上任意元素进行标注</div>';
      return;
    }
    var metaBits = [];
    if (current.id) metaBits.push('id: <b>' + esc(current.id) + '</b>');
    if (current.cls) metaBits.push('class: <b>' + esc(current.cls.slice(0, 80)) + '</b>');
    if (current.href) metaBits.push('href: <b>' + esc(current.href) + '</b>');
    if (current.rect) metaBits.push('尺寸: <b>' + current.rect.w + '×' + current.rect.h + '</b> @ <b>' + current.rect.x + ',' + current.rect.y + '</b>');
    bodySel.innerHTML =
      '<div style="padding:10px 12px;font-size:12px;line-height:1.6">' +
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">' +
      '<span style="background:#9E7B3A;color:#1C1916;font-weight:800;font-size:11px;padding:2px 8px;border:1px solid #1C1916">' + esc(current.tag) + '</span>' +
      '<span style="color:#8C0000;font-weight:800;font-size:10px">第 ' + items.length + ' 次标注</span>' +
      '</div>' +
      '<div style="font-size:10px;color:#6B6560;font-weight:800;letter-spacing:.08em;margin-bottom:3px">SELECTOR</div>' +
      '<div style="font-family:Consolas,monospace;font-size:11px;color:#1C1916;background:#F7F4ED;border:1px solid #C5BFB5;padding:6px 8px;word-break:break-all;margin-bottom:8px">' + esc(current.selector) + '</div>' +
      '<div style="font-size:10px;color:#6B6560;margin-bottom:8px">' + metaBits.join(' · ') + '</div>' +
      '<div style="font-size:11px;color:#4A433C;border-left:3px solid #8C0000;padding:2px 0 2px 8px;margin-bottom:8px">' + esc(current.text ? '「' + current.text + '」' : '') + '</div>' +
      '<div style="display:flex;gap:6px">' +
      '<button data-act="copy" style="flex:1;background:#8C0000;color:#FCFAF5;border:1px solid #1C1916;font-size:11px;font-weight:800;padding:5px 0;cursor:pointer">复制 selector</button>' +
      '<button data-act="clear" style="background:transparent;color:#8C0000;border:1px solid #C5BFB5;font-size:11px;font-weight:800;padding:5px 10px;cursor:pointer">清空</button>' +
      '</div>' +
      '<div style="margin-top:8px;padding-top:6px;border-top:1px solid #C5BFB5;font-size:10px;color:#6B6560">' +
      (items.slice(0, 4).map(function (it, i) {
        return '<div style="display:flex;gap:6px;padding:2px 0;align-items:baseline"><span style="color:#9E7B3A;font-family:Consolas,monospace;font-weight:800">' + (i + 1) + '</span><span style="font-family:Consolas,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(it.tag + ' ' + it.selector.slice(0, 60)) + '</span></div>';
      }).join('')) +
      '</div>' +
      '</div>';
  }

  function ensurePanel() {
    if (panel) return;
    panel = document.createElement('div');
    panel.className = PANEL_CLS;
    panel.style.cssText = 'position:fixed;right:16px;bottom:16px;width:300px;max-width:calc(100vw - 32px);z-index:2147483000;background:#FCFAF5;border:2px solid #1C1916;box-shadow:6px 6px 0 rgba(28,25,22,.18);font-family:Arial,"Microsoft YaHei",sans-serif;color:#1C1916;';
    panel.innerHTML =
      '<div data-act="toggle" style="display:flex;align-items:center;justify-content:space-between;background:#1C1916;color:#FCFAF5;padding:8px 12px;cursor:pointer;user-select:none">' +
      '<span style="font-size:11px;font-weight:900;letter-spacing:.1em">PRAXIC 标注台</span>' +
      '<span data-act="toggle" style="font-size:13px;line-height:1">–</span>' +
      '</div>' +
      '<div data-part="body" style="max-height:70vh;overflow-y:auto"></div>';
    document.body.appendChild(panel);
    bodySel = panel.querySelector('[data-part="body"]');
    panel.addEventListener('click', function (e) {
      var act = e.target.getAttribute && e.target.getAttribute('data-act');
      if (!act) return;
      if (act === 'toggle') {
        var open = panel.classList.toggle(MINI_CLS);
        panel.querySelector('[data-part="body"]').style.display = open ? 'none' : '';
        panel.querySelector('[data-act="toggle"]:last-child').textContent = open ? '+' : '–';
      } else if (act === 'copy' && current) {
        copyText(current.selector).then(function () {
          var b = panel.querySelector('[data-act="copy"]');
          b.textContent = '已复制';
          setTimeout(function () { b.textContent = '复制 selector'; }, 1200);
        });
      } else if (act === 'clear') {
        items = [];
        current = null;
        render();
      }
    });
    render();
  }

  function onDocClick(e) {
    var t = e.target;
    if (!t || t.nodeType !== 1) return;
    if (t.closest && t.closest('.' + PANEL_CLS)) return;
    ensurePanel();
    var r = t.getBoundingClientRect();
    var href = t.getAttribute ? (t.getAttribute('href') || '') : '';
    var info = {
      source: 'praxic-annotate',
      tag: t.tagName.toLowerCase(),
      id: t.id || '',
      cls: (typeof t.className === 'string' ? t.className : '').slice(0, 140),
      text: shortText(t),
      selector: selectorPath(t),
      rect: {
        x: Math.round(r.x), y: Math.round(r.y),
        w: Math.round(r.width), h: Math.round(r.height)
      },
      href: href,
      ts: Date.now()
    };
    current = info;
    items.unshift(info);
    if (items.length > 12) items.pop();
    render();
    try { window.parent.postMessage(info, '*'); } catch (err) {}
  }

  function activate() {
    if (active) return;
    active = true;
    clickHandler = onDocClick;
    document.addEventListener('click', onDocClick, true);
  }

  function deactivate() {
    if (!active) return;
    active = false;
    if (clickHandler) document.removeEventListener('click', clickHandler, true);
    clickHandler = null;
    if (panel && panel.parentNode) panel.parentNode.removeChild(panel);
    panel = null;
    bodySel = null;
    items = [];
    current = null;
  }

  function sync() {
    if (FORCED || flagEnabled()) activate();
    else deactivate();
  }

  window.__praxicAnnotateSetEnabled = function (enabled) {
    try { localStorage.setItem('praxic_dev_annotate', enabled ? '1' : '0'); } catch (e) {}
    sync();
  };

  var toast = null;
  var toastTimer = null;
  function showToast(msg) {
    if (!toast) {
      toast = document.createElement('div');
      toast.style.cssText = 'position:fixed;top:72px;right:16px;z-index:2147483001;background:#1C1916;color:#FCFAF5;border:2px solid #9E7B3A;border-left:4px solid #8C0000;padding:8px 14px;font-family:Arial,"Microsoft YaHei",sans-serif;font-size:12px;font-weight:800;box-shadow:4px 4px 0 rgba(28,25,22,.18);opacity:0;transition:opacity .15s ease';
      document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.style.opacity = '1';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.style.opacity = '0'; }, 1500);
  }

  function isDevMode() {
    try { return JSON.parse(localStorage.getItem('praxic_dev_mode')) === true; } catch (e) { return false; }
  }

  document.addEventListener('keydown', function (e) {
    if (!e.ctrlKey || !e.shiftKey || !e.key || e.key.toLowerCase() !== 'a') return;
    if (!isDevMode()) return;
    e.preventDefault();
    var next = !flagEnabled();
    window.__praxicAnnotateSetEnabled(next);
    showToast('元素标注 selector：' + (next ? '开' : '关') + '  (Ctrl+Shift+A)');
  });

  sync();
  window.addEventListener('storage', function (e) {
    if (e.key === 'praxic_dev_annotate') sync();
  });
})();
