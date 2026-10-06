import Foundation

struct BackendHealth: Decodable {
    let service: String
    let api_version: Int
    let model_status: String
    let demo: Bool
    let max_pages: Int
}
struct JobFailure: Codable { let code: String; let message: String }
struct JobStatus: Decodable {
    let session_id: String
    let created_at: Double
    let state: String
    let result_available: Bool
    let error: JobFailure?
    let demo: Bool
}

enum BackendError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

final class BackendClient: NSObject, URLSessionTaskDelegate {
    private lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 90
        configuration.timeoutIntervalForResource = 600
        configuration.waitsForConnectivity = false
        configuration.urlCache = nil
        return URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
    }()

    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil) // A LAN backend must not redirect photographs to another endpoint.
    }

    static func localURL(_ input: String) throws -> URL {
        let text = input.contains("://") ? input : "http://" + input
        guard var parts = URLComponents(string: text), parts.scheme == "http",
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              let host = parts.host?.lowercased(), parts.path.isEmpty || parts.path == "/" else {
            throw BackendError.message("Enter the laptop LAN address, for example 192.168.1.20:8765.")
        }
        let fields = host.split(separator: ".").compactMap { Int($0) }
        let privateIPv4 = fields.count == 4 && fields.allSatisfy { (0...255).contains($0) } &&
            (fields[0] == 10 || fields[0] == 192 && fields[1] == 168 ||
             fields[0] == 172 && (16...31).contains(fields[1]) || fields[0] == 169 && fields[1] == 254)
        guard privateIPv4 || host.hasSuffix(".local") else {
            throw BackendError.message("Use a private Wi-Fi IPv4 address or Bonjour .local hostname.")
        }
        parts.path = ""
        parts.port = parts.port ?? 8765
        guard let url = parts.url else { throw BackendError.message("Invalid laptop address.") }
        return url
    }

    private func checked(_ data: Data, _ response: URLResponse) throws -> Data {
        guard let http = response as? HTTPURLResponse else { throw BackendError.message("Invalid laptop response.") }
        guard (200..<300).contains(http.statusCode) else {
            let message: String
            switch http.statusCode {
            case 404: message = "Session no longer exists on the laptop. Retry as a new task."
            case 409: message = "Session changed or already failed. Retry as a new task."
            case 413: message = "Photographs exceed the laptop upload limit."
            case 429: message = "Laptop queue is full. Try again shortly."
            default: message = "Laptop request failed (\(http.statusCode))."
            }
            throw BackendError.message(message)
        }
        return data
    }

    func health(_ base: URL) async throws -> BackendHealth {
        let (data, response) = try await session.data(from: base.appendingPathComponent("health"))
        let health = try JSONDecoder().decode(BackendHealth.self, from: checked(data, response))
        guard health.service == "local-vision-solver", health.api_version == 1 else {
            throw BackendError.message("This address is not a compatible Local Vision Solver.")
        }
        return health
    }

    private func jsonRequest(_ base: URL, _ path: String, _ object: [String: Any]) async throws -> JobStatus {
        var request = URLRequest(url: base.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: object)
        let (data, response) = try await session.data(for: request)
        return try JSONDecoder().decode(JobStatus.self, from: checked(data, response))
    }
    func create(_ base: URL, id: String) async throws -> JobStatus {
        try await jsonRequest(base, "v1/sessions", ["session_id": id])
    }
    func upload(_ base: URL, id: String, index: Int, file: URL) async throws {
        var request = URLRequest(url: base.appendingPathComponent("v1/sessions/\(id)/pages/\(index)"))
        request.httpMethod = "PUT"
        request.setValue("image/jpeg", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.upload(for: request, fromFile: file)
        _ = try checked(data, response)
    }
    func solve(_ base: URL, id: String, count: Int) async throws -> JobStatus {
        try await jsonRequest(base, "v1/sessions/\(id)/solve", ["page_count": count, "page_order": Array(1...count)])
    }
    func status(_ base: URL, id: String) async throws -> JobStatus {
        let (data, response) = try await session.data(from: base.appendingPathComponent("v1/sessions/\(id)"))
        return try JSONDecoder().decode(JobStatus.self, from: checked(data, response))
    }
    func structuredResult(_ base: URL, id: String) async throws -> Data {
        let (data, response) = try await session.data(from: base.appendingPathComponent("v1/sessions/\(id)/result"))
        let body = try checked(data, response)
        guard let result = try JSONSerialization.jsonObject(with: body) as? [String: Any],
              result["session_id"] as? String == id else { throw PackageError.invalid("structured result session") }
        return body
    }
    func download(_ base: URL, id: String, destination: URL) async throws {
        let (temporary, response) = try await session.download(from: base.appendingPathComponent("v1/sessions/\(id)/package"))
        _ = try checked(Data(), response)
        guard let size = try temporary.resourceValues(forKeys: [.fileSizeKey]).fileSize,
              size <= PackageReader.maximumBytes else { throw PackageError.invalid("package too large") }
        let staging = destination.appendingPathExtension("part")
        try? FileManager.default.removeItem(at: staging)
        try FileManager.default.moveItem(at: temporary, to: staging)
        if FileManager.default.fileExists(atPath: destination.path) {
            try FileManager.default.removeItem(at: destination)
        }
        try FileManager.default.moveItem(at: staging, to: destination)
    }
    func delete(_ base: URL, id: String) async {
        var request = URLRequest(url: base.appendingPathComponent("v1/sessions/\(id)"))
        request.httpMethod = "DELETE"
        _ = try? await session.data(for: request)
    }
}
