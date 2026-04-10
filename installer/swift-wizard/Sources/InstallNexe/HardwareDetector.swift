// HardwareDetector.swift — Detecció de hardware natiu (RAM, chip, Metal, disc)

import Foundation
import Metal

struct HardwareInfo {
    let ramGB: Int
    let isAppleSilicon: Bool
    let hasMetal: Bool
    let chipModel: String
    let diskFreeGB: Int
    let diskTotalGB: Int

    /// Tier de RAM recomanat — 6 tiers, regla del 25% (mateixa lògica que installer_hardware.py)
    var ramTier: String {
        if ramGB >= 64  { return "tier_64" }
        if ramGB >= 48  { return "tier_48" }
        if ramGB >= 32  { return "tier_32" }
        if ramGB >= 24  { return "tier_24" }
        if ramGB >= 16  { return "tier_16" }
        return "tier_8"
    }

    static func detect() -> HardwareInfo {
        // RAM via sysctl
        var ramBytes: UInt64 = 0
        var size = MemoryLayout<UInt64>.size
        sysctlbyname("hw.memsize", &ramBytes, &size, nil, 0)
        let ramGB = Int(ramBytes / (1024 * 1024 * 1024))

        // Arquitectura
        let machine = ProcessInfo.processInfo.machineHardwareName
        let isAppleSilicon = machine == "arm64"

        // Chip model
        var chipModel = "Unknown"
        var chipSize = 0
        sysctlbyname("machdep.cpu.brand_string", nil, &chipSize, nil, 0)
        if chipSize > 0 {
            var chipBuffer = [CChar](repeating: 0, count: chipSize)
            sysctlbyname("machdep.cpu.brand_string", &chipBuffer, &chipSize, nil, 0)
            chipModel = String(cString: chipBuffer)
        }

        // Metal GPU
        let hasMetal = MTLCreateSystemDefaultDevice() != nil

        // Disc
        var diskFreeGB = 0
        var diskTotalGB = 0
        if let attrs = try? FileManager.default.attributesOfFileSystem(
            forPath: NSHomeDirectory()
        ) {
            if let free = attrs[.systemFreeSize] as? Int64 {
                diskFreeGB = Int(free / (1024 * 1024 * 1024))
            }
            if let total = attrs[.systemSize] as? Int64 {
                diskTotalGB = Int(total / (1024 * 1024 * 1024))
            }
        }

        return HardwareInfo(
            ramGB: ramGB,
            isAppleSilicon: isAppleSilicon,
            hasMetal: hasMetal,
            chipModel: chipModel,
            diskFreeGB: diskFreeGB,
            diskTotalGB: diskTotalGB
        )
    }
}

// Extension per obtenir el nom de l'arquitectura
extension ProcessInfo {
    var machineHardwareName: String {
        var sysinfo = utsname()
        uname(&sysinfo)
        return withUnsafePointer(to: &sysinfo.machine) {
            $0.withMemoryRebound(to: CChar.self, capacity: 1) {
                String(cString: $0)
            }
        }
    }
}
