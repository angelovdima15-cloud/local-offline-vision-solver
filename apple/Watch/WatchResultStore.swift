import Foundation
import Combine
import WatchConnectivity
import WatchKit
import UserNotifications

final class WatchResultStore: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = WatchResultStore()
    @Published var answer: AnswerPackage?
    @Published var failure: String?
    private let work = DispatchQueue(label: "vision.watch.receive")
    private let session = WCSession.default
    private let processingLock = NSLock()
    private var processingCount = 0
    var isProcessing: Bool {
        processingLock.lock(); defer { processingLock.unlock() }
        return processingCount > 0
    }
    private var currentFile: URL { LocalFiles.root.appendingPathComponent("watch_current.json") }
    private(set) var ready = false
    var onTransferIdle: (() -> Void)?

    private override init() {
        super.init()
        try? LocalFiles.prepare(LocalFiles.root)
        if let data = try? Data(contentsOf: currentFile), let id = try? JSONDecoder().decode(String.self, from: data) {
            answer = try? LocalFiles.loadHeader(id)
        }
        if WCSession.isSupported() { session.delegate = self; session.activate() }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }
    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        DispatchQueue.main.async {
            self.ready = activationState == .activated
            if error != nil { self.failure = "Check iPhone." }
            self.onTransferIdle?()
        }
    }
    func session(_ session: WCSession, didReceive file: WCSessionFile) {
        // WCSession owns its URL only during this callback. Copy synchronously before returning.
        let inbox = LocalFiles.root.appendingPathComponent("Inbox", isDirectory: true)
        let staged = inbox.appendingPathComponent(UUID().uuidString + ".lvsp")
        let id = file.metadata?["session_id"] as? String
        do {
            try LocalFiles.prepare(inbox)
            try FileManager.default.copyItem(at: file.fileURL, to: staged)
        } catch {
            receipt(id, accepted: false)
            DispatchQueue.main.async { self.failure = "Processing failed. Check iPhone." }
            return
        }
        processingLock.lock(); processingCount += 1; processingLock.unlock()
        work.async {
            defer { try? FileManager.default.removeItem(at: staged) }
            do {
                let parsed = try PackageReader.unpack(staged)
                guard parsed.session_id == id else { throw PackageError.invalid("session mismatch") }
                // Commit/prune before the serial queue unpacks the next result. Otherwise
                // an earlier main-thread callback can delete the next result's directory.
                DispatchQueue.main.sync {
                    do {
                        let newer = self.answer == nil || parsed.created_at > self.answer!.created_at
                        if newer {
                            try JSONEncoder().encode(parsed.session_id).write(to: self.currentFile, options: .atomic)
                            self.answer = parsed; self.failure = nil
                            if WKApplication.shared().applicationState == .active { WKInterfaceDevice.current().play(.success) }
                            else { self.notify(parsed) }
                        }
                        self.receipt(parsed.session_id, accepted: true)
                        if let current = self.answer { self.prune(keeping: current.session_id) }
                    } catch { self.receipt(parsed.session_id, accepted: false); self.failure = "Check iPhone." }
                    self.processingLock.lock(); self.processingCount -= 1; self.processingLock.unlock()
                    self.onTransferIdle?()
                }
            } catch {
                self.receipt(id, accepted: false)
                DispatchQueue.main.async {
                    self.failure = "Processing failed. Check iPhone."
                    self.processingLock.lock(); self.processingCount -= 1; self.processingLock.unlock()
                    self.onTransferIdle?()
                }
            }
        }
    }
    private func receipt(_ id: String?, accepted: Bool) {
        guard let id, UUID(uuidString: id) != nil, session.activationState == .activated else { return }
        let message: [String: Any] = ["kind": "answer_receipt", "session_id": id, "accepted": accepted]
        session.transferUserInfo(message) // Durable even when iPhone isn't reachable.
        if session.isReachable { session.sendMessage(message, replyHandler: nil, errorHandler: nil) }
    }
    private func notify(_ answer: AnswerPackage) {
        let content = UNMutableNotificationContent()
        content.title = answer.demo ? "Transport demo received" : "Answer ready"
        content.body = "Open Local Vision Solver to read the complete answer."
        content.sound = .default
        content.userInfo = ["session_id": answer.session_id]
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: answer.session_id, content: content, trigger: nil))
    }
    private func prune(keeping id: String) {
        let root = LocalFiles.root.appendingPathComponent("Results", isDirectory: true)
        let keep = id.lowercased()
        guard let folders = try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil) else { return }
        for folder in folders where UUID(uuidString: folder.lastPathComponent) != nil && folder.lastPathComponent != keep {
            try? FileManager.default.removeItem(at: folder)
        }
    }
}
