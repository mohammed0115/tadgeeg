module.exports = {
  plugins: {
    'tailwindcss/nesting': {},
    'tailwindcss':         {},
    // Converts physical CSS (margin-right, padding-left) into logical
    // (margin-inline-end, padding-inline-start) so the same stylesheet
    // works in both RTL and LTR without dir-specific overrides.
    'postcss-logical':     { preserve: false },
    'autoprefixer':        {},
  },
};
