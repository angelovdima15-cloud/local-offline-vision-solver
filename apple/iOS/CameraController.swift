import AVFoundation
import UIKit
import SwiftUI

final class CameraController: NSObject, ObservableObject, AVCapturePhotoCaptureDelegate {
    let session = AVCaptureSession()
    private let output = AVCapturePhotoOutput()
    private let queue = DispatchQueue(label: "vision.camera")
    private var device: AVCaptureDevice?
    private var configured = false
    @Published var captured: Data?
    @Published var error: String?
    @Published var ready = false
    @Published var takingPhoto = false
    @Published var lensName = "Ultra Wide"

    func start() {
        Task {
            let granted: Bool
            if AVCaptureDevice.authorizationStatus(for: .video) == .authorized { granted = true }
            else { granted = await AVCaptureDevice.requestAccess(for: .video) }
            guard granted else {
                await MainActor.run { self.error = "Allow Camera access in Settings." }; return
            }
            queue.async { self.configureAndStart() }
        }
    }
    func stop() { queue.async { if self.session.isRunning { self.session.stopRunning() } } }

    private func configureAndStart() {
        do {
            if !configured {
                session.beginConfiguration()
                defer { session.commitConfiguration() }
                session.sessionPreset = .photo
                let ultraWide = AVCaptureDevice.default(.builtInUltraWideCamera, for: .video, position: .back)
                guard let camera = ultraWide ?? AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
                    throw BackendError.message("Camera unavailable.")
                }
                device = camera
                let input = try AVCaptureDeviceInput(device: camera)
                guard session.canAddInput(input), session.canAddOutput(output) else {
                    throw BackendError.message("Camera configuration failed.")
                }
                session.addInput(input); session.addOutput(output)
                try camera.lockForConfiguration()
                if camera.isFocusModeSupported(.continuousAutoFocus) { camera.focusMode = .continuousAutoFocus }
                if camera.isExposureModeSupported(.continuousAutoExposure) { camera.exposureMode = .continuousAutoExposure }
                camera.unlockForConfiguration()
                if let maximum = camera.activeFormat.supportedMaxPhotoDimensions.max(by: {
                    Int64($0.width) * Int64($0.height) < Int64($1.width) * Int64($1.height)
                }) { output.maxPhotoDimensions = maximum }
                output.maxPhotoQualityPrioritization = .quality
                configured = true
                DispatchQueue.main.async { self.lensName = ultraWide == nil ? "Wide camera" : "Ultra Wide" }
            }
            if !session.isRunning { session.startRunning() }
            DispatchQueue.main.async { self.ready = true; self.error = nil }
        } catch { DispatchQueue.main.async { self.error = error.localizedDescription } }
    }

    func capture() {
        guard ready, !takingPhoto else { return }
        takingPhoto = true
        queue.async {
            let settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
            settings.maxPhotoDimensions = self.output.maxPhotoDimensions
            settings.photoQualityPrioritization = .quality
            if let connection = self.output.connection(with: .video), connection.isVideoRotationAngleSupported(90) {
                connection.videoRotationAngle = 90 // Portrait UI; JPEG keeps its metadata.
            }
            self.output.capturePhoto(with: settings, delegate: self)
        }
    }
    func focus(_ point: CGPoint) {
        queue.async {
            guard let camera = self.device else { return }
            do {
                try camera.lockForConfiguration(); defer { camera.unlockForConfiguration() }
                if camera.isFocusPointOfInterestSupported { camera.focusPointOfInterest = point }
                if camera.isFocusModeSupported(.autoFocus) { camera.focusMode = .autoFocus }
                if camera.isExposurePointOfInterestSupported { camera.exposurePointOfInterest = point }
                if camera.isExposureModeSupported(.continuousAutoExposure) { camera.exposureMode = .continuousAutoExposure }
            } catch { DispatchQueue.main.async { self.error = error.localizedDescription } }
        }
    }
    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        let data = photo.fileDataRepresentation()
        DispatchQueue.main.async {
            self.takingPhoto = false
            if let error { self.error = error.localizedDescription }
            else if let data { self.captured = data }
            else { self.error = "Photo capture failed. Try again." }
        }
    }
}

final class PreviewUIView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    var preview: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    var onFocus: ((CGPoint) -> Void)?
    override init(frame: CGRect) {
        super.init(frame: frame)
        addGestureRecognizer(UITapGestureRecognizer(target: self, action: #selector(tap(_:))))
    }
    required init?(coder: NSCoder) { fatalError("Use init(frame:)") }
    @objc private func tap(_ gesture: UITapGestureRecognizer) {
        onFocus?(preview.captureDevicePointConverted(fromLayerPoint: gesture.location(in: self)))
    }
}
struct CameraPreview: UIViewRepresentable {
    let camera: CameraController
    func makeUIView(context: Context) -> PreviewUIView {
        let view = PreviewUIView()
        view.preview.session = camera.session; view.preview.videoGravity = .resizeAspectFill
        view.onFocus = camera.focus
        return view
    }
    func updateUIView(_ uiView: PreviewUIView, context: Context) {}
}
