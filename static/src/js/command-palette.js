/**
 * Command Palette — Cmd+K / Ctrl+K.
 *
 * Lightweight client-side search across the app's main routes.
 * Power users can jump to "Invoices", "Audit Inbox", "Risk Matrix",
 * etc., without leaving the keyboard.
 *
 * Backend integration (server-side search across invoices / vendors
 * / cases) is wired through `apiFetch('/search/?q=...')` if available;
 * otherwise the palette falls back to the static route list.
 */
import { apiFetch } from './api.js';

const STATIC_ROUTES = [
  { id: 'dashboard',   title: 'Dashboard',          href: '/dashboard/',                 group: 'Pages'  },
  { id: 'upload',      title: 'Upload document',    href: '/auditor/upload/',            group: 'Pages'  },
  { id: 'invoices',    title: 'Invoices',           href: '/invoices/',                  group: 'Pages'  },
  { id: 'inbox',       title: 'Approval inbox',     href: '/audit/inbox/',               group: 'Audit'  },
  { id: 'risk',        title: 'Risk matrix',        href: '/audit/risk-matrix/',         group: 'Audit'  },
  { id: 'reports',     title: 'Reports',            href: '/reports/',                   group: 'Pages'  },
  { id: 'compliance',  title: 'Compliance',         href: '/compliance/',                group: 'Pages'  },
  { id: 'users',       title: 'Users',              href: '/users/',                     group: 'Admin'  },
  { id: 'settings',    title: 'Settings',           href: '/settings/',                  group: 'Admin'  },
  { id: 'billing',     title: 'Subscription',       href: '/billing/subscription/',      group: 'Billing'},
];

export function commandPalette() {
  return {
    open:    false,
    query:   '',
    cursor:  0,
    results: STATIC_ROUTES,
    _searchDebounce: null,

    init() {
      window.addEventListener('open-command-palette', () => this.show());
      window.addEventListener('keydown', (e) => {
        if (!this.open) return;
        if (e.key === 'Escape') this.hide();
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          this.cursor = Math.min(this.cursor + 1, this.results.length - 1);
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          this.cursor = Math.max(this.cursor - 1, 0);
        }
        if (e.key === 'Enter' && this.results[this.cursor]) {
          window.location.href = this.results[this.cursor].href;
        }
      });
    },

    show() {
      this.open = true;
      this.query = '';
      this.cursor = 0;
      this.results = STATIC_ROUTES;
      this.$nextTick(() => this.$refs.input?.focus());
    },
    hide() {
      this.open = false;
    },

    onInput() {
      clearTimeout(this._searchDebounce);
      const q = this.query.trim().toLowerCase();
      if (!q) {
        this.results = STATIC_ROUTES;
        this.cursor = 0;
        return;
      }
      // Local fuzzy match
      this.results = STATIC_ROUTES.filter(r =>
        r.title.toLowerCase().includes(q) || r.group.toLowerCase().includes(q)
      );
      this.cursor = 0;
      // Server-side augment, debounced
      this._searchDebounce = setTimeout(() => this._serverSearch(q), 200);
    },

    async _serverSearch(q) {
      try {
        const data = await apiFetch(`/search/?q=${encodeURIComponent(q)}`);
        if (data && Array.isArray(data.results)) {
          this.results = [...this.results, ...data.results];
        }
      } catch (_) {
        // Backend search optional — silent fallback to static.
      }
    },
  };
}
