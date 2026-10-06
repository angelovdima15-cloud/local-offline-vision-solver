from pathlib import Path
import plistlib
import re
import xml.etree.ElementTree as ET

from local_vision_solver.package import inspect_package

ROOT = Path(__file__).resolve().parents[1]


def test_native_targets_share_protocol_and_companion_identifiers():
    project = (ROOT / "apple/LocalVisionSolver.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
    objects = set(re.findall(r"^\s*([0-9A-F]{24}) =", project, re.MULTILINE))
    referenced = set(re.findall(r"\b[0-9A-F]{24}\b", project))
    assert referenced == objects
    assert project.count("isa = PBXNativeTarget;") == 2
    assert "Embed Watch Content" in project
    for source in (ROOT / "apple").glob("*/*.swift"):
        if source.parent.name == "Tests": continue
        assert source.relative_to(ROOT / "apple").as_posix() in project
    for scheme in (ROOT / "apple/LocalVisionSolver.xcodeproj/xcshareddata/xcschemes").glob("*.xcscheme"):
        ET.parse(scheme)
    with (ROOT / "apple/iOS/Info.plist").open("rb") as file:
        phone = plistlib.load(file)
    with (ROOT / "apple/Watch/Info.plist").open("rb") as file:
        watch = plistlib.load(file)
    assert phone["NSBonjourServices"] == ["_visionsolver._tcp"]
    assert phone["NSAppTransportSecurity"]["NSAllowsLocalNetworking"]
    assert "NSAllowsArbitraryLoads" not in phone["NSAppTransportSecurity"]
    assert watch["WKCompanionAppBundleIdentifier"] == "$(VISION_IOS_BUNDLE_ID)"
    assert watch["WKRunsIndependentlyOfCompanionApp"] is False


def test_shared_swift_fixture_matches_python_framing():
    value = inspect_package(ROOT / "apple/Tests/Fixtures/transport.lvsp")
    assert value["demo"] is True
    assert value["session_id"] == "11111111-1111-4111-8111-111111111111"
    assert len(value["cards"]) == 1
