// InstallNexeApp.swift — Punt d'entrada de l'aplicació SwiftUI
// Wizard natiu per instal·lar server-nexe a macOS

import SwiftUI

@main
struct InstallNexeApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var engine = InstallerEngine()

    var body: some Scene {
        WindowGroup {
            InstallerWizardView()
                .environmentObject(engine)
                .frame(minWidth: 800, minHeight: 580)
                .frame(width: 880, height: 620)
                .preferredColorScheme(engine.darkMode ? .dark : .light)
                .background(WindowCloseInterceptor(engine: engine))
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
    }
}

/// Evitar que el procés quedi viu en background quan es tanca la finestra.
/// Sense això, si l'usuari ejecta el DMG, el procés fa SIGBUS (KERN_MEMORY_ERROR)
/// perquè el kernel no pot servir pàgines del volum desmuntat.
class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

/// NSViewRepresentable que intercepta el botó vermell de la finestra
struct WindowCloseInterceptor: NSViewRepresentable {
    let engine: InstallerEngine

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            guard let window = view.window else { return }
            window.delegate = context.coordinator
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(engine: engine)
    }

    @MainActor
    class Coordinator: NSObject, NSWindowDelegate {
        let engine: InstallerEngine

        init(engine: InstallerEngine) {
            self.engine = engine
        }

        func windowShouldClose(_ sender: NSWindow) -> Bool {
            // Si ja ha acabat, tancar directament
            if engine.installFinished { return true }

            // Preguntar sempre
            let alert = NSAlert()
            alert.messageText = T.get("cancel_title", lang: engine.lang)
            alert.informativeText = T.get("cancel_message", lang: engine.lang)
            alert.alertStyle = .warning
            alert.addButton(withTitle: T.get("cancel_continue", lang: engine.lang))
            alert.addButton(withTitle: T.get("cancel_quit", lang: engine.lang))

            let response = alert.runModal()
            if response == .alertSecondButtonReturn {
                engine.cancelInstall()
                NSApplication.shared.terminate(nil)
                return true
            }
            return false
        }
    }
}
