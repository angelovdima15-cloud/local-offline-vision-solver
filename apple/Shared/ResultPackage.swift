import Foundation
import CryptoKit
import ImageIO

struct AnswerCard: Codable, Identifiable, Equatable {
    let index: Int
    let file: String
    let byte_count: Int
    let sha256: String
    let width: Int
    let height: Int
    var id: Int { index }
}

struct AnswerPackage: Codable, Equatable {
    let schema_version: Int
    let session_id: String
    let created_at: Double
    let detected_language: String
    let plain_text_answer: String
    let demo: Bool
    let cards: [AnswerCard]
}

enum PackageError: LocalizedError {
    case invalid(String)
    var errorDescription: String? {
        switch self { case .invalid(let reason): return "Invalid answer package: \(reason)" }
    }
}

enum LocalFiles {
    static var root: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("LocalVisionSolver", isDirectory: true)
    }
    static func prepare(_ directory: URL) throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var url = directory
        var values = URLResourceValues()
        values.isExcludedFromBackup = true // Task photographs/answers must not enter iCloud backups.
        try url.setResourceValues(values)
    }
    static func sessionDirectory(_ identifier: String, storageRoot: URL = LocalFiles.root) throws -> URL {
        guard let id = UUID(uuidString: identifier) else { throw PackageError.invalid("session identifier") }
        return storageRoot.appendingPathComponent("Results", isDirectory: true)
            .appendingPathComponent(id.uuidString.lowercased(), isDirectory: true)
    }
    static func loadHeader(_ identifier: String, storageRoot: URL = LocalFiles.root) throws -> AnswerPackage {
        let directory = try sessionDirectory(identifier, storageRoot: storageRoot)
        return try JSONDecoder().decode(AnswerPackage.self, from: Data(contentsOf: directory.appendingPathComponent("manifest.json")))
    }
    static func cardURL(_ identifier: String, _ card: AnswerCard) throws -> URL {
        try sessionDirectory(identifier).appendingPathComponent(card.file)
    }
}

enum PackageReader {
    static let maximumBytes = 300 * 1024 * 1024
    static let maximumHeader = 8 * 1024 * 1024

    /// Receives the same binary framing produced by Windows package.py.
    /// Files are committed only after every PNG and SHA256 has been verified.
    static func unpack(_ source: URL, storageRoot: URL = LocalFiles.root) throws -> AnswerPackage {
        let values = try source.resourceValues(forKeys: [.fileSizeKey])
        guard let bytes = values.fileSize, bytes >= 12, bytes <= maximumBytes else {
            throw PackageError.invalid("size")
        }
        let data = try Data(contentsOf: source, options: .mappedIfSafe)
        guard data.prefix(8) == Data("LVSPKG01".utf8) else { throw PackageError.invalid("magic") }
        let headerSize = data[8..<12].reduce(0) { ($0 << 8) | Int($1) }
        guard headerSize > 0, headerSize <= maximumHeader, headerSize <= data.count - 12 else {
            throw PackageError.invalid("header length")
        }
        let headerData = data.subdata(in: 12..<(12 + headerSize))
        let header = try JSONDecoder().decode(AnswerPackage.self, from: headerData)
        guard header.schema_version == 1, UUID(uuidString: header.session_id) != nil,
              header.created_at.isFinite, !header.cards.isEmpty, header.cards.count <= 10000 else {
            throw PackageError.invalid("metadata")
        }
        let results = storageRoot.appendingPathComponent("Results", isDirectory: true)
        try LocalFiles.prepare(results)
        let staging = results.appendingPathComponent("staging_" + UUID().uuidString, isDirectory: true)
        try LocalFiles.prepare(staging)
        defer { try? FileManager.default.removeItem(at: staging) }
        var cursor = 12 + headerSize
        for (index, card) in header.cards.enumerated() {
            guard card.index == index + 1, card.file.range(of: #"^answer_[0-9]+\.png$"#, options: .regularExpression) != nil,
                  card.byte_count > 0, card.byte_count <= maximumBytes,
                  card.byte_count <= data.count - cursor, card.width > 0, card.height > 0,
                  card.width <= 4096, card.height <= 4096 else { throw PackageError.invalid("card metadata") }
            let image = data.subdata(in: cursor..<(cursor + card.byte_count))
            guard image.prefix(8) == Data([137, 80, 78, 71, 13, 10, 26, 10]) else {
                throw PackageError.invalid("PNG")
            }
            let hash = SHA256.hash(data: image).map { String(format: "%02x", $0) }.joined()
            guard hash == card.sha256 else { throw PackageError.invalid("card checksum") }
            guard let source = CGImageSourceCreateWithData(image as CFData, nil),
                  let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
                  let width = properties[kCGImagePropertyPixelWidth] as? Int,
                  let height = properties[kCGImagePropertyPixelHeight] as? Int,
                  width == card.width, height == card.height else {
                throw PackageError.invalid("PNG dimensions")
            }
            try image.write(to: staging.appendingPathComponent(card.file), options: .atomic)
            cursor += card.byte_count
        }
        guard cursor == data.count else { throw PackageError.invalid("trailing bytes") }
        try headerData.write(to: staging.appendingPathComponent("manifest.json"), options: .atomic)
        let destination = try LocalFiles.sessionDirectory(header.session_id, storageRoot: storageRoot)
        if FileManager.default.fileExists(atPath: destination.path) {
            let stored = try LocalFiles.loadHeader(header.session_id, storageRoot: storageRoot)
            guard stored == header else { throw PackageError.invalid("conflicting replay") }
            // A valid replay can restore locally missing/damaged cards after an interrupted write.
            let intact = header.cards.allSatisfy { card in
                guard let image = try? Data(contentsOf: destination.appendingPathComponent(card.file)),
                      image.count == card.byte_count else { return false }
                return SHA256.hash(data: image).map { String(format: "%02x", $0) }.joined() == card.sha256
            }
            if !intact {
                let previous = results.appendingPathComponent("repair_" + UUID().uuidString, isDirectory: true)
                try FileManager.default.moveItem(at: destination, to: previous)
                do {
                    try FileManager.default.moveItem(at: staging, to: destination)
                } catch {
                    // Keep the old result available if committing the replacement fails.
                    try? FileManager.default.moveItem(at: previous, to: destination)
                    throw error
                }
                try? FileManager.default.removeItem(at: previous)
            }
        } else {
            try FileManager.default.moveItem(at: staging, to: destination)
        }
        return header
    }
}
