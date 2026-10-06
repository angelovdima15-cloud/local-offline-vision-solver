// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "VisionTransport",
    platforms: [.macOS(.v13), .iOS(.v17), .watchOS(.v10)],
    products: [.library(name: "VisionTransport", targets: ["VisionTransport"])],
    targets: [
        .target(name: "VisionTransport", path: "Shared"),
        .testTarget(name: "VisionTransportTests", dependencies: ["VisionTransport"], path: "Tests",
                    resources: [.copy("Fixtures")])
    ]
)

