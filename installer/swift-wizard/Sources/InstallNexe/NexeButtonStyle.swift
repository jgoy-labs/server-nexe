// NexeButtonStyle.swift — Button style consistent across the whole wizard.
//
// Replaces `.buttonStyle(.borderedProminent)`, which macOS turns
// transparent when the window loses focus (only the text appears, without
// a red background). This looks as if the button disappeared.
//
// NexePrimaryButtonStyle always paints the background explicitly, independent
// of the window's focus state.
//
// Usage:
//   Button("Next") { ... }
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
    /// Applies the primary button (Nexe red) with an always-visible background.
    func nexePrimaryButton() -> some View {
        buttonStyle(NexePrimaryButtonStyle())
    }
}
