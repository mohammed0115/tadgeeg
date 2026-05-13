/**
 * Tadgeeg frontend entry.
 *
 * Bundles the three vendor libraries the platform actually uses
 * (Alpine, Chart.js, Lucide), the shared `apiFetch` helper, the
 * toast store, and a single icon-render bootstrap.
 *
 * Replaces:
 *   • static/vendor/alpine.min.js
 *   • static/vendor/chart.umd.min.js
 *   • static/vendor/lucide.min.js
 *   • static/vendor/tailwind.browser.js   ← deleted; CSS is built ahead of time
 *
 * Pages that need Chart.js explicitly already check `window.Chart`.
 */
import Alpine from 'alpinejs';
import * as lucide from 'lucide';
import Chart from 'chart.js/auto';

import { apiFetch } from './api.js';
import { toastStore } from './toast.js';
import { notify } from './notify.js';
import { shell } from './shell.js';
import { commandPalette } from './command-palette.js';

window.Alpine = Alpine;
window.Chart  = Chart;
window.lucide = lucide;
window.apiFetch = apiFetch;
window.notify   = notify;

Alpine.data('toastStore',    toastStore);
Alpine.data('shell',         shell);
Alpine.data('commandPalette', commandPalette);

document.addEventListener('DOMContentLoaded', () => {
  lucide.createIcons();
});
document.addEventListener('alpine:initialized', () => {
  lucide.createIcons();
});

Alpine.start();
