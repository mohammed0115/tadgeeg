/**
 * Toast store for Alpine.
 *
 * Mounted in base.html via `x-data="toastStore()"`.
 * Dispatch from anywhere with `notify(msg)` or `notify({...})`.
 */
const TADGEEG_I18N = window.TADGEEG_I18N || {};

const PRESETS = {
  success: { title: TADGEEG_I18N.msg?.toast_success || 'Operation completed', icon: '✓' },
  error:   { title: TADGEEG_I18N.msg?.toast_error   || 'Operation failed',    icon: '!' },
  info:    { title: TADGEEG_I18N.msg?.toast_info    || 'Notice',              icon: 'i' },
  warning: { title: TADGEEG_I18N.msg?.toast_warning || 'Attention required',  icon: '!' },
};

export function toastStore() {
  return {
    toasts: [],
    push(payload) {
      const detail = typeof payload === 'string'
        ? { message: payload }
        : (payload || {});
      const type   = detail.type || 'info';
      const preset = PRESETS[type] || PRESETS.info;
      const id     = Date.now() + Math.random();
      const duration = Number.isFinite(detail.duration)
        ? detail.duration
        : (type === 'error' ? 7000 : 4500);

      this.toasts.push({
        id, type,
        title:   detail.title   || preset.title,
        message: detail.message || detail.detail || detail.error || '',
        icon:    detail.icon    || preset.icon,
        visible: true,
      });
      this.$nextTick(() => window.lucide?.createIcons());
      setTimeout(() => this.dismiss(id), duration);
    },
    dismiss(id) {
      const t = this.toasts.find(t => t.id === id);
      if (!t) return;
      t.visible = false;
      setTimeout(() => {
        this.toasts = this.toasts.filter(x => x.id !== id);
      }, 300);
    },
  };
}
