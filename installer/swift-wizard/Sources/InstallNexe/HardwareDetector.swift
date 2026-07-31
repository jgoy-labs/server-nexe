// HardwareDetector.swift — Native hardware detection (RAM, chip, Metal, disk)

import Foundation
import Metal

/// Environment variable that simulates a machine's RAM for testing the picker
/// from any Mac. Permanent house tool, not a one-off: the case that decides the
/// wizard's behaviour is a 24 GB Mac (mistral_small_24b needs exactly 18.0 GB
/// against a limit of exactly 18.0), and nobody is going to keep one around.
/// Documented in docs/PROVES-WIZARD.md.
let kSimulatedRamEnvVar = "NEXE_WIZARD_RAM_GB"

/// The ONLY simulable amounts. A closed list, not a range: every entry is a
/// machine worth testing, and anything else is a typo better caught than
/// rounded off.
///  * 24 is mandatory — it is the zero-margin tier (mistral_small_24b needs
///    exactly 18.0 GB against a limit of exactly 18.0), the most critical case
///    of the smoke test, and real hardware: the MacBook Air M2/M3 and the Mac
///    mini ship with 24 GB.
///  * 32 and 64 are the two sides of alia_40b's frontier (32 × 0.75 = 24 →
///    greyed out, 64 × 0.75 = 48 → active).
///  * 128 is the ceiling: above it `ramTier` saturates at tier_32 anyway, so
///    simulating more buys nothing.
let kSimulatableRamGB: [Int] = [8, 16, 24, 32, 64, 96, 128]

struct HardwareInfo {
    let ramGB: Int
    let isAppleSilicon: Bool
    let hasMetal: Bool
    let chipModel: String
    let diskFreeGB: Int
    let diskTotalGB: Int
    /// The machine's REAL RAM when `ramGB` is simulated; `nil` on a normal run.
    /// Anything non-nil means the wizard is lying about the hardware on purpose
    /// and the UI must say so — this installer picks models by RAM, so a
    /// simulated run left unnoticed can install a model the Mac cannot hold.
    /// Defaults to nil so the other construction sites (InstallerEngine) stay
    /// untouched: no override unless someone asks for one.
    var simulatedFromRealGB: Int? = nil

    /// Recommended RAM tier — 4 active tiers (tier_48/tier_64 removed from the catalog)
    var ramTier: String {
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
        let realRamGB = Int(ramBytes / (1024 * 1024 * 1024))

        // Test override: only the SOURCE of the number changes. Everything
        // downstream (tier, filter, recommendation) runs untouched, so a
        // simulated run exercises the real code path.
        var ramGB = realRamGB
        var simulatedFromRealGB: Int? = nil
        if let raw = ProcessInfo.processInfo.environment[kSimulatedRamEnvVar] {
            let trimmed = raw.trimmingCharacters(in: .whitespaces)
            guard let simulated = Int(trimmed),
                  kSimulatableRamGB.contains(simulated) else {
                // Present but not valid: refuse loudly BEFORE any window opens.
                // Rounding to the nearest tier, or silently falling back to the
                // real RAM, would leave someone testing a machine they did not
                // ask for — and this wizard installs models by RAM.
                let valid = kSimulatableRamGB.map(String.init).joined(separator: ", ")
                let message = "\n" + kSimulatedRamEnvVar + "=" + trimmed
                    + " no és un valor simulable.\n"
                    + "Valors vàlids: " + valid + ".\n"
                    + "Sense la variable, el wizard llegeix la RAM real de la màquina.\n\n"
                FileHandle.standardError.write(Data(message.utf8))
                exit(2)
            }
            ramGB = simulated
            simulatedFromRealGB = realRamGB
        }

        // Architecture
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

        // Disk
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
            diskTotalGB: diskTotalGB,
            simulatedFromRealGB: simulatedFromRealGB
        )
    }
}

// Extension to get the architecture name
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
