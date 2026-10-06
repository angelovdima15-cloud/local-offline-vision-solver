import SwiftUI
import UIKit

struct ContentView: View {
    @StateObject private var camera = CameraController()
    @StateObject private var discovery = BackendDiscovery()
    @StateObject private var controller = TaskController()
    @StateObject private var relay = WatchRelay()
    @Environment(\.scenePhase) private var scenePhase
    @State private var cameraVisible = true
    @State private var settingsVisible = false
    @State private var manualAddress = ""
    @State private var showText = false

    var body: some View {
        NavigationStack {
            Group {
                if let data = camera.captured, let photo = UIImage(data: data) {
                    VStack {
                        Image(uiImage: photo).resizable().scaledToFit().frame(maxWidth: .infinity, maxHeight: .infinity)
                        HStack {
                            Button("Retake") { camera.captured = nil; camera.start() }
                            Spacer()
                            Button("Use Photo") {
                                controller.add(data)
                                if controller.error == nil { camera.captured = nil; cameraVisible = false; camera.stop() }
                            }.buttonStyle(.borderedProminent)
                        }.padding()
                    }
                } else if let answer = controller.answer {
                    result(answer)
                } else if controller.busy {
                    VStack(spacing: 24) {
                        ProgressView().controlSize(.large)
                        Text(controller.stage).font(.title2)
                        Text("Keep the iPhone app open while uploading. If interrupted, reopen it to resume.")
                            .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }.padding()
                } else if cameraVisible && !controller.task.submitted {
                    ZStack(alignment: .bottom) {
                        CameraPreview(camera: camera).ignoresSafeArea(edges: .bottom)
                        VStack {
                            if let error = camera.error { Text(error).padding().background(.ultraThinMaterial) }
                            Text(camera.lensName + " · tap page to focus").padding(8).background(.ultraThinMaterial)
                            HStack {
                                if !controller.task.pages.isEmpty { Button("Pages") { cameraVisible = false; camera.stop() } }
                                Spacer()
                                Button(action: camera.capture) {
                                    Image(systemName: "circle.inset.filled").font(.system(size: 66)).foregroundStyle(.white)
                                }.disabled(!camera.ready || camera.takingPhoto)
                                Spacer()
                            }.padding()
                        }
                    }.onAppear { camera.start() }
                } else { pages }
            }
            .navigationTitle(controller.task.pages.isEmpty ? "Capture task" : "Local Vision Solver")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { settingsVisible = true } label: {
                        Image(systemName: discovery.backend == nil ? "wifi.exclamationmark" : "wifi")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("New Task") { controller.newTask(); cameraVisible = true; camera.captured = nil; camera.start() }
                        .disabled(controller.busy)
                }
            }
            .safeAreaInset(edge: .bottom) {
                if let error = controller.error {
                    Text(error).font(.callout).foregroundStyle(.red).padding().frame(maxWidth: .infinity).background(.regularMaterial)
                }
            }
            .sheet(isPresented: $settingsVisible) { settings }
            .sheet(isPresented: $showText) {
                NavigationStack { ScrollView { Text(controller.answer?.plain_text_answer ?? "").textSelection(.enabled).padding() }
                    .navigationTitle("Full answer").toolbar { Button("Done") { showText = false } } }
            }
            .onAppear {
                discovery.start()
                if !controller.task.pages.isEmpty { cameraVisible = false }
                controller.resume(discovery.backend, relay: relay)
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active {
                    relay.flush(); controller.resume(discovery.backend, relay: relay)
                    if cameraVisible && controller.answer == nil { camera.start() }
                } else { camera.stop(); controller.pause() }
            }
        }
    }

    private var pages: some View {
        VStack {
            Text(discovery.message).font(.caption).foregroundStyle(.secondary)
            List {
                ForEach(Array(controller.task.pages.enumerated()), id: \.element.id) { index, page in
                    HStack {
                        if let image = UIImage(contentsOfFile: controller.pageURL(page).path) {
                            Image(uiImage: image).resizable().scaledToFit().frame(width: 64, height: 84)
                        }
                        Text("Page \(index + 1)")
                        Spacer(); Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                    }
                }.onDelete(perform: controller.remove).onMove(perform: controller.move)
            }.environment(\.editMode, .constant(controller.task.submitted ? .inactive : .active))
            if !controller.task.submitted {
                Button("Add Page") { cameraVisible = true; camera.start() }
                    .buttonStyle(.bordered).disabled(controller.task.pages.count >= 12)
            }
            if controller.backendFailed {
                Button("Edit / retake pages") { controller.newTask(keepPages: true); cameraVisible = false }
                    .buttonStyle(.bordered)
            }
            Button(controller.task.submitted ? "Resume / Retry" : "Solve") { controller.submit(discovery.backend, relay: relay) }
                .buttonStyle(.borderedProminent).disabled(controller.task.pages.isEmpty).padding()
        }
    }
    private func result(_ answer: AnswerPackage) -> some View {
        VStack(spacing: 8) {
            if answer.demo { Text("TRANSPORT DEMO · no AI answer").foregroundStyle(.orange).font(.headline) }
            Text(relay.message).font(.caption)
            TabView {
                ForEach(answer.cards) { card in
                    if let url = try? LocalFiles.cardURL(answer.session_id, card), let image = UIImage(contentsOfFile: url.path) {
                        ScrollView { Image(uiImage: image).resizable().scaledToFit() }
                    }
                }
            }.tabViewStyle(.page)
            HStack {
                Button("Full text") { showText = true }
                Spacer(); Button("Retry Watch") { relay.retry() }
            }.padding()
        }.onAppear { camera.stop() }
    }
    private var settings: some View {
        NavigationStack {
            Form {
                Section("Laptop") {
                    Text(discovery.message)
                    Button("Find again") { discovery.retry() }
                }
                Section("Manual fallback") {
                    TextField("192.168.1.20:8765", text: $manualAddress)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    Button("Connect") { Task { await discovery.useManual(manualAddress) } }
                }
                Section("Watch") { Text(relay.message); Button("Retry delivery") { relay.retry() } }
            }.navigationTitle("Connection").toolbar { Button("Done") { settingsVisible = false } }
        }
    }
}
