//
//  CDCard.swift
//  ClearDrive
//
//  Reusable card and UI components
//

import SwiftUI

// MARK: - Card

struct CDCard<Content: View>: View {
    let content: Content
    var style: CardStyle = .standard

    enum CardStyle {
        case standard
        case elevated
        case glowing
    }

    init(style: CardStyle = .standard, @ViewBuilder content: () -> Content) {
        self.style = style
        self.content = content()
    }

    var body: some View {
        content
            .padding(CDSpacing.medium)
            .background(Color.cdCardBackground)
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .shadow(
                color: style == .elevated ? Color.black.opacity(0.3) : Color.clear,
                radius: 10,
                y: 4
            )
    }
}

// MARK: - Card Header

struct CDCardHeader: View {
    let title: String
    var icon: String? = nil

    var body: some View {
        HStack(spacing: CDSpacing.small) {
            if let icon = icon {
                Image(systemName: icon)
                    .foregroundStyle(Color.cdTextSecondary)
            }
            Text(title.uppercased())
                .font(.caption)
                .fontWeight(.semibold)
                .foregroundStyle(Color.cdTextSecondary)
            Spacer()
        }
    }
}

// MARK: - Button

struct CDButton: View {
    let title: String
    var icon: String? = nil
    var style: ButtonStyle = .primary
    var isLoading: Bool = false
    let action: () -> Void

    enum ButtonStyle {
        case primary
        case secondary
        case destructive

        var backgroundColor: Color {
            switch self {
            case .primary: return .cdPrimary
            case .secondary: return .cdCardBackground
            case .destructive: return .cdCritical
            }
        }

        var foregroundColor: Color {
            switch self {
            case .primary: return .white
            case .secondary: return .cdTextPrimary
            case .destructive: return .white
            }
        }
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: CDSpacing.small) {
                if isLoading {
                    ProgressView()
                        .tint(style.foregroundColor)
                } else if let icon = icon {
                    Image(systemName: icon)
                }
                Text(title)
                    .fontWeight(.semibold)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .background(style.backgroundColor)
            .foregroundStyle(style.foregroundColor)
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .disabled(isLoading)
    }
}

// MARK: - Text Field

struct CDTextField: View {
    let title: String
    @Binding var text: String
    var placeholder: String = ""
    var keyboardType: UIKeyboardType = .default

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased())
                .font(.caption2)
                .foregroundStyle(Color.cdTextSecondary)

            TextField(placeholder, text: $text)
                .textFieldStyle(.plain)
                .padding(12)
                .background(Color.cdCardBackground)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .keyboardType(keyboardType)
        }
    }
}

// MARK: - Status Badge

struct CDStatusBadge: View {
    let status: OBDConnectionStatus

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(status.color)
                .frame(width: 8, height: 8)
            Text(status.label)
                .font(.caption)
                .foregroundStyle(status.color)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(status.color.opacity(0.15))
        .clipShape(Capsule())
    }
}

// MARK: - Safety Badge

struct CDSafetyBadge: View {
    let rating: SafetyRating

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: rating.icon)
            Text(rating.label)
                .fontWeight(.medium)
        }
        .font(.subheadline)
        .foregroundStyle(rating.color)
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(rating.color.opacity(0.15))
        .clipShape(Capsule())
    }
}

#Preview {
    VStack(spacing: 20) {
        CDCard {
            VStack(alignment: .leading, spacing: 12) {
                CDCardHeader(title: "Vehicle Info", icon: "car.fill")
                Text("2014 Toyota Land Cruiser")
                    .font(.headline)
            }
        }

        CDButton(title: "Scan Vehicle", icon: "magnifyingglass", action: {})
        CDButton(title: "Cancel", style: .secondary, action: {})

        CDTextField(title: "Year", text: .constant("2014"), placeholder: "2020")

        CDStatusBadge(status: .connected)
        CDStatusBadge(status: .disconnected)

        CDSafetyBadge(rating: .safe)
        CDSafetyBadge(rating: .caution)
        CDSafetyBadge(rating: .critical)
    }
    .padding()
    .background(Color.cdBackground)
    .preferredColorScheme(.dark)
}
