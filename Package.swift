// swift-tools-version: 6.0

import Foundation
import PackageDescription

let gestureTestsOnly = ProcessInfo.processInfo.environment["SANDSTORIES_GESTURE_TESTS_ONLY"] == "1"

let products: [Product] = gestureTestsOnly
    ? [
        .library(
            name: "GestureRecognition",
            targets: ["GestureRecognition"]
        ),
    ]
    : [
        // An xtool project should contain exactly one library product,
        // representing the main app.
        .library(
            name: "SandStories",
            targets: ["SandStories"]
        ),
    ]

let dependencies: [Package.Dependency] = gestureTestsOnly
    ? []
    : [
        .package(url: "https://github.com/livekit/client-sdk-swift.git", exact: "2.15.3"),
    ]

let targets: [Target] = gestureTestsOnly
    ? [
        .target(name: "GestureRecognition"),
        .testTarget(
            name: "GestureRecognitionTests",
            dependencies: ["GestureRecognition"]
        ),
    ]
    : [
        .target(name: "GestureRecognition"),
        .target(
            name: "SandStories",
            dependencies: [
                "GestureRecognition",
                .product(name: "LiveKit", package: "client-sdk-swift"),
            ],
            linkerSettings: [
                .linkedFramework("ARKit", .when(platforms: [.iOS])),
                .linkedFramework("RealityKit", .when(platforms: [.iOS])),
                .linkedFramework("CoreLocation", .when(platforms: [.iOS])),
                .linkedFramework("Vision", .when(platforms: [.iOS])),
                .linkedFramework("AVFoundation", .when(platforms: [.iOS])),
            ]
        ),
        .testTarget(
            name: "GestureRecognitionTests",
            dependencies: ["GestureRecognition"]
        ),
    ]

let package = Package(
    name: "SandStories",
    platforms: [
        .iOS(.v17),
        .macOS(.v14),
    ],
    products: products,
    dependencies: dependencies,
    targets: targets
)
