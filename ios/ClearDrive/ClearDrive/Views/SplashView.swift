//
//  SplashView.swift
//  ClearDrive
//
//  Animated launch screen with logo
//

import SwiftUI

struct SplashView: View {
    @State private var isAnimating = false
    @State private var showContent = false
    @State private var logoScale: CGFloat = 0.5
    @State private var logoOpacity: Double = 0
    @State private var glowOpacity: Double = 0
    @State private var textOpacity: Double = 0

    let onComplete: () -> Void

    var body: some View {
        ZStack {
            // Background
            Color.cdBackground
                .ignoresSafeArea()

            // Ambient glow behind logo
            Circle()
                .fill(
                    RadialGradient(
                        colors: [
                            Color.cdPrimary.opacity(0.4),
                            Color.cdPrimary.opacity(0.1),
                            Color.clear
                        ],
                        center: .center,
                        startRadius: 40,
                        endRadius: 200
                    )
                )
                .frame(width: 400, height: 400)
                .opacity(glowOpacity)
                .blur(radius: 30)

            VStack(spacing: CDSpacing.xlarge) {
                // Logo
                Image("Logo")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 120, height: 120)
                    .clipShape(RoundedRectangle(cornerRadius: 28))
                    .shadow(color: Color.cdPrimary.opacity(0.5), radius: 30, y: 10)
                    .scaleEffect(logoScale)
                    .opacity(logoOpacity)

                // App name
                VStack(spacing: CDSpacing.xs) {
                    Text("ClearDrive")
                        .font(.system(size: 32, weight: .bold))
                        .foregroundStyle(Color.cdTextPrimary)

                    Text("AI-Powered Diagnostics")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Color.cdTextTertiary)
                        .tracking(1)
                }
                .opacity(textOpacity)
            }
        }
        .onAppear {
            startAnimation()
        }
    }

    private func startAnimation() {
        // Phase 1: Logo fades in and scales up
        withAnimation(.easeOut(duration: 0.6)) {
            logoOpacity = 1
            logoScale = 1
        }

        // Phase 2: Glow appears
        withAnimation(.easeInOut(duration: 0.8).delay(0.3)) {
            glowOpacity = 1
        }

        // Phase 3: Text fades in
        withAnimation(.easeOut(duration: 0.5).delay(0.5)) {
            textOpacity = 1
        }

        // Phase 4: Complete and transition to main app
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.8) {
            withAnimation(.easeInOut(duration: 0.3)) {
                onComplete()
            }
        }
    }
}

#Preview {
    SplashView(onComplete: {})
}
