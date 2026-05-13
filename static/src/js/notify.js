/**
 * Toast dispatcher.
 *
 * Replaces every `alert(...)` and `confirm(...)` left in the codebase.
 * Templates dispatch via `notify(msg)` / `notify({title, message, type})`.
 */
export function notify(payload, type = 'info') {
  const detail = typeof payload === 'string'
    ? { message: payload, type }
    : { ...(payload || {}), type: payload?.type || type };
  window.dispatchEvent(new CustomEvent('notify', { detail }));
}

notify.success = (msg, opts = {}) => notify({ message: msg, ...opts, type: 'success' });
notify.error   = (msg, opts = {}) => notify({ message: msg, ...opts, type: 'error'   });
notify.warning = (msg, opts = {}) => notify({ message: msg, ...opts, type: 'warning' });
notify.info    = (msg, opts = {}) => notify({ message: msg, ...opts, type: 'info'    });
