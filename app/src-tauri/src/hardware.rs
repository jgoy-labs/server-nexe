//! F5.3: Hardware detection Tauri command for the onboarding wizard.
//!
//! Provides RAM, OS, Apple Silicon flag and free disk space without
//! requiring the sidecar to be running — Steps 0-2 work fully offline.

use serde::Serialize;
use sysinfo::{Disks, System};

/// Hardware summary returned to the onboarding frontend.
#[derive(Debug, Serialize)]
pub struct HardwareInfo {
    /// Total physical RAM in GB.
    pub ram_gb: u64,
    /// Long OS version string (e.g. "macOS 15.4").
    pub os: String,
    /// True when running on Apple Silicon (aarch64 + macOS).
    pub is_apple_silicon: bool,
    /// CPU architecture string (e.g. "aarch64", "x86_64").
    pub machine: String,
    /// Free disk space on the root partition, in GB.
    pub disk_free_gb: u64,
}

/// Return hardware information for the onboarding wizard.
///
/// Called via `invoke("get_hardware")` from the frontend (Step 2).
/// Does not require the sidecar.
#[tauri::command]
pub fn get_hardware() -> HardwareInfo {
    let mut sys = System::new_all();
    sys.refresh_memory();

    let ram_gb = sys.total_memory() / (1024 * 1024 * 1024);
    let os = System::long_os_version().unwrap_or_default();
    let machine = System::cpu_arch();
    let is_apple_silicon = cfg!(target_arch = "aarch64") && cfg!(target_os = "macos");

    let disks = Disks::new_with_refreshed_list();
    let disk_free_gb = disks
        .iter()
        .find(|d| d.mount_point() == std::path::Path::new("/"))
        .map(|d| d.available_space() / (1024 * 1024 * 1024))
        .unwrap_or(0);

    HardwareInfo {
        ram_gb,
        os,
        is_apple_silicon,
        machine,
        disk_free_gb,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn get_hardware_returns_nonzero_ram() {
        let hw = get_hardware();
        assert!(hw.ram_gb > 0, "RAM should be > 0 GB, got {}", hw.ram_gb);
    }

    #[test]
    fn get_hardware_machine_not_empty() {
        let hw = get_hardware();
        assert!(!hw.machine.is_empty(), "machine string should not be empty");
    }

    #[test]
    fn get_hardware_os_not_empty() {
        let hw = get_hardware();
        assert!(!hw.os.is_empty(), "OS string should not be empty");
    }

    #[test]
    fn get_hardware_apple_silicon_consistent() {
        let hw = get_hardware();
        // On non-macOS/non-aarch64 builds this must be false.
        if cfg!(not(all(target_arch = "aarch64", target_os = "macos"))) {
            assert!(!hw.is_apple_silicon);
        }
    }
}
