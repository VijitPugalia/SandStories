
// swift-tools-version: 6.2

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
    targets: [
        .target(
            name: "SandStories",
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
