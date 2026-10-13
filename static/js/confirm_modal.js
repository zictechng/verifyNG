
/**
 * confirm_modal.js
 * ----------------
 * Reads data-* attributes from buttons to drive the confirmation modal.
 * No onclick attributes needed — works across any page that includes
 * templates/includes/confirm_modal.html and this script.
 *
 * Button data attributes:
 *   data-confirm-action          — plain action (no extras)
 *   data-confirm-action="role"   — action that reads #modalRoleSelect
 *   data-confirm-action="delete" — action that validates #deleteConfirmInput
 *   data-title                   — modal title
 *   data-body                    — modal body HTML
 *   data-confirm-label           — confirm button label
 *   data-confirm-class           — Bootstrap btn- class for confirm button
 *   data-form-action             — URL the hidden form POSTs to
 *   data-hidden-action           — optional: adds <input name="action"> to form
 *   data-delete-username         — required for delete: username to match
 */

(function () {
  'use strict';

  var _actionType      = null;
  var _deleteUsername  = null;

  /* ── Wire up all buttons ───────────────────────────────────── */
  /* This script loads at end-of-body so the DOM is already ready.
     DOMContentLoaded has already fired — call init() directly.    */
  function init() {

    /* Confirm button click → submit */
    var confirmBtn = document.getElementById('confirmModalBtn');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', handleConfirm);
    }

    /* All buttons with [data-confirm-action] */
    document.querySelectorAll('[data-confirm-action]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        openFromButton(btn);
      });
    });
  }

  /* ── Open modal from a button's data attributes ───────────── */
  function openFromButton(btn) {
    _actionType     = btn.dataset.confirmAction || null;  // '', 'role', 'delete'
    _deleteUsername = btn.dataset.deleteUsername || null;

    /* Populate modal */
    document.getElementById('confirmModalLabel').innerHTML =
      btn.dataset.title || 'Confirm Action';
    document.getElementById('confirmModalBody').innerHTML =
      btn.dataset.body  || 'Are you sure?';

    /* Confirm button */
    var confirmBtn = document.getElementById('confirmModalBtn');
    confirmBtn.querySelector('.confirm-btn-label').textContent =
      btn.dataset.confirmLabel || 'Confirm';
    confirmBtn.className =
      'btn btn-sm px-4 d-flex align-items-center gap-2 ' +
      (btn.dataset.confirmClass || 'btn-primary');
    confirmBtn.disabled = false;

    /* Reset spinner */
    document.getElementById('confirmModalSpinner').classList.add('d-none');

    /* Form action */
    document.getElementById('confirmActionForm').action =
      btn.dataset.formAction || '';

    /* Static hidden fields */
    var hf = document.getElementById('confirmActionHiddenFields');
    hf.innerHTML = '';
    if (btn.dataset.hiddenAction) {
      addHidden(hf, 'action', btn.dataset.hiddenAction);
    }

    /* Show */
    var modalEl = document.getElementById('confirmActionModal');
    var bsModal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
    bsModal.show();
  }

  /* ── Handle confirm button click ──────────────────────────── */
  function handleConfirm() {
    var hf = document.getElementById('confirmActionHiddenFields');

    /* Delete: validate username input */
    if (_actionType === 'delete') {
      var inp = document.getElementById('deleteConfirmInput');
      if (!inp || inp.value.trim() !== _deleteUsername) {
        showModalAlert('Username does not match. Deletion cancelled.');
        return;
      }
    }

    /* Role: extract selected role */
    if (_actionType === 'role') {
      var sel = document.getElementById('modalRoleSelect');
      if (sel) addHidden(hf, 'role', sel.value);
    }

    /* Loading state — prevent double submit */
    var confirmBtn = document.getElementById('confirmModalBtn');
    confirmBtn.disabled = true;
    confirmBtn.querySelector('.confirm-btn-label').textContent = 'Processing\u2026';
    document.getElementById('confirmModalSpinner').classList.remove('d-none');

    /* Submit */
    document.getElementById('confirmActionForm').submit();
  }

  /* ── Helpers ──────────────────────────────────────────────── */
  function addHidden(container, name, value) {
    var inp   = document.createElement('input');
    inp.type  = 'hidden';
    inp.name  = name;
    inp.value = value;
    container.appendChild(inp);
  }

  function showModalAlert(msg) {
    var body  = document.getElementById('confirmModalBody');
    var alert = document.createElement('div');
    alert.className = 'alert alert-danger alert-sm mt-2 mb-0 py-2 px-3';
    alert.textContent = msg;
    var prev = body.querySelector('.alert');
    if (prev) prev.remove();
    body.appendChild(alert);
  }

  /* Run immediately — DOM is fully parsed at end-of-body */
  init();

})();


/* Show a subtle top progress bar while the page is loading after submit */
(function () {
  var form = document.getElementById('confirmActionForm');
  if (!form) return;
  form.addEventListener('submit', function () {
    var bar = document.getElementById('pageLoadingBar');
    if (bar) bar.classList.remove('d-none');
  });
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


