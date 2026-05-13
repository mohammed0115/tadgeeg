/**
 * Single API helper for every fetch in the app.
 *
 * Responsibilities:
 *   • Auto-attach CSRF token from the `csrftoken` cookie.
 *   • Auto-redirect to /login/?next=... on 401.
 *   • Parse JSON / text based on content-type.
 *   • Throw on !res.ok with the server's `detail` / `error` message.
 *   • Surface 402 (billing) and 403 (permission) as typed errors.
 *
 * Never let a template build its own raw `fetch()` — the central
 * helper is the only thing that guarantees CSRF + session refresh
 * + i18n error messages.
 */

const CSRF = () =>
  (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';

let _authRedirecting = false;

export class APIError extends Error {
  constructor(message, { status, code, detail } = {}) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export async function apiFetch(path, opts = {}) {
  const isFormData = typeof FormData !== 'undefined' &&
                     opts.body instanceof FormData;
  const headers = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    'X-CSRFToken': CSRF(),
    ...(opts.headers || {}),
  };
  const url = path.startsWith('/api/') ? path : '/api/v1' + path;

  const res = await fetch(url, {
    credentials: 'same-origin',
    ...opts,
    headers,
  });

  if (res.status === 401) {
    if (!_authRedirecting) {
      _authRedirecting = true;
      window.location.href = '/login/?next=' +
        encodeURIComponent(window.location.pathname);
    }
    return null;
  }
  if (res.status === 204) return null;

  const ct = res.headers.get('content-type') || '';
  const body = ct.includes('application/json')
    ? await res.json().catch(() => ({}))
    : await res.text();

  if (!res.ok) {
    const message =
      (typeof body === 'object' && (body.detail || body.error)) ||
      (typeof body === 'string' && body) ||
      `HTTP ${res.status}`;
    throw new APIError(message, {
      status: res.status,
      code:   body && body.code,
      detail: body && body.detail,
    });
  }
  return body;
}
