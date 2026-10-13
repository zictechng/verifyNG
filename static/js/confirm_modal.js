
/**
 * confirm_modal.js
 * ----------------
 * Global reusable confirmation modal for VerifyNG admin.
 *
 * Usage from any page/template:
 *
 *   window.openConfirmModal({
 *     title:         'Suspend Account',
 *     body:          'Are you sure you want to suspend <strong>Emeka</strong>?',
 *     confirmLabel:  'Yes, Suspend',
 *     confirmClass:  'btn-warning',           // any Bootstrap btn- class
 *     formAction:    '/admin/users/abc123/toggle-status/',
 *     hiddenFields:  { action: 'suspend' },   // optional extra POST fields
 *
 *     // Optional: extract extra fields from modal DOM just before submit
 *     // (e.g. a <select> or <input> rendered inside the body HTML)
 *     extraFieldsCallback: function () {
 *       return { role: document.getElementById('modalRoleSelect').value };
 *     },
 *
 *     // Optional: return false to abort submit (e.g. username confirmation)
 *     preSubmitCheck: function () {
 *       var val = document.getElementById('deleteConfirmInput').value;
 *       if (val !== 'expected-username') {
 *         alert('Username does not match.');
 *         return false;
 *       }
 *       return true;
 *     },
 *   });
 *
 * The modal is included via:
 *   {% include "includes/confirm_modal.html" %}
 */

(function () {
  'use strict';

  var _extraCallback  = null;
  var _preSubmitCheck = null;

  /* ── Open ─────────────────────────────────────────────────── */
  window.openConfirmModal = function (opts) {
    _extraCallback  = opts.extraFieldsCallback || null;
    _preSubmitCheck = opts.preSubmitCheck      || null;

    /* Title + body */
    document.getElementById('confirmModalLabel').innerHTML = opts.title || 'Confirm Action';
    document.getElementById('confirmModalBody').innerHTML  = opts.body  || 'Are you sure?';

    /* Confirm button */
    var btn   = document.getElementById('confirmModalBtn');
    var label = btn.querySelector('.confirm-btn-label');
    label.textContent = opts.confirmLabel || 'Confirm';
    btn.className     = 'btn btn-sm px-4 d-flex align-items-center gap-2 '
                        + (opts.confirmClass || 'btn-primary');
    btn.disabled = false;

    /* Reset spinner */
    document.getElementById('confirmModalSpinner').classList.add('d-none');

    /* Form action */
    document.getElementById('confirmActionForm').action = opts.formAction || '';

    /* Inject static hidden fields */
    var hf = document.getElementById('confirmActionHiddenFields');
    hf.innerHTML = '';
    var fields = opts.hiddenFields || {};
    Object.keys(fields).forEach(function (k) {
      _addHidden(hf, k, fields[k]);
    });

    /* Show modal */
    var modalEl = document.getElementById('confirmActionModal');
    var modal   = bootstrap.Modal.getOrCreate(modalEl);
    modal.show();
  };

  /* ── Submit handler ───────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('confirmModalBtn');
    if (!btn) return;

    btn.addEventListener('click', function () {

      /* 1. Optional pre-submit check (e.g. type username to confirm) */
      if (_preSubmitCheck && !_preSubmitCheck()) return;

      /* 2. Optional dynamic field extraction (e.g. role <select>) */
      if (_extraCallback) {
        var extra = _extraCallback();
        var hf    = document.getElementById('confirmActionHiddenFields');
        Object.keys(extra).forEach(function (k) {
          _addHidden(hf, k, extra[k]);
        });
      }

      /* 3. Show loading state — prevent double-submit */
      btn.disabled = true;
      btn.querySelector('.confirm-btn-label').textContent = 'Processing…';
      document.getElementById('confirmModalSpinner').classList.remove('d-none');

      /* 4. Submit */
      document.getElementById('confirmActionForm').submit();
    });
  });

  /* ── Helper ───────────────────────────────────────────────── */
  function _addHidden(container, name, value) {
    var inp   = document.createElement('input');
    inp.type  = 'hidden';
    inp.name  = name;
    inp.value = value;
    container.appendChild(inp);
  }

})();


/* Show a subtle top progress bar while the page is loading after submit */
document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('confirmActionForm');
  if (!form) return;
  form.addEventListener('submit', function () {
    /* Optional: inject a top loading bar if you have one in the base layout */
    var bar = document.getElementById('pageLoadingBar');
    if (bar) bar.classList.remove('d-none');
  });
});


