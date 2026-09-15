const { withAppBuildGradle } = require('expo/config-plugins');
module.exports = config => withAppBuildGradle(config, config => {
  let code = config.modResults.contents;
  if (!code.includes('// TerraRun release signing')) {
    code = code.replace('signingConfigs {', `signingConfigs {
        // TerraRun release signing: credentials stay outside the repository.
        release {
            if (System.getenv('TERRARUN_KEYSTORE')) {
                storeFile file(System.getenv('TERRARUN_KEYSTORE'))
                storePassword System.getenv('TERRARUN_STORE_PASSWORD')
                keyAlias 'terrarun'
                keyPassword System.getenv('TERRARUN_STORE_PASSWORD')
            }
        }`);

  }
  code = code.replace(/(buildTypes \{\s*debug \{\s*signingConfig signingConfigs\.)\w+/, '$1debug');
  code = code.replace(/signingConfig signingConfigs\.\w+(\s+def enableShrinkResources)/, 'signingConfig signingConfigs.release$1');
  config.modResults.contents = code;
  return config;
});
