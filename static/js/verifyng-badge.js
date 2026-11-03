(function() {
  'use strict';

  function initVerifyNGBadge() {
    var scripts = document.querySelectorAll('script[data-merchant]');
    if (!scripts.length) return;

    scripts.forEach(function(script) {
      if (script.getAttribute('data-vng-rendered')) return;
      script.setAttribute('data-vng-rendered', 'true');

      var slug = script.getAttribute('data-merchant');
      if (!slug) return;

      var baseUrl = script.src.split('/static/')[0];
      if (!baseUrl) {
        baseUrl = 'https://verifyng.com';
      }

      var badgeContainer = document.createElement('a');
      badgeContainer.href = baseUrl + '/trust-seal/v/' + encodeURIComponent(slug) + '/';
      badgeContainer.target = '_blank';
      badgeContainer.rel = 'noopener noreferrer';
      badgeContainer.title = 'Verify this merchant on VerifyNG';
      badgeContainer.style.display = 'inline-flex';
      badgeContainer.style.alignItems = 'center';
      badgeContainer.style.gap = '8px';
      badgeContainer.style.padding = '8px 14px';
      badgeContainer.style.background = '#0f172a';
      badgeContainer.style.color = '#ffffff';
      badgeContainer.style.borderRadius = '50px';
      badgeContainer.style.fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
      badgeContainer.style.fontSize = '12px';
      badgeContainer.style.fontWeight = '600';
      badgeContainer.style.textDecoration = 'none';
      badgeContainer.style.boxShadow = '0 4px 14px rgba(15, 23, 42, 0.15)';
      badgeContainer.style.border = '1px solid #334155';
      badgeContainer.style.transition = 'all 0.2s ease';

      badgeContainer.innerHTML = 
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="#22c55e" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0;">' +
          '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>' +
        '</svg>' +
        '<span>Verified Merchant</span>' +
        '<span style="background:rgba(255,255,255,0.15);padding:2px 7px;border-radius:12px;font-size:10px;letter-spacing:0.3px;color:#94a3b8;">VerifyNG</span>';

      badgeContainer.addEventListener('mouseenter', function() {
        badgeContainer.style.transform = 'translateY(-1px)';
        badgeContainer.style.boxShadow = '0 6px 20px rgba(15, 23, 42, 0.25)';
      });
      badgeContainer.addEventListener('mouseleave', function() {
        badgeContainer.style.transform = 'translateY(0)';
        badgeContainer.style.boxShadow = '0 4px 14px rgba(15, 23, 42, 0.15)';
      });

      if (script.parentNode) {
        script.parentNode.insertBefore(badgeContainer, script);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initVerifyNGBadge);
  } else {
    initVerifyNGBadge();
  }
})();
