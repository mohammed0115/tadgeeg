import { defineConfig } from 'vite';
import { resolve } from 'path';

/**
 * Tadgeeg frontend build.
 *
 * Inputs:
 *   static/src/css/app.css   →  Tailwind + design tokens + component layers
 *   static/src/js/app.js     →  Alpine + apiFetch + toasts + chart bootstrap
 *
 * Outputs:
 *   static/dist/app.[hash].css
 *   static/dist/app.[hash].js
 *   static/dist/manifest.json   ← consumed by `asset_tags.asset()` template tag
 */
export default defineConfig({
  base: '/static/dist/',
  root: 'static/src',
  build: {
    outDir:        '../dist',
    emptyOutDir:   true,
    manifest:      true,
    sourcemap:     true,
    cssCodeSplit:  false,
    rollupOptions: {
      input: {
        app: resolve(__dirname, 'static/src/js/app.js'),
      },
      output: {
        entryFileNames: 'app.[hash].js',
        chunkFileNames: 'chunks/[name].[hash].js',
        assetFileNames: '[name].[hash][extname]',
      },
    },
  },
  server: { hmr: false },   // not used; we ship a build, Django serves it.
});
