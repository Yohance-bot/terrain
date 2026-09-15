const { withInfoPlist, withXcodeProject } = require('expo/config-plugins');
const fs = require('node:fs');
const path = require('node:path');

const NAME = 'TerraRunActivity';
module.exports = function withRunLiveActivity(config) {
  config = withInfoPlist(config, mod => {
    mod.modResults.NSSupportsLiveActivities = true;
    return mod;
  });
  return withXcodeProject(config, mod => {
    const project = mod.modResults;
    const root = mod.modRequest.projectRoot;
    const folder = path.join(mod.modRequest.platformProjectRoot, NAME);
    fs.mkdirSync(folder, { recursive: true });
    fs.copyFileSync(path.join(root, 'modules/run-live-activity/ios/RunActivityAttributes.swift'), path.join(folder, 'RunActivityAttributes.swift'));
    fs.copyFileSync(path.join(__dirname, 'live-activity/RunActivityWidget.swift'), path.join(folder, 'RunActivityWidget.swift'));
    fs.writeFileSync(path.join(folder, 'Info.plist'), `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleDisplayName</key><string>TerraRun</string>
<key>CFBundleExecutable</key><string>$(EXECUTABLE_NAME)</string>
<key>CFBundleIdentifier</key><string>$(PRODUCT_BUNDLE_IDENTIFIER)</string>
<key>CFBundleName</key><string>$(PRODUCT_NAME)</string>
<key>CFBundlePackageType</key><string>XPC!</string>
<key>CFBundleShortVersionString</key><string>$(MARKETING_VERSION)</string>
<key>CFBundleVersion</key><string>$(CURRENT_PROJECT_VERSION)</string>
<key>NSExtension</key><dict><key>NSExtensionPointIdentifier</key><string>com.apple.widgetkit-extension</string></dict>
</dict></plist>`);
    let target = Object.entries(project.pbxNativeTargetSection()).find(([, v]) => typeof v === 'object' && v.name?.replaceAll('"', '') === NAME);
    let uuid;
    if (target) uuid = target[0];
    else {
      uuid = project.addTarget(NAME, 'app_extension', NAME, `${mod.ios.bundleIdentifier}.activity`).uuid;
      project.addBuildPhase([`${NAME}/RunActivityAttributes.swift`, `${NAME}/RunActivityWidget.swift`], 'PBXSourcesBuildPhase', 'Sources', uuid);
      project.addBuildPhase([], 'PBXFrameworksBuildPhase', 'Frameworks', uuid);
      project.addBuildPhase([], 'PBXResourcesBuildPhase', 'Resources', uuid);
    }
    const native = project.pbxNativeTargetSection()[uuid];
    const configs = project.pbxXCConfigurationList()[native.buildConfigurationList].buildConfigurations;
    const main = project.getFirstTarget().firstTarget;
    const mainConfigs = project.pbxXCConfigurationList()[main.buildConfigurationList].buildConfigurations;
    for (const entry of configs) {
      const cfg = project.pbxXCBuildConfigurationSection()[entry.value];
      const mainEntry = mainConfigs.find(e => e.comment === cfg.name) ?? mainConfigs[0];
      const app = project.pbxXCBuildConfigurationSection()[mainEntry.value].buildSettings;
      Object.assign(cfg.buildSettings, {
        INFOPLIST_FILE: `${NAME}/Info.plist`, SWIFT_VERSION: '5.0', IPHONEOS_DEPLOYMENT_TARGET: '16.2',
        SDKROOT: 'iphoneos', TARGETED_DEVICE_FAMILY: '"1,2"',
        PRODUCT_BUNDLE_IDENTIFIER: `${mod.ios.bundleIdentifier}.activity`,
        APPLICATION_EXTENSION_API_ONLY: 'YES', GENERATE_INFOPLIST_FILE: 'NO', CODE_SIGN_STYLE: 'Automatic',
        CURRENT_PROJECT_VERSION: app.CURRENT_PROJECT_VERSION ?? '1', MARKETING_VERSION: app.MARKETING_VERSION ?? '1.0.0',
        ...(app.DEVELOPMENT_TEAM ? { DEVELOPMENT_TEAM: app.DEVELOPMENT_TEAM } : {}),
      });
    }
    return mod;
  });
};
