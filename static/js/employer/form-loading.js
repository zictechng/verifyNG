
/**
 * form-loading.js — VerifyNG Employer Portal
 * Applies professional loading state to ALL submit buttons on form submission.
 * Also provides window.vng.fetchPost() for Fetch+Toast pattern buttons.
 *
 * Usage (automatic): any <button type="submit"> inside a <form> gets the spinner.
 * Usage (manual):    data-loading="true" on any button triggers spinner on click.
 */

(function () {
  'use strict';

  // ── Spinner SVG ─────────────────────────────────────────────────────────────
  const SPINNER = `
    <span class="vng-btn-spinner" role="status" aria-hidden="true"
          style="display:inline-block;width:14px;height:14px;border:2px solid currentColor;
                 border-right-color:transparent;border-radius:50%;
                 animation:vng-spin .65s linear infinite;vertical-align:-2px;margin-right:6px;">
    </span>`;

  // Inject keyframes once
  if (!document.getElementById('vng-spin-style')) {
    const s = document.createElement('style');
    s.id = 'vng-spin-style';
    s.textContent = '@keyframes vng-spin{to{transform:rotate(360deg)}}';
    document.head.appendChild(s);
  }

  // ── Apply loading state to a button ────────────────────────────────────────
  function setLoading(btn, loadingText) {
    if (!btn || btn.dataset.loading === 'active') return; // already spinning
    btn.dataset.loading   = 'active';
    btn.dataset.origText  = btn.innerHTML;
    btn.style.pointerEvents = 'none';
    btn.style.opacity     = '0.78';
    btn.style.cursor      = 'not-allowed';
    btn.innerHTML         = SPINNER + (loadingText || btn.dataset.loadingText || 'Please wait…');
    // Also activate top progress bar if available in base layout
    const bar = document.getElementById('pageLoadingBar');
    if (bar) bar.classList.remove('d-none');
  }
  function clearLoading(btn) {
    if (!btn || !btn.dataset.origText) return;
    btn.disabled          = false;
    btn.style.pointerEvents = '';
    btn.style.opacity     = '';
    btn.style.cursor      = '';
    btn.innerHTML         = btn.dataset.origText;
    delete btn.dataset.loading;
    const bar = document.getElementById('pageLoadingBar');
    if (bar) bar.classList.add('d-none');
  }
  // ── Auto-hook all forms ─────────────────────────────────────────────────────
  document.addEventListener('submit', function (e) {
    const form = e.target;
    if (!form || form.tagName !== 'FORM') return;
    // Skip forms that opt out
    if (form.dataset.noLoading) return;
    // Find the clicked submit button (stored by pointer/touch/mousedown)
    const btn = form._clickedBtn ||
                form.querySelector('button[type="submit"]:not([data-no-loading])') ||
                form.querySelector('button:not([type="button"]):not([data-no-loading])');
    if (!btn) return;
    // Slight delay so browser validation fires first
    setTimeout(function () {
      if (form.checkValidity && !form.checkValidity()) return;
      setLoading(btn, btn.dataset.loadingText);
    }, 0);
    // Safety reset after 15 s (e.g. server error with no page reload)
    setTimeout(function () { clearLoading(btn); }, 15000);
  });
  // Track which submit button was clicked (supports touchscreens, mouse, stylus)
  ['pointerdown', 'touchstart', 'mousedown'].forEach(function (evt) {
    document.addEventListener(evt, function (e) {
      const btn = e.target.closest('button[type="submit"], button:not([type]), [data-loading="true"]');
      if (btn) {
        const form = btn.closest('form');
        if (form) form._clickedBtn = btn;
      }
    }, { capture: true, passive: true });
  });

  // ── window.vng namespace (Fetch + Toast helper) ─────────────────────────────
  window.vng = window.vng || {};

  /**
   * window.vng.fetchPost(url, body, btn, opts)
   *   url   — string
   *   body  — FormData or plain object (auto-serialised)
   *   btn   — the button element (for loading state)
   *   opts  — { loadingText, onSuccess(data), onError(data) }
   */
  window.vng.fetchPost = async function (url, body, btn, opts) {
    opts = opts || {};
    if (btn) setLoading(btn, opts.loadingText || 'Processing…');

    let payload;
    if (body instanceof FormData) {
      payload = body;
    } else {
      const fd = new FormData();
      Object.entries(body || {}).forEach(([k, v]) => fd.append(k, v));
      payload = fd;
    }

    // Robust CSRF token reader — handles base64 padding and spaces
    const _getCsrf = () => {
      const name = 'csrftoken=';
      for (const part of document.cookie.split(';')) {
        const p = part.trim();
        if (p.startsWith(name)) return decodeURIComponent(p.slice(name.length));
      }
      return '';
    };
    const csrfToken = _getCsrf();
    if (csrfToken && !payload.get('csrfmiddlewaretoken')) {
      payload.set('csrfmiddlewaretoken', csrfToken);
    }

    try {
      const resp = await fetch(url, {
        method:      'POST',
        headers:     csrfToken ? { 'X-CSRFToken': csrfToken } : {},
        credentials: 'same-origin',
        body:        payload,
      });
      const data = await resp.json().catch(() => ({ ok: false, message: 'Server error.' }));

      if (btn) clearLoading(btn);

      if (data.ok || resp.ok) {
        window.vng.toast(data.message || 'Done.', 'success');
        if (opts.onSuccess) opts.onSuccess(data);
      } else {
        window.vng.toast(data.message || 'Something went wrong.', 'danger');
        if (opts.onError) opts.onError(data);
      }
    } catch (err) {
      if (btn) clearLoading(btn);
      window.vng.toast('Network error. Please try again.', 'danger');
      if (opts.onError) opts.onError({ ok: false, message: err.message });
    }
  };

  /**
   * window.vng.toast(message, type)
   *   type — 'success' | 'danger' | 'warning' | 'info'
   */
  window.vng.toast = function (message, type) {
    type = type || 'success';

    let container = document.getElementById('vng-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'vng-toast-container';
      container.style.cssText = [
        'position:fixed', 'bottom:24px', 'right:24px',
        'z-index:9999', 'display:flex', 'flex-direction:column',
        'gap:10px', 'align-items:flex-end', 'pointer-events:none',
      ].join(';');
      document.body.appendChild(container);
    }

    const colours = {
      success: { bg: '#D1FAE5', border: '#34D399', text: '#065F46', icon: '✓' },
      danger:  { bg: '#FEE2E2', border: '#F87171', text: '#991B1B', icon: '✕' },
      warning: { bg: '#FEF3C7', border: '#FCD34D', text: '#92400E', icon: '⚠' },
      info:    { bg: '#EFF6FF', border: '#93C5FD', text: '#1E40AF', icon: 'ℹ' },
    };
    const c = colours[type] || colours.info;

    const toast = document.createElement('div');
    toast.style.cssText = [
      `background:${c.bg}`, `border:1px solid ${c.border}`,
      `color:${c.text}`, 'border-radius:10px',
      'padding:12px 18px', 'font-size:14px', 'font-weight:500',
      'box-shadow:0 4px 16px rgba(0,0,0,.12)',
      'display:flex', 'align-items:center', 'gap:10px',
      'pointer-events:auto', 'max-width:360px',
      'opacity:0', 'transform:translateY(8px)',
      'transition:opacity .2s ease,transform .2s ease',
    ].join(';');

    toast.innerHTML = `
      <span style="font-size:16px;flex-shrink:0;">${c.icon}</span>
      <span style="flex:1;">${message}</span>
      <button onclick="this.closest('.vng-toast').remove()"
              style="background:none;border:none;cursor:pointer;color:inherit;font-size:18px;
                     line-height:1;padding:0;margin-left:4px;opacity:.6;">×</button>`;
    toast.classList.add('vng-toast');
    container.appendChild(toast);

    requestAnimationFrame(() => {
      toast.style.opacity   = '1';
      toast.style.transform = 'translateY(0)';
    });

    setTimeout(() => {
      toast.style.opacity   = '0';
      toast.style.transform = 'translateY(8px)';
      setTimeout(() => toast.remove(), 220);
    }, 4500);
  };

})();

