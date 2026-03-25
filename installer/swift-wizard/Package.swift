// swift-tools-version:5.9
// Package.swift — SwiftUI Wizard per instal·lar server-nexe

import PackageDescription

let package = Package(
    name: "InstallNexe",
    platforms: [
        .macOS(.v13)
    ],
    targets: [
        .executableTarget(
            name: "InstallNexe",
            path: "Sources/InstallNexe"
        )
    ]
)
