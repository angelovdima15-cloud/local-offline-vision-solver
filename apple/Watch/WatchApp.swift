import SwiftUI
import WatchKit
import WatchConnectivity

final class WatchDelegate: NSObject, WKApplicationDelegate {
    private var tasks: [WKWatchConnectivityRefreshBackgroundTask] = []
    private var pendingObservation: NSKeyValueObservation?
    override init() {
        super.init()
        WatchResultStore.shared.onTransferIdle = { [weak self] in self?.finishIfIdle() }
        pendingObservation = WCSession.default.observe(\.hasContentPending, options: [.new]) { [weak self] _, _ in
            DispatchQueue.main.async { self?.finishIfIdle() }
        }
    }
    func handle(_ backgroundTasks: Set<WKRefreshBackgroundTask>) {
        for task in backgroundTasks {
            if let connectivity = task as? WKWatchConnectivityRefreshBackgroundTask { tasks.append(connectivity) }
            else { task.setTaskCompletedWithSnapshot(false) }
        }
        finishIfIdle()
    }
    private func finishIfIdle() {
        guard WatchResultStore.shared.ready, !WatchResultStore.shared.isProcessing,
              !WCSession.default.hasContentPending else { return }
        for task in tasks { task.setTaskCompletedWithSnapshot(false) }
        tasks.removeAll()
    }
}

@main struct VisionWatchApp: App {
    @WKApplicationDelegateAdaptor(WatchDelegate.self) private var delegate
    @StateObject private var store = WatchResultStore.shared
    var body: some Scene {
        WindowGroup {
            if let answer = store.answer {
                TabView {
                    ForEach(answer.cards) { card in
                        ScrollView {
                            if let url = try? LocalFiles.cardURL(answer.session_id, card),
                               let image = UIImage(contentsOfFile: url.path) {
                                Image(uiImage: image).resizable().scaledToFit().frame(maxWidth: .infinity)
                            }
                        }.background(.black)
                    }
                }.tabViewStyle(.page).background(.black)
                    .id(answer.session_id)
            } else {
                Text(store.failure ?? "Take a task photo on iPhone. Answers will appear here.")
                    .font(.body).multilineTextAlignment(.center).padding()
            }
        }
    }
}
