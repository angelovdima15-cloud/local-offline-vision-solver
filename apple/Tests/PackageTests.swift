import XCTest
@testable import VisionTransport

final class PackageTests: XCTestCase {
    private func temporary() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }
    func testPythonFixtureAndReplay() throws {
        let fixture = try XCTUnwrap(Bundle.module.url(forResource: "transport", withExtension: "lvsp", subdirectory: "Fixtures"))
        let root = try temporary()
        let header = try PackageReader.unpack(fixture, storageRoot: root)
        XCTAssertTrue(header.demo)
        XCTAssertEqual(header.session_id, "11111111-1111-4111-8111-111111111111")
        XCTAssertEqual(header.cards.map(\.index), [1])
        XCTAssertTrue(header.plain_text_answer.contains("TRANSPORT DEMO"))
        let stored = try LocalFiles.loadHeader(header.session_id, storageRoot: root)
        XCTAssertEqual(stored.cards[0].sha256, header.cards[0].sha256)
        let replay = try PackageReader.unpack(fixture, storageRoot: root)
        XCTAssertEqual(replay.created_at, header.created_at)
    }
    func testChecksumFailureDoesNotCommit() throws {
        let fixture = try XCTUnwrap(Bundle.module.url(forResource: "transport", withExtension: "lvsp", subdirectory: "Fixtures"))
        let root = try temporary()
        var bytes = try Data(contentsOf: fixture)
        bytes[bytes.count - 1] ^= 0xFF
        let corrupt = root.appendingPathComponent("corrupt.lvsp")
        try bytes.write(to: corrupt)
        XCTAssertThrowsError(try PackageReader.unpack(corrupt, storageRoot: root))
        let destination = try LocalFiles.sessionDirectory("11111111-1111-4111-8111-111111111111", storageRoot: root)
        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.path))
    }
    func testTruncatedHeader() throws {
        let root = try temporary()
        let input = root.appendingPathComponent("short.lvsp")
        try Data("LVSPKG01".utf8).write(to: input)
        XCTAssertThrowsError(try PackageReader.unpack(input, storageRoot: root))
    }

    func testReplayRejectsChangedTextWithTheSameCards() throws {
        let fixture = try XCTUnwrap(Bundle.module.url(forResource: "transport", withExtension: "lvsp", subdirectory: "Fixtures"))
        let root = try temporary()
        let original = try PackageReader.unpack(fixture, storageRoot: root)
        let data = try Data(contentsOf: fixture)
        let headerSize = data[8..<12].reduce(0) { ($0 << 8) | Int($1) }
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: data.subdata(in: 12..<(12 + headerSize))) as? [String: Any])
        object["plain_text_answer"] = "Conflicting answer text"
        let revised = try JSONSerialization.data(withJSONObject: object)
        let count = UInt32(revised.count)
        var replay = Data("LVSPKG01".utf8)
        replay.append(contentsOf: [UInt8(truncatingIfNeeded: count >> 24), UInt8(truncatingIfNeeded: count >> 16),
                                   UInt8(truncatingIfNeeded: count >> 8), UInt8(truncatingIfNeeded: count)])
        replay.append(revised)
        replay.append(data.subdata(in: (12 + headerSize)..<data.count))
        let altered = root.appendingPathComponent("altered.lvsp")
        try replay.write(to: altered)
        XCTAssertThrowsError(try PackageReader.unpack(altered, storageRoot: root))
        XCTAssertEqual(try LocalFiles.loadHeader(original.session_id, storageRoot: root), original)
    }

    func testValidReplayRepairsMissingCard() throws {
        let fixture = try XCTUnwrap(Bundle.module.url(forResource: "transport", withExtension: "lvsp", subdirectory: "Fixtures"))
        let root = try temporary()
        let header = try PackageReader.unpack(fixture, storageRoot: root)
        let directory = try LocalFiles.sessionDirectory(header.session_id, storageRoot: root)
        let card = directory.appendingPathComponent(header.cards[0].file)
        try FileManager.default.removeItem(at: card)
        XCTAssertEqual(try PackageReader.unpack(fixture, storageRoot: root), header)
        XCTAssertEqual(try Data(contentsOf: card).count, header.cards[0].byte_count)
    }
}
