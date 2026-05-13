/**
 * CSP nonce propagator.
 *
 * When the Django CSP middleware injects `<meta name="csp-nonce">` into
 * <head>, this script reads it and attaches it to dynamically-created
 * <script>/<style> elements so strict CSP (`script-src 'self' 'nonce-XYZ'`)
 * works for Chart.js / Alpine.
 */
(function () {
  const meta = document.querySelector('meta[name="csp-nonce"]');
  if (!meta) return;
  const nonce = meta.getAttribute('content');
  window.__cspNonce = nonce;
  // Patch document.createElement so injected scripts inherit the nonce.
  const orig = document.createElement;
  document.createElement = function (tag, opts) {
    const el = orig.call(document, tag, opts);
    if (/^(script|style)$/i.test(tag)) {
      el.setAttribute('nonce', nonce);
    }
    return el;
  };
})();
