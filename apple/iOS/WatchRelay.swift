import Foundation
import Combine
import WatchConnectivity

struct Delivery: Codable {
    let sessionID: String
    let file: String
    var state: String
}

final class WatchRelay: NSObject, ObservableObject, WCSessionDelegate {
    @Published var message = "Waiting for Watch"
    @Published var deliveries: [String: Delivery] = [:]
    private let session = WCSession.default
    private var directory: URL { LocalFiles.root.appendingPathComponent("Outbox", isDirectory: true) }

    override init() {
        super.init()
        do {
            try LocalFiles.prepare(directory)
            let file = directory.appendingPathComponent("queue.json")
            if let data = try? Data(contentsOf: file) { deliveries = try JSONDecoder().decode([String: Delivery].self, from: data) }
        } catch { message = error.localizedDescription }
        if WCSession.isSupported() { session.delegate = self; session.activate() }
        else { message = "WatchConnectivity unavailable" }
    }

    private func persist() {
        do { try JSONEncoder().encode(deliveries).write(to: directory.appendingPathComponent("queue.json"), options: .atomic) }
        catch { message = "Could not save Watch delivery queue" }
    }
    func enqueue(_ package: URL, header: AnswerPackage) throws {
        if deliveries[header.session_id]?.state == "delivered" { message = "Delivered to Watch"; return }
        let filename = header.session_id + ".lvsp"
        let destination = directory.appendingPathComponent(filename)
        if !FileManager.default.fileExists(atPath: destination.path) {
            try FileManager.default.copyItem(at: package, to: destination)
        }
        if deliveries[header.session_id]?.state != "delivered" {
            deliveries[header.session_id] = Delivery(sessionID: header.session_id, file: filename, state: "queued")
            persist()
        }
        flush()
    }
    func flush() {
        guard session.activationState == .activated, session.isPaired, session.isWatchAppInstalled else {
            message = "Watch unavailable — answer saved on iPhone"; return
        }
        let outstanding = Set(session.outstandingFileTransfers.compactMap { $0.file.metadata?["session_id"] as? String })
        for delivery in Array(deliveries.values) where delivery.state != "delivered" && !outstanding.contains(delivery.sessionID) {
            // Waiting for ACK is not proof of receipt. Resend after activation/retry; Watch deduplicates.
            let file = directory.appendingPathComponent(delivery.file)
            guard FileManager.default.fileExists(atPath: file.path) else { continue }
            session.transferFile(file, metadata: ["session_id": delivery.sessionID, "kind": "answer_package"])
            deliveries[delivery.sessionID]?.state = "transferring"
        }
        persist(); message = "Sending to Watch"
        if deliveries.values.allSatisfy({ $0.state == "delivered" }) { message = "Delivered to Watch" }
    }
    func retry() { flush() }

    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        DispatchQueue.main.async {
            if let error { self.message = error.localizedDescription }
            else { self.flush() }
        }
    }
    func sessionDidBecomeInactive(_ session: WCSession) {}
    func sessionDidDeactivate(_ session: WCSession) { session.activate() }
    func sessionWatchStateDidChange(_ session: WCSession) { DispatchQueue.main.async { self.flush() } }
    func session(_ session: WCSession, didFinish fileTransfer: WCSessionFileTransfer, error: Error?) {
        guard let id = fileTransfer.file.metadata?["session_id"] as? String else { return }
        DispatchQueue.main.async {
            if self.deliveries[id]?.state == "delivered" { return }
            self.deliveries[id]?.state = error == nil ? "awaiting_ack" : "queued"
            self.message = error == nil ? "Waiting for Watch receipt" : "Watch transfer failed — tap Retry"
            self.persist()
        }
    }
    private func receive(_ message: [String: Any]) {
        guard message["kind"] as? String == "answer_receipt", let id = message["session_id"] as? String else { return }
        DispatchQueue.main.async {
            guard self.deliveries[id] != nil else { return }
            let accepted = message["accepted"] as? Bool == true
            self.deliveries[id]?.state = accepted ? "delivered" : "queued"
            self.message = accepted ? "Delivered to Watch" : "Watch could not read the result — tap Retry"
            self.persist()
            if accepted, let delivery = self.deliveries[id] {
                try? FileManager.default.removeItem(at: self.directory.appendingPathComponent(delivery.file))
            }
        }
    }
    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) { receive(userInfo) }
    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) { receive(message) }
}
