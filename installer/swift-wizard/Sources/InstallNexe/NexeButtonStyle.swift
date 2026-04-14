// NexeButtonStyle.swift — Button style consistent per tot el wizard.
//
// Substitueix `.buttonStyle(.borderedProminent)` que macOS converteix en
// transparent quan la finestra perd el focus (apareix només el text, sense
// fons vermell). Això es veu com si el botó desaparegués.
//
// NexePrimaryButtonStyle pinta sempre el fons explícitament, independent
// de l'estat de focus de la finestra.
//
// Ús:
//   Button("Següent") { ... }
//       .nexePrimaryButton()
//       .disabled(!canContinue)

import SwiftUI

struct NexePrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .foregroundColor(.white)
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .frame(minHeight: 24)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(backgroundColor(pressed: configuration.isPressed))
            )
            .opacity(isEnabled ? 1.0 : 0.6)
    }

    private func backgroundColor(pressed: Bool) -> Color {
        if !isEnabled { return Color.nexeRed.opacity(0.4) }
        return pressed ? Color.nexeRed.opacity(0.85) : Color.nexeRed
    }
}

extension View {
    /// Aplica el botó primari (vermell Nexe) amb fons sempre visible.
    func nexePrimaryButton() -> some View {
        buttonStyle(NexePrimaryButtonStyle())
    }
}
