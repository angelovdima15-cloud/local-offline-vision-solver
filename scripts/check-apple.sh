#!/bin/bash
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root/apple"
swift test
xcodebuild -project LocalVisionSolver.xcodeproj -scheme VisionPhone \
  -destination 'generic/platform=iOS Simulator' -derivedDataPath "$project_root/.cache/xcode-phone" \
  CODE_SIGNING_ALLOWED=NO build
xcodebuild -project LocalVisionSolver.xcodeproj -scheme VisionWatch \
  -destination 'generic/platform=watchOS Simulator' -derivedDataPath "$project_root/.cache/xcode-watch" \
  CODE_SIGNING_ALLOWED=NO build

