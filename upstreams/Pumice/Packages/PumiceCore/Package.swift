 // swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "PumiceCore",
    platforms: [
        .iOS(.v18)
    ],
    products: [
        .library(name: "PumiceCore", targets: ["PumiceCore"])
    ],
    dependencies: [
        // Apple's Markdown AST. Used by the .md preview and the .md to
        // PDF converter so both walk the same parse, keeping the
        // preview honest with what gets exported.
        .package(url: "https://github.com/apple/swift-markdown.git", from: "0.6.0")
    ],
    targets: [
        .target(
            name: "PumiceCore",
            dependencies: [
                .product(name: "Markdown", package: "swift-markdown")
            ]
        ),
        .testTarget(name: "PumiceCoreTests", dependencies: ["PumiceCore"])
    ],
    swiftLanguageModes: [.v6]
)
