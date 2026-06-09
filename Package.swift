
// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "SandStories",
    platforms: [
        .iOS(.v17),
        .macOS(.v14),
    ],
    products: [
        // An xtool project should contain exactly one library product,
        // representing the main app.
        .library(
            name: "SandStories",
            targets: ["SandStories"]
        ),
    ],
    dependencies: [
        .package(url: "https://github.com/livekit/client-sdk-swift.git", exact: "2.5.0"),
    ],
    targets: [
        .target(
            name: "SandStories",
            dependencies: [
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
    ]
)
