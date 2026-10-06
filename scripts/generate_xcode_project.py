"""Generate a deterministic two-target Xcode project; no XcodeGen or online packages."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1] / "apple"


def uid(name):
    return hashlib.sha1(name.encode()).hexdigest()[:24].upper()


def generate():
    objects = []

    def add(name, text):
        objects.append(f"\t\t{uid(name)} = {{ {text} }};")
        return uid(name)

    def quoted(value):
        return json.dumps(str(value))

    def array(values):
        return "(" + ", ".join(values) + ",)" if values else "()"

    shared = sorted(ROOT.glob("Shared/*.swift"))
    phone = shared + sorted(ROOT.glob("iOS/*.swift"))
    watch = shared + sorted(ROOT.glob("Watch/*.swift"))
    file_ids = []
    for path in sorted(set(phone + watch)):
        relative = path.relative_to(ROOT).as_posix()
        file_ids.append(add("file:" + relative, f'isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = {quoted(relative)}; sourceTree = "<group>";'))
    config_ref = add("signing", 'isa = PBXFileReference; lastKnownFileType = text.xcconfig; path = Signing.xcconfig; sourceTree = "<group>";')
    file_ids.append(config_ref)
    for kind in ("iOS", "Watch"):
        file_ids.append(add("plist:" + kind, f'isa = PBXFileReference; lastKnownFileType = text.plist.xml; path = {kind}/Info.plist; sourceTree = "<group>";'))
    product_phone = add("product:phone", 'isa = PBXFileReference; explicitFileType = wrapper.application; path = VisionPhone.app; sourceTree = BUILT_PRODUCTS_DIR;')
    product_watch = add("product:watch", 'isa = PBXFileReference; explicitFileType = wrapper.application; path = VisionWatch.app; sourceTree = BUILT_PRODUCTS_DIR;')
    products = add("products", f'isa = PBXGroup; children = {array([product_phone, product_watch])}; name = Products; sourceTree = "<group>";')
    main = add("main", f'isa = PBXGroup; children = {array(file_ids + [products])}; sourceTree = "<group>";')
    target_ids = []
    for kind, files in (("phone", phone), ("watch", watch)):
        builds = []
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            builds.append(add(f"build:{kind}:{relative}", f'isa = PBXBuildFile; fileRef = {uid("file:" + relative)};'))
        sources = add("sources:" + kind, f'isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = {array(builds)}; runOnlyForDeploymentPostprocessing = 0;')
        frameworks = add("frameworks:" + kind, 'isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0;')
        resources = add("resources:" + kind, 'isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0;')
        configurations = []
        for configuration in ("Debug", "Release"):
            settings = {
                "SWIFT_VERSION": "5.0", "SWIFT_STRICT_CONCURRENCY": "minimal",
                "SWIFT_OPTIMIZATION_LEVEL": "-Onone" if configuration == "Debug" else "-O",
                "ENABLE_TESTABILITY": "YES" if configuration == "Debug" else "NO",
                "GENERATE_INFOPLIST_FILE": "NO", "PRODUCT_NAME": "$(TARGET_NAME)",
                "CURRENT_PROJECT_VERSION": "1", "MARKETING_VERSION": "0.2.0",
                "SDKROOT": "iphoneos" if kind == "phone" else "watchos",
                "SUPPORTED_PLATFORMS": "iphoneos iphonesimulator" if kind == "phone" else "watchos watchsimulator",
                "PRODUCT_BUNDLE_IDENTIFIER": "$(VISION_IOS_BUNDLE_ID)" if kind == "phone" else "$(VISION_WATCH_BUNDLE_ID)",
                "INFOPLIST_FILE": "iOS/Info.plist" if kind == "phone" else "Watch/Info.plist",
                "TARGETED_DEVICE_FAMILY": "1" if kind == "phone" else "4",
                "LD_RUNPATH_SEARCH_PATHS": "$(inherited) @executable_path/Frameworks",
            }
            settings["IPHONEOS_DEPLOYMENT_TARGET" if kind == "phone" else "WATCHOS_DEPLOYMENT_TARGET"] = "17.0" if kind == "phone" else "10.0"
            if kind == "watch": settings["SKIP_INSTALL"] = "YES"
            value = " ".join(f"{key} = {quoted(value)};" for key, value in settings.items())
            configurations.append(add(f"config:{kind}:{configuration}", f'isa = XCBuildConfiguration; baseConfigurationReference = {config_ref}; buildSettings = {{ {value} }}; name = {configuration};'))
        listing = add("configlist:" + kind, f'isa = XCConfigurationList; buildConfigurations = {array(configurations)}; defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;')
        phases = [sources, frameworks, resources]
        dependencies = []
        if kind == "phone":
            proxy = add("watchproxy", f'isa = PBXContainerItemProxy; containerPortal = {uid("project")}; proxyType = 1; remoteGlobalIDString = {uid("target:watch")}; remoteInfo = VisionWatch;')
            dependencies.append(add("watchdependency", f'isa = PBXTargetDependency; target = {uid("target:watch")}; targetProxy = {proxy};'))
            embed = add("embedwatchfile", f'isa = PBXBuildFile; fileRef = {product_watch}; settings = {{ ATTRIBUTES = (RemoveHeadersOnCopy,); }};')
            phases.append(add("embedwatch", f'isa = PBXCopyFilesBuildPhase; buildActionMask = 2147483647; dstPath = "$(CONTENTS_FOLDER_PATH)/Watch"; dstSubfolderSpec = 16; files = {array([embed])}; name = "Embed Watch Content"; runOnlyForDeploymentPostprocessing = 0;'))
        name = "VisionPhone" if kind == "phone" else "VisionWatch"
        target_ids.append(add("target:" + kind, f'isa = PBXNativeTarget; buildConfigurationList = {listing}; buildPhases = {array(phases)}; buildRules = (); dependencies = {array(dependencies)}; name = {name}; productName = {name}; productReference = {product_phone if kind == "phone" else product_watch}; productType = "com.apple.product-type.application";'))
    project_configs = []
    for configuration in ("Debug", "Release"):
        project_configs.append(add("projectconfig:" + configuration, f'isa = XCBuildConfiguration; buildSettings = {{ CLANG_ENABLE_MODULES = YES; SWIFT_VERSION = 5.0; }}; name = {configuration};'))
    project_list = add("projectconfiglist", f'isa = XCConfigurationList; buildConfigurations = {array(project_configs)}; defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;')
    add("project", f'isa = PBXProject; attributes = {{ BuildIndependentTargetsInParallel = YES; LastUpgradeCheck = 1600; }}; buildConfigurationList = {project_list}; compatibilityVersion = "Xcode 14.0"; developmentRegion = en; hasScannedForEncodings = 0; knownRegions = (en, Base, ru, kk,); mainGroup = {main}; productRefGroup = {products}; projectDirPath = ""; projectRoot = ""; targets = {array(target_ids)};')
    directory = ROOT / "LocalVisionSolver.xcodeproj"
    directory.mkdir(exist_ok=True)
    (directory / "project.pbxproj").write_text("// !$*UTF8*$!\n{\n\tarchiveVersion = 1;\n\tclasses = {};\n\tobjectVersion = 56;\n\tobjects = {\n" + "\n".join(objects) + f"\n\t}};\n\trootObject = {uid('project')};\n}}\n", encoding="utf-8")
    schemes = directory / "xcshareddata" / "xcschemes"
    schemes.mkdir(parents=True, exist_ok=True)
    for kind, name in (("phone", "VisionPhone"), ("watch", "VisionWatch")):
        reference = f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{uid("target:" + kind)}" BuildableName="{name}.app" BlueprintName="{name}" ReferencedContainer="container:LocalVisionSolver.xcodeproj"/>'
        scheme = f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1600" version="1.3">
 <BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">{reference}</BuildActionEntry></BuildActionEntries></BuildAction>
 <TestAction buildConfiguration="Debug" shouldUseLaunchSchemeArgsEnv="YES"/>
 <LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" allowLocationSimulation="YES"><BuildableProductRunnable runnableDebuggingMode="0">{reference}</BuildableProductRunnable></LaunchAction>
 <ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0">{reference}</BuildableProductRunnable></ProfileAction>
 <AnalyzeAction buildConfiguration="Debug"/>
 <ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
'''
        (schemes / f"{name}.xcscheme").write_text(scheme, encoding="utf-8")
    print(directory)


if __name__ == "__main__":
    generate()

