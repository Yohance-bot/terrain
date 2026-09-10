const path = require('path');

// 'babel-preset-expo' isn't hoisted to the top-level node_modules in this
// tree, so the plain string form fails to resolve from this file's location.
// Resolve it explicitly relative to the 'expo' package that depends on it.
const babelPresetExpo = path.join(
  path.dirname(require.resolve('expo/package.json')),
  'node_modules',
  'babel-preset-expo'
);

module.exports = function (api) {
  api.cache(true);
  return {
    presets: [babelPresetExpo],
    plugins: ['react-native-worklets-core/plugin'],
  };
};
