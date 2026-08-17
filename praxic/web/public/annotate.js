/* Praxic dev annotation probe v4
 * 激活条件（任一满足）：
 *   1. URL 带 ?annotate=1（强制，供 Hana 插件 iframe 使用）
 *   2. localStorage 标志 praxic_dev_annotate === '1'（设置面板 · 开发者模式开关）
 * 行为：右键（contextmenu）点击任意元素 → 页面内弹出输入框 → 输入改动要求/问题 →
 *       合成注释 postMessage 给父窗口（插件 bridge），同时显示在页面标注台。
 * 提供 window.__praxicAnnotateSetEnabled(bool) 供设置面板即时切换。
 */
(function () {
  var FORCED = new URLSearchParams(location.search).get('annotate') === '1';
  var PANEL_CLS = 'praxic-annotate-panel';
  var active = false;
  var items = [];
  var current = null;
  var panel = null;
  var bodySel = null;
  var contextHandler = null;

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

  function buildNoteInfo(t, note) {
    var r = t.getBoundingClientRect();
    var href = t.getAttribute ? (t.getAttribute('href') || '') : '';
    return {
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
      note: typeof note === 'string' ? note.trim() : '',
      ts: Date.now()
    };
  }

  // ---------- 输入框（页面内，贴近目标） ----------

  var modal = null;

  function showNoteModal(targetEl) {
    if (modal) return;
    var info = buildNoteInfo(targetEl, '');
    modal = document.createElement('div');
    modal.className = 'praxic-annotate-modal';
    modal.style.cssText = 'position:fixed;right:20px;bottom:20px;width:340px;max-width:calc(100vw - 40px);z-index:2147483002;background:#FCFAF5;border:2px solid #1C1916;box-shadow:6px 6px 0 rgba(28,25,22,.18);font-family:Arial,"Microsoft YaHei",sans-serif;color:#1C1916;';
    modal.innerHTML =
      '<div style="background:#1C1916;color:#FCFAF5;padding:8px 12px;font-size:11px;font-weight:900;letter-spacing:.1em">PRAXIC 标注注释</div>' +
      '<div style="padding:10px 12px;font-size:11px;line-height:1.5">' +
      '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">' +
      '<span style="background:#9E7B3A;color:#1C1916;font-weight:800;font-size:11px;padding:1px 7px;border:1px solid #1C1916">' + esc(info.tag) + '</span>' +
      '<span style="color:#6B6560;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">' + esc(info.selector) + '</span>' +
      '</div>' +
      '<div style="font-size:10px;color:#6B6560;margin-bottom:4px">改动要求 / 问题：</div>' +
      '<textarea placeholder="例：把这个按钮改成主色，宽度加大" style="width:100%;box-sizing:border-box;min-height:64px;resize:vertical;border:1px solid #C5BFB5;background:#F7F4ED;padding:6px 8px;font-size:12px;color:#1C1916;outline:none"></textarea>' +
      '<div style="display:flex;gap:6px;margin-top:8px">' +
      '<button data-act="ok" style="flex:1;background:#8C0000;color:#FCFAF5;border:1px solid #1C1916;font-size:11px;font-weight:800;padding:6px 0;cursor:pointer">确认标注</button>' +
      '<button data-act="cancel" style="background:transparent;color:#8C0000;border:1px solid #C5BFB5;font-size:11px;font-weight:800;padding:6px 12px;cursor:pointer">取消</button>' +
      '</div>' +
      '</div>';
    document.body.appendChild(modal);
    var textarea = modal.querySelector('textarea');
    textarea.focus();

    modal.addEventListener('click', function (e) {
      var act = e.target.getAttribute && e.target.getAttribute('data-act');
      if (!act) return;
      if (act === 'cancel') {
        closeModal();
      } else if (act === 'ok') {
        var note = textarea.value;
        var record = buildNoteInfo(targetEl, note);
        closeModal();
        emitNote(record);
      }
    });
  }

  function closeModal() {
    if (modal && modal.parentNode) modal.parentNode.removeChild(modal);
    modal = null;
  }

  function emitNote(record) {
    items.unshift(record);
    if (items.length > 12) items.pop();
    current = record;
    try { window.parent.postMessage(record, '*'); } catch (err) {}
    showToast('已标注：' + (record.note || '(无备注)'));
  }

  // ---------- 标注台（页面内历史） ----------

  function render() {
    if (!bodySel) return;
    if (!current) {
      bodySel.innerHTML = '<div style="padding:10px 12px;color:#6B6560;font-size:12px">右键点击页面上任意元素进行标注注释</div>';
      return;
    }
    var metaBits = [];
    if (current.id) metaBits.push('id: <b>' + esc(current.id) + '</b>');
    if (current.cls) metaBits.push('class: <b>' + esc(current.cls.slice(0, 80)) + '</b>');
    if (current.href) metaBits.push('href: <b>' + esc(current.href) + '</b>');
    bodySel.innerHTML =
      '<div style="padding:10px 12px;font-size:12px;line-height:1.6">' +
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">' +
      '<span style="background:#9E7B3A;color:#1C1916;font-weight:800;font-size:11px;padding:2px 8px;border:1px solid #1C1916">' + esc(current.tag) + '</span>' +
      '<span style="color:#8C0000;font-weight:800;font-size:10px">第 ' + items.length + ' 条注释</span>' +
      '</div>' +
      '<div style="font-size:10px;color:#6B6560;font-weight:800;letter-spacing:.08em;margin-bottom:3px">SELECTOR</div>' +
      '<div style="font-family:Consolas,monospace;font-size:11px;color:#1C1916;background:#F7F4ED;border:1px solid #C5BFB5;padding:6px 8px;word-break:break-all;margin-bottom:8px">' + esc(current.selector) + '</div>' +
      (current.note ? '<div style="font-size:11px;color:#4A433C;border-left:3px solid #9E7B3A;padding:2px 0 2px 8px;margin-bottom:8px">备注：' + esc(current.note) + '</div>' : '') +
      '<div style="font-size:10px;color:#6B6560;margin-bottom:8px">' + metaBits.join(' · ') + '</div>' +
      '<div style="display:flex;gap:6px">' +
      '<button data-act="copy" style="flex:1;background:#8C0000;color:#FCFAF5;border:1px solid #1C1916;font-size:11px;font-weight:800;padding:5px 0;cursor:pointer">复制 selector</button>' +
      '<button data-act="clear" style="background:transparent;color:#8C0000;border:1px solid #C5BFB5;font-size:11px;font-weight:800;padding:5px 10px;cursor:pointer">清空</button>' +
      '</div>' +
      '<div style="margin-top:8px;padding-top:6px;border-top:1px solid #C5BFB5;font-size:10px;color:#6B6560">' +
      (items.slice(0, 4).map(function (it, i) {
        return '<div style="display:flex;gap:6px;padding:2px 0;align-items:baseline"><span style="color:#9E7B3A;font-family:Consolas,monospace;font-weight:800">' + (i + 1) + '</span><span style="font-family:Consolas,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(it.tag + ' ' + (it.note || it.selector).slice(0, 50)) + '</span></div>';
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
      '<span style="font-size:11px;font-weight:900;letter-spacing:.1em">PRAXIC 标注注释</span>' +
      '<span data-act="toggle" style="font-size:13px;line-height:1">–</span>' +
      '</div>' +
      '<div data-part="body" style="max-height:70vh;overflow-y:auto"></div>';
    document.body.appendChild(panel);
    bodySel = panel.querySelector('[data-part="body"]');
    panel.addEventListener('click', function (e) {
      var act = e.target.getAttribute && e.target.getAttribute('data-act');
      if (!act) return;
      if (act === 'toggle') {
        var open = panel.classList.toggle('praxic-annotate-mini');
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

  function onContextMenu(e) {
    var t = e.target;
    if (!t || t.nodeType !== 1) return;
    if (t.closest && t.closest('.' + PANEL_CLS)) return;
    if (modal && t.closest && t.closest('.praxic-annotate-modal')) return;
    e.preventDefault();
    ensurePanel();
    showNoteModal(t);
  }

  function activate() {
    if (active) return;
    active = true;
    contextHandler = onContextMenu;
    document.addEventListener('contextmenu', onContextMenu, true);
  }

  function deactivate() {
    if (!active) return;
    active = false;
    if (contextHandler) document.removeEventListener('contextmenu', contextHandler, true);
    contextHandler = null;
    closeModal();
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

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modal) closeModal();
    if (!e.ctrlKey || !e.shiftKey || !e.key || e.key.toLowerCase() !== 'a') return;
    if (!isDevMode()) return;
    e.preventDefault();
    var next = !flagEnabled();
    window.__praxicAnnotateSetEnabled(next);
    showToast('标注注释：' + (next ? '开' : '关') + '  (Ctrl+Shift+A)');
  });

  sync();
  window.addEventListener('storage', function (e) {
    if (e.key === 'praxic_dev_annotate') sync();
  });
})();
