//
//  Theme.swift
//  ClearDrive
//
//  Luxury automotive design system - Tesla/BMW inspired
//  Dark pine green with sophisticated grays
//

import SwiftUI

// MARK: - Colors

extension Color {
    // Primary brand - Forest green (matched to logo #2D4A3E)
    static let cdPrimary = Color(hex: "2D4A3E")
    static let cdPrimaryLight = Color(hex: "3D6A54")
    static let cdPrimaryBright = Color(hex: "4A9B6F")
    static let cdAccent = Color(hex: "7FCFA3")  // Soft mint accent

    // Backgrounds - Rich dark grays with subtle warmth
    static let cdBackground = Color(hex: "0A0C0B")
    static let cdBackgroundElevated = Color(hex: "121614")
    static let cdCardBackground = Color(hex: "1A1E1C")
    static let cdCardBackgroundLight = Color(hex: "242A27")

    // Text hierarchy
    static let cdTextPrimary = Color(hex: "F5F7F6")
    static let cdTextSecondary = Color(hex: "9CA3A0")
    static let cdTextTertiary = Color(hex: "5C6360")

    // Status colors - Muted luxury palette
    static let cdSuccess = Color(hex: "4A9B6F")
    static let cdWarning = Color(hex: "D4A84B")
    static let cdCritical = Color(hex: "CF6B6B")

    // Glow/highlight
    static let cdGlow = Color(hex: "4A9B6F")

    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch hex.count {
        case 3:
            (a, r, g, b) = (255, (int >> 8) * 17, (int >> 4 & 0xF) * 17, (int & 0xF) * 17)
        case 6:
            (a, r, g, b) = (255, int >> 16, int >> 8 & 0xFF, int & 0xFF)
        case 8:
            (a, r, g, b) = (int >> 24, int >> 16 & 0xFF, int >> 8 & 0xFF, int & 0xFF)
        default:
            (a, r, g, b) = (1, 1, 1, 0)
        }
        self.init(
            .sRGB,
            red: Double(r) / 255,
            green: Double(g) / 255,
            blue: Double(b) / 255,
            opacity: Double(a) / 255
        )
    }
}

// MARK: - Gradients

extension LinearGradient {
    static let cdBackgroundGradient = LinearGradient(
        colors: [
            Color(hex: "0F1311"),
            Color(hex: "0A0C0B")
        ],
        startPoint: .top,
        endPoint: .bottom
    )

    static let cdCardGradient = LinearGradient(
        colors: [
            Color(hex: "1E2422"),
            Color(hex: "1A1E1C")
        ],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    static let cdPrimaryGradient = LinearGradient(
        colors: [Color.cdPrimaryBright, Color.cdPrimary],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    static let cdSubtleGlow = LinearGradient(
        colors: [
            Color.cdPrimaryBright.opacity(0.15),
            Color.clear
        ],
        startPoint: .top,
        endPoint: .bottom
    )

    // Glass-like gradients
    static let cdGlassGradient = LinearGradient(
        colors: [
            Color.white.opacity(0.12),
            Color.white.opacity(0.05),
            Color.clear
        ],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    static let cdGlassBorder = LinearGradient(
        colors: [
            Color.white.opacity(0.25),
            Color.white.opacity(0.08),
            Color.white.opacity(0.03)
        ],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    static let cdCardGradientElevated = LinearGradient(
        colors: [
            Color(hex: "252B28"),
            Color(hex: "1A1E1C"),
            Color(hex: "151917")
        ],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
}

// MARK: - Glass Card Style (Apple-inspired)

struct GlassCard<Content: View>: View {
    let content: Content
    var padding: CGFloat = CDSpacing.medium
    var cornerRadius: CGFloat = 20

    init(padding: CGFloat = CDSpacing.medium, cornerRadius: CGFloat = 20, @ViewBuilder content: () -> Content) {
        self.padding = padding
        self.cornerRadius = cornerRadius
        self.content = content()
    }

    var body: some View {
        content
            .padding(padding)
            .background(
                ZStack {
                    // Base layer with gradient
                    RoundedRectangle(cornerRadius: cornerRadius)
                        .fill(LinearGradient.cdCardGradientElevated)

                    // Glass highlight overlay
                    RoundedRectangle(cornerRadius: cornerRadius)
                        .fill(LinearGradient.cdGlassGradient)

                    // Subtle inner glow at top
                    RoundedRectangle(cornerRadius: cornerRadius)
                        .fill(
                            LinearGradient(
                                colors: [
                                    Color.cdPrimaryBright.opacity(0.08),
                                    Color.clear
                                ],
                                startPoint: .top,
                                endPoint: .center
                            )
                        )
                }
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius)
                    .stroke(LinearGradient.cdGlassBorder, lineWidth: 1)
            )
            .shadow(color: Color.black.opacity(0.3), radius: 10, y: 5)
    }
}

// MARK: - Spacing

enum CDSpacing {
    static let xs: CGFloat = 4
    static let small: CGFloat = 8
    static let medium: CGFloat = 16
    static let large: CGFloat = 24
    static let xlarge: CGFloat = 32
    static let xxlarge: CGFloat = 48
}

// MARK: - Luxury Card Style

struct LuxuryCard<Content: View>: View {
    let content: Content
    var padding: CGFloat = CDSpacing.medium

    init(padding: CGFloat = CDSpacing.medium, @ViewBuilder content: () -> Content) {
        self.padding = padding
        self.content = content()
    }

    var body: some View {
        content
            .padding(padding)
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(Color.cdCardBackground)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16)
                            .stroke(
                                LinearGradient(
                                    colors: [
                                        Color.cdPrimary.opacity(0.3),
                                        Color.cdPrimary.opacity(0.05)
                                    ],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                ),
                                lineWidth: 1
                            )
                    )
            )
    }
}

// MARK: - Glowing Arc Background

struct GlowingArc: View {
    var color: Color = .cdPrimaryBright
    var intensity: Double = 1.0

    var body: some View {
        ZStack {
            // Outer ambient glow
            Ellipse()
                .fill(
                    RadialGradient(
                        colors: [
                            color.opacity(0.3 * intensity),
                            color.opacity(0.1 * intensity),
                            Color.clear
                        ],
                        center: .center,
                        startRadius: 20,
                        endRadius: 180
                    )
                )
                .frame(width: 360, height: 200)
                .blur(radius: 40)

            // Inner bright core
            Ellipse()
                .fill(
                    RadialGradient(
                        colors: [
                            color.opacity(0.5 * intensity),
                            color.opacity(0.2 * intensity),
                            Color.clear
                        ],
                        center: .center,
                        startRadius: 10,
                        endRadius: 100
                    )
                )
                .frame(width: 200, height: 100)
                .blur(radius: 25)
        }
    }
}

// MARK: - Safety Rating

enum SafetyRating: String, CaseIterable, Codable {
    case safe
    case caution
    case critical

    init(from string: String) {
        switch string.uppercased() {
        case "SAFE", "GREEN", "OK":
            self = .safe
        case "CAUTION", "YELLOW", "WARNING":
            self = .caution
        case "CRITICAL", "RED", "STOP", "DANGER":
            self = .critical
        default:
            self = .safe
        }
    }

    var label: String {
        switch self {
        case .safe: return "Safe to Drive"
        case .caution: return "Schedule Service"
        case .critical: return "Immediate Attention"
        }
    }

    var icon: String {
        switch self {
        case .safe: return "checkmark.circle.fill"
        case .caution: return "exclamationmark.triangle.fill"
        case .critical: return "xmark.octagon.fill"
        }
    }

    var color: Color {
        switch self {
        case .safe: return .cdSuccess
        case .caution: return .cdWarning
        case .critical: return .cdCritical
        }
    }
}

// MARK: - Luxury Button

struct LuxuryButton: View {
    let title: String
    let icon: String?
    var isLoading: Bool = false
    var style: ButtonStyle = .primary
    let action: () -> Void

    enum ButtonStyle {
        case primary, secondary
    }

    init(_ title: String, icon: String? = nil, isLoading: Bool = false, style: ButtonStyle = .primary, action: @escaping () -> Void) {
        self.title = title
        self.icon = icon
        self.isLoading = isLoading
        self.style = style
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: CDSpacing.small) {
                if isLoading {
                    ProgressView()
                        .tint(style == .primary ? .white : .cdTextPrimary)
                        .scaleEffect(0.9)
                } else {
                    if let icon = icon {
                        Image(systemName: icon)
                            .font(.system(size: 16, weight: .semibold))
                    }
                    Text(title)
                        .font(.system(size: 16, weight: .semibold))
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 54)
            .background(
                ZStack {
                    if style == .primary {
                        // Rich gradient for primary button
                        LinearGradient(
                            colors: [
                                Color.cdPrimaryBright,
                                Color.cdPrimary,
                                Color(hex: "1E3D2F")
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                        // Glass highlight at top
                        LinearGradient(
                            colors: [
                                Color.white.opacity(0.2),
                                Color.white.opacity(0.05),
                                Color.clear
                            ],
                            startPoint: .top,
                            endPoint: .center
                        )
                    } else {
                        LinearGradient.cdCardGradientElevated
                        LinearGradient.cdGlassGradient
                    }
                }
            )
            .foregroundStyle(style == .primary ? .white : .cdTextPrimary)
            .clipShape(RoundedRectangle(cornerRadius: 14))
            .overlay(
                RoundedRectangle(cornerRadius: 14)
                    .stroke(
                        style == .primary
                            ? LinearGradient(
                                colors: [Color.white.opacity(0.3), Color.cdPrimaryBright.opacity(0.3), Color.clear],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                              )
                            : LinearGradient.cdGlassBorder,
                        lineWidth: style == .primary ? 1 : 0.5
                    )
            )
            .shadow(
                color: style == .primary ? Color.cdPrimaryBright.opacity(0.4) : Color.clear,
                radius: 12,
                y: 4
            )
        }
        .disabled(isLoading)
    }
}

// MARK: - Stat Display

struct StatDisplay: View {
    let value: String
    let label: String
    let icon: String

    var body: some View {
        VStack(spacing: CDSpacing.small) {
            Image(systemName: icon)
                .font(.system(size: 18))
                .foregroundStyle(
                    LinearGradient(
                        colors: [Color.cdPrimaryBright, Color.cdPrimary],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )

            Text(value)
                .font(.system(size: 24, weight: .bold, design: .rounded))
                .foregroundStyle(Color.cdTextPrimary)

            Text(label)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Color.cdTextTertiary)
                .textCase(.uppercase)
                .tracking(0.5)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CDSpacing.medium)
        .background(
            ZStack {
                RoundedRectangle(cornerRadius: 14)
                    .fill(LinearGradient.cdCardGradientElevated)
                RoundedRectangle(cornerRadius: 14)
                    .fill(LinearGradient.cdGlassGradient)
            }
        )
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(LinearGradient.cdGlassBorder, lineWidth: 1)
        )
    }
}

// MARK: - Section Header

struct SectionHeader: View {
    let title: String
    var trailing: String? = nil

    var body: some View {
        HStack {
            Text(title)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Color.cdTextTertiary)
                .textCase(.uppercase)
                .tracking(1)

            Spacer()

            if let trailing = trailing {
                Text(trailing)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Color.cdPrimaryBright)
            }
        }
    }
}

// MARK: - Animated Glow Modifier

struct PulsingGlow: ViewModifier {
    let color: Color
    @State private var isAnimating = false

    func body(content: Content) -> some View {
        content
            .shadow(color: color.opacity(isAnimating ? 0.6 : 0.3), radius: isAnimating ? 20 : 10)
            .onAppear {
                withAnimation(.easeInOut(duration: 2).repeatForever(autoreverses: true)) {
                    isAnimating = true
                }
            }
    }
}

extension View {
    func pulsingGlow(color: Color = .cdPrimaryBright) -> some View {
        modifier(PulsingGlow(color: color))
    }
}

// MARK: - Legacy Support

struct PrimaryButton: View {
    let title: String
    var isLoading: Bool = false
    let action: () -> Void

    var body: some View {
        LuxuryButton(title, isLoading: isLoading, action: action)
    }
}

struct CircularGauge: View {
    let value: Double
    let label: String
    let unit: String
    var displayValue: String
    var color: Color = .cdPrimaryBright
    var size: CGFloat = 80

    init(value: Double, label: String, displayValue: String, unit: String = "", color: Color = .cdPrimaryBright, size: CGFloat = 80) {
        self.value = value
        self.label = label
        self.displayValue = displayValue
        self.unit = unit
        self.color = color
        self.size = size
    }

    var body: some View {
        VStack(spacing: CDSpacing.small) {
            ZStack {
                Circle()
                    .stroke(Color.cdCardBackgroundLight, lineWidth: 4)
                    .frame(width: size, height: size)

                Circle()
                    .trim(from: 0, to: value)
                    .stroke(color, style: StrokeStyle(lineWidth: 4, lineCap: .round))
                    .frame(width: size, height: size)
                    .rotationEffect(.degrees(-90))

                VStack(spacing: 0) {
                    Text(displayValue)
                        .font(.system(size: size * 0.25, weight: .bold, design: .rounded))
                    if !unit.isEmpty {
                        Text(unit)
                            .font(.system(size: size * 0.12))
                            .foregroundStyle(Color.cdTextSecondary)
                    }
                }
            }

            Text(label)
                .font(.caption2)
                .foregroundStyle(Color.cdTextSecondary)
        }
    }
}

struct MetricTile: View {
    let icon: String
    let label: String
    let value: String
    var status: MetricStatus = .normal

    enum MetricStatus {
        case normal, warning, critical
        var color: Color {
            switch self {
            case .normal: return .cdTextPrimary
            case .warning: return .cdWarning
            case .critical: return .cdCritical
            }
        }
    }

    var body: some View {
        StatDisplay(value: value, label: label, icon: icon)
    }
}

struct IconButton: View {
    let icon: String
    var size: CGFloat = 44
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 16, weight: .medium))
                .foregroundStyle(Color.cdTextPrimary)
                .frame(width: size, height: size)
                .background(Color.cdCardBackground)
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }
}

