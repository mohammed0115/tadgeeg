/**
 * Shell — top-level Alpine state for the app frame (sidebar, dark mode,
 * mobile-nav). Replaces the inline `shell()` block in base.html so the
 * SSR template gets smaller and the logic is testable.
 */
export function shell() {
  return {
    dark:                localStorage.getItem('fin_dark')    === 'true',
    desktopSidebarOpen:  localStorage.getItem('fin_sidebar') !== 'false',
    mobileNavOpen:       false,
    isDesktop:           window.innerWidth >= 1024,
    isRtl:               document.documentElement.dir === 'rtl',

    get sidebarOpen() {
      return this.isDesktop ? this.desktopSidebarOpen : true;
    },

    init() {
      this._syncSidebarActive();
      this.handleResize();
      window.addEventListener('resize', () => this.handleResize());
      // Cmd+K / Ctrl+K → open command palette.
      window.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
          e.preventDefault();
          window.dispatchEvent(new CustomEvent('open-command-palette'));
        }
      });
    },

    handleResize() {
      const nextDesktop = window.innerWidth >= 1024;
      if (nextDesktop !== this.isDesktop) this.isDesktop = nextDesktop;
      if (this.isDesktop) {
        this.mobileNavOpen = false;
        document.body.classList.remove('overflow-hidden');
      }
    },

    sidebarStyle() {
      if (!this.isDesktop) return '';
      return `inline-size:${this.desktopSidebarOpen ? 260 : 72}px`;
    },

    openMobileNav() {
      if (this.isDesktop) return;
      this.mobileNavOpen = true;
      document.body.classList.add('overflow-hidden');
      this.$nextTick(() => window.lucide?.createIcons());
    },
    closeMobileNav() {
      this.mobileNavOpen = false;
      document.body.classList.remove('overflow-hidden');
    },
    toggleSidebar() {
      this.desktopSidebarOpen = !this.desktopSidebarOpen;
      localStorage.setItem('fin_sidebar', this.desktopSidebarOpen);
      this.$nextTick(() => window.lucide?.createIcons());
    },

    /**
     * JS-side fallback for `.nav-item.active` highlighting when Django's
     * `{% block nav_xxx %}active{% endblock %}` wasn't set. Driven from
     * the current pathname.
     */
    _syncSidebarActive() {
      const path = window.location.pathname;
      const map = [
        { re: /^\/dashboard/,                              key: 'nav_dashboard'   },
        { re: /^\/auditor\/upload|^\/documents\/upload/,    key: 'nav_upload'      },
        { re: /^\/invoices/,                                key: 'nav_invoices'    },
        { re: /^\/batches/,                                 key: 'nav_batches'     },
        { re: /^\/reports/,                                 key: 'nav_reports'     },
        { re: /^\/compliance/,                              key: 'nav_compliance'  },
        { re: /^\/audit/,                                   key: 'nav_audit'       },
        { re: /^\/documents/,                               key: 'nav_documents'   },
        { re: /^\/settings/,                                key: 'nav_settings'    },
        { re: /^\/users/,                                   key: 'nav_users'       },
      ];
      for (const { re, key } of map) {
        if (!re.test(path)) continue;
        document.querySelectorAll(`.nav-item[data-nav="${key}"]`)
          .forEach(el => el.classList.add('active'));
      }
    },
  };
}
