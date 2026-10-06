import Foundation
import Combine

/// Browses only the declared service. Resolution doesn't assume a Wi-Fi interface name.
final class BackendDiscovery: NSObject, ObservableObject, NetServiceBrowserDelegate, NetServiceDelegate {
    @Published var backend: URL?
    @Published var message = "Looking for laptop…"
    private let browser = NetServiceBrowser()
    private var services: [NetService] = []
    private let client = BackendClient()
    private var manual = false

    override init() { super.init(); browser.delegate = self }
    func start() { browser.searchForServices(ofType: "_visionsolver._tcp.", inDomain: "local.") }
    func retry() {
        browser.stop(); services.removeAll(); backend = nil; manual = false
        message = "Looking for laptop…"; start()
    }
    func useManual(_ input: String) async {
        do {
            let address = try BackendClient.localURL(input)
            let health = try await client.health(address)
            await MainActor.run {
                self.manual = true; self.backend = address
                self.message = health.demo ? "Connected · transport demo" : "Laptop connected"
            }
        } catch { await MainActor.run { self.message = error.localizedDescription } }
    }
    func netServiceBrowser(_ browser: NetServiceBrowser, didFind service: NetService, moreComing: Bool) {
        services.append(service); service.delegate = self; service.resolve(withTimeout: 5)
    }
    func netServiceDidResolveAddress(_ sender: NetService) {
        guard !manual, let host = sender.hostName else { return }
        let trimmed = host.hasSuffix(".") ? String(host.dropLast()) : host
        var parts = URLComponents(); parts.scheme = "http"; parts.host = trimmed; parts.port = sender.port
        guard let candidate = parts.url, let url = try? BackendClient.localURL(candidate.absoluteString) else { return }
        Task {
            do {
                let health = try await client.health(url)
                await MainActor.run {
                    guard !self.manual else { return }
                    self.backend = url
                    self.message = health.demo ? "Connected · transport demo" : "Laptop connected"
                }
            } catch { await MainActor.run { self.message = "Laptop found, service unavailable" } }
        }
    }
    func netServiceBrowser(_ browser: NetServiceBrowser, didRemove service: NetService, moreComing: Bool) {
        services.removeAll { $0 == service }
        if services.isEmpty && !manual { backend = nil; message = "Laptop not found" }
    }
    func netServiceBrowser(_ browser: NetServiceBrowser, didNotSearch errorDict: [String: NSNumber]) {
        message = "Discovery unavailable. Allow Local Network access or enter the laptop address."
    }
}
