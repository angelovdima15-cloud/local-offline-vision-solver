import Foundation
import Combine

struct CapturedPage: Codable, Identifiable {
    let id: String
    let filename: String
}
struct SavedTask: Codable {
    var id: String
    var pages: [CapturedPage]
    var submitted: Bool
    var backend: String?
    var resultID: String?
}

@MainActor final class TaskController: ObservableObject {
    @Published var task: SavedTask
    @Published var busy = false
    @Published var stage = ""
    @Published var error: String?
    @Published var answer: AnswerPackage?
    @Published var backendFailed = false
    private let client = BackendClient()
    private var operation: Task<Void, Never>?
    private var stateFile: URL { LocalFiles.root.appendingPathComponent("active_task.json") }
    private var directory: URL { LocalFiles.root.appendingPathComponent("Capture", isDirectory: true).appendingPathComponent(task.id, isDirectory: true) }

    init() {
        let file = LocalFiles.root.appendingPathComponent("active_task.json")
        if let data = try? Data(contentsOf: file), let saved = try? JSONDecoder().decode(SavedTask.self, from: data),
           UUID(uuidString: saved.id) != nil {
            task = saved
            if let id = saved.resultID { answer = try? LocalFiles.loadHeader(id) }
        } else { task = SavedTask(id: UUID().uuidString.lowercased(), pages: [], submitted: false) }
        try? LocalFiles.prepare(LocalFiles.root)
    }
    func pageURL(_ page: CapturedPage) -> URL { directory.appendingPathComponent(page.filename) }
    private func save() throws {
        try LocalFiles.prepare(LocalFiles.root)
        try JSONEncoder().encode(task).write(to: stateFile, options: .atomic)
    }
    func add(_ data: Data) {
        guard !task.submitted, task.pages.count < 12 else { error = "Start a new task before adding pages."; return }
        do {
            try LocalFiles.prepare(directory)
            let id = UUID().uuidString.lowercased()
            let page = CapturedPage(id: id, filename: id + ".jpg")
            try data.write(to: pageURL(page), options: .atomic)
            task.pages.append(page); try save(); error = nil
        } catch { self.error = error.localizedDescription }
    }
    func remove(_ offsets: IndexSet) {
        guard !task.submitted else { return }
        for index in offsets.sorted(by: >) {
            let page = task.pages.remove(at: index)
            try? FileManager.default.removeItem(at: pageURL(page))
        }
        do { try save() } catch { self.error = error.localizedDescription }
    }
    func move(_ source: IndexSet, _ destination: Int) {
        guard !task.submitted else { return }
        var pages = task.pages
        let moving = source.sorted().map { pages[$0] }
        let adjusted = destination - source.filter { $0 < destination }.count
        for index in source.sorted(by: >) { pages.remove(at: index) }
        pages.insert(contentsOf: moving, at: adjusted); task.pages = pages
        do { try save() } catch { self.error = error.localizedDescription }
    }
    @discardableResult func newTask(keepPages: Bool = false) -> Bool {
        guard !busy else { return false }
        let old = task
        let oldDirectory = directory
        let nextID = UUID().uuidString.lowercased()
        let nextDirectory = LocalFiles.root.appendingPathComponent("Capture", isDirectory: true)
            .appendingPathComponent(nextID, isDirectory: true)
        do {
            if keepPages {
                try LocalFiles.prepare(nextDirectory)
                for page in old.pages {
                    try FileManager.default.copyItem(at: oldDirectory.appendingPathComponent(page.filename),
                                                    to: nextDirectory.appendingPathComponent(page.filename))
                }
            }
            task = SavedTask(id: nextID, pages: keepPages ? old.pages : [], submitted: false)
            try save()
        } catch {
            task = old
            try? FileManager.default.removeItem(at: nextDirectory)
            self.error = "Could not preserve photographs: " + error.localizedDescription
            return false
        }
        answer = nil; error = nil; backendFailed = false; stage = ""
        if let address = old.backend, let base = URL(string: address) { Task { await client.delete(base, id: old.id) } }
        try? FileManager.default.removeItem(at: oldDirectory)
        return true
    }
    func submit(_ discovered: URL?, relay: WatchRelay) {
        guard !busy, !task.pages.isEmpty else { return }
        let base = task.submitted ? task.backend.flatMap(URL.init(string:)) : discovered
        guard let base else { error = "Laptop not found. Check Wi-Fi or enter its address."; return }
        if backendFailed && !newTask(keepPages: true) { return }
        task.backend = base.absoluteString
        busy = true; error = nil
        operation = Task {
            do {
                let health = try await client.health(base)
                guard task.pages.count <= health.max_pages else { throw BackendError.message("Too many pages for this laptop.") }
                let existing = try await client.create(base, id: task.id)
                if existing.state == "RECEIVING" {
                    guard health.demo || health.model_status == "ready" else {
                        throw BackendError.message(health.model_status == "loading" ? "Model is loading. Try again shortly." : "AI backend unavailable. Check laptop.")
                    }
                    // Freeze order before the first PUT: retries retain the same page numbering.
                    task.submitted = true; try save()
                    for (index, page) in task.pages.enumerated() {
                        stage = "Uploading \(index + 1)/\(task.pages.count)"
                        try await client.upload(base, id: task.id, index: index + 1, file: pageURL(page))
                    }
                    _ = try await client.solve(base, id: task.id, count: task.pages.count)
                } else { task.submitted = true; try save() }
                // Allow long complete solutions; never abandon verification at 60 seconds.
                while true {
                    try Task.checkCancellation()
                    let status = try await client.status(base, id: task.id)
                    stage = Self.label(status.state)
                    if status.state == "ERROR" {
                        backendFailed = true
                        throw BackendError.message(status.error?.code == "retake_required" ?
                            "Image unreadable or a page is missing. Retake the affected page." :
                            (status.error?.message ?? "Processing failed. Check laptop."))
                    }
                    if status.result_available { break }
                    try await Task.sleep(for: .seconds(1))
                }
                stage = "Receiving answer"
                try LocalFiles.prepare(directory)
                let structured = try await client.structuredResult(base, id: task.id)
                try structured.write(to: directory.appendingPathComponent("result.json"), options: .atomic)
                let package = directory.appendingPathComponent("result.lvsp")
                try await client.download(base, id: task.id, destination: package)
                let parsed = try await Task.detached { try PackageReader.unpack(package) }.value
                guard parsed.session_id == task.id else { throw PackageError.invalid("wrong session") }
                answer = parsed; task.resultID = parsed.session_id; try save()
                stage = "Sending to Watch"
                try relay.enqueue(package, header: parsed)
            } catch is CancellationError {
                stage = "Paused — resume when the app is active"
            } catch { self.error = error.localizedDescription }
            busy = false
        }
    }
    func resume(_ discovered: URL?, relay: WatchRelay) {
        guard task.submitted, answer == nil, !busy else { return }
        submit(discovered, relay: relay)
    }
    func pause() { operation?.cancel() }
    static func label(_ state: String) -> String {
        switch state {
        case "RECEIVING": return "Uploading"
        case "QUEUED": return "Waiting for laptop"
        case "VALIDATING_IMAGES": return "Checking photographs"
        case "UNDERSTANDING", "UNDERSTANDING_RETRY": return "Reading task"
        case "SOLVING": return "Solving"
        case "VERIFYING", "VERIFYING_INDEPENDENT", "VERIFYING_AUDIT": return "Checking solution"
        case "CORRECTING": return "Correcting solution"
        case "RENDERING": return "Rendering"
        case "SENDING", "COMPLETE": return "Receiving answer"
        default: return "Processing…"
        }
    }
}
