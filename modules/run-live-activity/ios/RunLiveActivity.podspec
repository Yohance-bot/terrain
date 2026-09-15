Pod::Spec.new do |s|
  s.name = 'RunLiveActivity'
  s.version = '1.0.0'
  s.summary = 'TerraRun on the Lock Screen and Dynamic Island'
  s.description = s.summary
  s.license = { :type => 'MIT' }
  s.author = 'TerraRun'
  s.homepage = 'https://example.com/terrarun'
  s.platforms = { :ios => '15.1' }
  s.swift_version = '5.9'
  s.source = { :path => '.' }
  s.static_framework = true
  s.dependency 'ExpoModulesCore'
  s.source_files = '**/*.swift'
  s.pod_target_xcconfig = { 'DEFINES_MODULE' => 'YES' }
end
