//
//  ResultsView.swift
//  ClearDrive
//
//  Post-scan results display - matches VehicleDetailSheet design with follow-up questions
//

import SwiftUI

struct ResultsView: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var apiClient: APIClient
    @AppStorage("useMetricUnits") private var useMetricUnits = false
    let result: ScanResult
    var liveData: LiveOBDData?

    private var units: UnitConverter { UnitConverter(useMetric: useMetricUnits) }

    @State private var chatMessages: [ChatMessage] = []
    @State private var currentQuestion = ""
    @State private var isAskingQuestion = false

    // Feedback state
    @State private var feedbackSubmitted = false
    @State private var selectedFeedback: String? = nil
    @State private var isSubmittingFeedback = false

    var body: some View {
        NavigationStack {
            ZStack {
                // Smooth gradient background (matches VehicleDetailSheet)
                ZStack {
                    Color.cdBackground

                    LinearGradient(
                        stops: [
                            .init(color: Color(hex: "0F1311"), location: 0),
                            .init(color: Color(hex: "0A0D0B"), location: 0.3),
                            .init(color: Color.cdBackground, location: 0.5),
                            .init(color: Color(hex: "080A09"), location: 1.0)
                        ],
                        startPoint: .top,
                        endPoint: .bottom
                    )

                    RadialGradient(
                        stops: [
                            .init(color: result.safetyRating.color.opacity(0.1), location: 0),
                            .init(color: result.safetyRating.color.opacity(0.03), location: 0.4),
                            .init(color: Color.clear, location: 0.7)
                        ],
                        center: .init(x: 0.5, y: 0.15),
                        startRadius: 40,
                        endRadius: 350
                    )
                }
                .ignoresSafeArea()

                ScrollView(showsIndicators: false) {
                    VStack(spacing: CDSpacing.large) {
                        // Vehicle hero with image
                        vehicleHero

                        // Safety status card
                        safetyStatusCard

                        // Vehicle specs (Engine, Transmission, Drive, Fuel)
                        vehicleSpecsSection

                        // Live OBD data at time of scan
                        if result.rpm != nil || result.speed != nil || result.coolantTemp != nil {
                            liveDataSection
                        }

                        // DTC Codes if any
                        if !result.codes.isEmpty {
                            dtcCodesSection
                        }

                        // All diagnostic sections
                        diagnosticCardsSection

                        // Follow-up questions
                        followUpCard

                        // Post-scan feedback
                        feedbackCard

                        Spacer().frame(height: 40)
                    }
                    .padding(CDSpacing.medium)
                }
            }
            .navigationTitle("Scan Results")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Color.cdPrimaryBright)
                }
            }
        }
    }

    // MARK: - Vehicle Hero

    private var vehicleHero: some View {
        VStack(spacing: CDSpacing.medium) {
            // Vehicle image
            if let imageURL = result.vehicleImageURL {
                AsyncImage(url: URL(string: imageURL)) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fit)
                            .frame(width: 280, height: 180)
                            .shadow(color: Color.black.opacity(0.4), radius: 20, y: 10)
                    case .failure, .empty:
                        imagePlaceholder
                    @unknown default:
                        imagePlaceholder
                    }
                }
                .id(imageURL)
                .frame(width: 280, height: 180)
            } else {
                imagePlaceholder
            }

            VStack(spacing: CDSpacing.xs) {
                Text(result.vehicle.displayName)
                    .font(.system(size: 20, weight: .bold))
                    .foregroundStyle(Color.cdTextPrimary)

                if let engine = result.engine ?? result.vehicle.engine {
                    Text(engine)
                        .font(.system(size: 14))
                        .foregroundStyle(Color.cdTextSecondary)
                }

                if let obdSource = result.obdSource {
                    Text(obdSource)
                        .font(.system(size: 12))
                        .foregroundStyle(Color.cdTextTertiary)
                        .padding(.top, 2)
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(CDSpacing.large)
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(Color.cdCardBackground)
        )
    }

    private var imagePlaceholder: some View {
        ZStack {
            Color.cdCardBackgroundLight
                .frame(width: 280, height: 180)
                .clipShape(RoundedRectangle(cornerRadius: 12))

            Image(systemName: "car.side.fill")
                .font(.system(size: 60))
                .foregroundStyle(Color.cdTextTertiary)
        }
    }

    // MARK: - Safety Status Card

    private var safetyStatusCard: some View {
        VStack(spacing: CDSpacing.medium) {
            // Status icon with glow
            ZStack {
                Circle()
                    .fill(result.safetyRating.color.opacity(0.15))
                    .frame(width: 80, height: 80)
                    .blur(radius: 15)

                Circle()
                    .fill(result.safetyRating.color.opacity(0.1))
                    .frame(width: 60, height: 60)

                Image(systemName: result.safetyRating.icon)
                    .font(.system(size: 28))
                    .foregroundStyle(result.safetyRating.color)
            }

            VStack(spacing: CDSpacing.xs) {
                Text(result.safetyRating.rawValue.uppercased())
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(result.safetyRating.color)

                Text(result.safetyRating.label)
                    .font(.system(size: 13))
                    .foregroundStyle(Color.cdTextSecondary)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CDSpacing.large)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color.cdCardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(result.safetyRating.color.opacity(0.2), lineWidth: 1)
                )
        )
    }

    // MARK: - Vehicle Specs Section

    private var vehicleSpecsSection: some View {
        VStack(spacing: CDSpacing.small) {
            HStack(spacing: CDSpacing.small) {
                SpecWidget(
                    title: "Engine",
                    value: formatSpec(result.engine ?? result.vehicle.engine),
                    icon: "engine.combustion"
                )
                SpecWidget(
                    title: "Trans",
                    value: formatSpec(result.transmission ?? result.vehicle.transmission),
                    icon: "gearshape.2.fill"
                )
            }
            HStack(spacing: CDSpacing.small) {
                SpecWidget(
                    title: "Drive",
                    value: formatDrive(result.drive ?? result.vehicle.driveType),
                    icon: "car.fill"
                )
                SpecWidget(
                    title: "Fuel",
                    value: result.fuelType ?? result.vehicle.fuelType ?? "--",
                    icon: "fuelpump.fill"
                )
            }
            // Bottom row: MPG, Range
            HStack(spacing: CDSpacing.small) {
                SpecWidget(
                    title: "MPG",
                    value: result.vehicle.mpgDisplay ?? "--",
                    icon: "gauge.with.dots.needle.33percent"
                )
                SpecWidget(
                    title: "Range",
                    value: result.vehicle.estimatedRange ?? "--",
                    icon: "road.lanes"
                )
            }
        }
    }

    private func formatSpec(_ value: String?) -> String {
        guard let value = value, !value.isEmpty else { return "--" }
        if value.count <= 14 { return value }
        return String(value.prefix(12)) + ".."
    }

    private func formatDrive(_ drive: String?) -> String {
        guard let drive = drive?.lowercased() else { return "--" }
        if drive.contains("rear") { return "RWD" }
        if drive.contains("front") { return "FWD" }
        if drive.contains("all") || drive.contains("awd") { return "AWD" }
        if drive.contains("4") { return "4WD" }
        return String(drive.prefix(4).uppercased())
    }

    // MARK: - Live Data Section

    private var liveDataSection: some View {
        // Use live data if connected, otherwise fall back to scan-time data
        let isLive = liveData?.connected == true
        let displayRpm = isLive ? (liveData?.rpm.map { Int($0) }) : result.rpm
        let displaySpeed = isLive ? (liveData?.speed.map { Int($0) }) : result.speed
        let displayTemp = isLive ? (liveData?.coolantTemp.map { Int($0) }) : result.coolantTemp

        return VStack(alignment: .leading, spacing: CDSpacing.small) {
            HStack(spacing: CDSpacing.xs) {
                Image(systemName: isLive ? "antenna.radiowaves.left.and.right.circle.fill" : "antenna.radiowaves.left.and.right")
                    .font(.system(size: 11))
                    .foregroundStyle(isLive ? Color.green : Color.cdPrimaryBright)

                Text("OBD-II DATA")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(isLive ? Color.green : Color.cdPrimaryBright)
                    .tracking(0.5)

                Spacer()

                if isLive {
                    HStack(spacing: 4) {
                        Circle()
                            .fill(Color.green)
                            .frame(width: 6, height: 6)
                        Text("LIVE")
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(Color.green)
                    }
                } else {
                    Text("AT TIME OF SCAN")
                        .font(.system(size: 9, weight: .medium))
                        .foregroundStyle(Color.cdTextTertiary)
                }
            }
            .padding(.horizontal, CDSpacing.small)

            HStack(spacing: CDSpacing.small) {
                if let rpm = displayRpm {
                    LiveDataWidget(
                        value: "\(rpm)",
                        label: "RPM",
                        icon: "gauge.with.needle",
                        color: isLive ? .green : .cdPrimaryBright
                    )
                }
                if let speed = displaySpeed {
                    LiveDataWidget(
                        value: units.speed(speed),
                        label: "Speed",
                        icon: "speedometer",
                        color: isLive ? .green : .cdPrimaryBright
                    )
                }
                if let temp = displayTemp {
                    LiveDataWidget(
                        value: units.temperature(temp),
                        label: "Coolant",
                        icon: "thermometer.medium",
                        color: isLive ? .green : .cdPrimaryBright
                    )
                }
            }
        }
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color.cdCardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(Color.cdPrimary.opacity(0.15), lineWidth: 1)
                )
        )
    }

    // MARK: - DTC Codes Section

    private var dtcCodesSection: some View {
        VStack(alignment: .leading, spacing: CDSpacing.small) {
            SectionHeader(title: "Diagnostic Codes")

            VStack(spacing: CDSpacing.small) {
                ForEach(result.codes) { code in
                    HStack(spacing: CDSpacing.medium) {
                        Text(code.code)
                            .font(.system(size: 15, weight: .bold, design: .monospaced))
                            .foregroundStyle(Color.cdWarning)
                            .frame(width: 70, alignment: .leading)

                        Text(code.description)
                            .font(.system(size: 13))
                            .foregroundStyle(Color.cdTextPrimary)
                            .lineLimit(2)

                        Spacer()
                    }
                    .padding(CDSpacing.small)
                    .background(Color.cdWarning.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }
            }
            .padding(CDSpacing.medium)
            .background(
                RoundedRectangle(cornerRadius: 14)
                    .fill(Color.cdCardBackground)
            )
        }
    }

    // MARK: - Diagnostic Cards Section

    private var diagnosticCardsSection: some View {
        VStack(spacing: CDSpacing.medium) {
            if let content = result.dontPanic, !content.isEmpty {
                VehicleDiagnosticCard(title: "What's Happening", content: content, icon: "info.circle.fill")
            }

            if let content = result.likelyCauses, !content.isEmpty {
                VehicleDiagnosticCard(title: "Likely Causes", content: content, icon: "questionmark.circle.fill")
            }

            if let content = result.symptoms, !content.isEmpty {
                VehicleDiagnosticCard(title: "What You Might Notice", content: content, icon: "eye.fill")
            }

            if let content = result.ifIgnored, !content.isEmpty {
                VehicleDiagnosticCard(title: "If You Ignore This", content: content, icon: "exclamationmark.triangle.fill", isWarning: true)
            }

            if let content = result.quickChecks, !content.isEmpty {
                VehicleDiagnosticCard(title: "Quick Checks", content: content, icon: "checklist")
            }

            if let content = result.diyFix, !content.isEmpty {
                VehicleDiagnosticCard(title: "DIY Fix", content: content, icon: "wrench.and.screwdriver.fill")
            }

            if let content = result.urgency, !content.isEmpty {
                VehicleDiagnosticCard(title: "When To See A Mechanic", content: content, icon: "clock.fill")
            }

            if let content = result.repairCost, !content.isEmpty {
                VehicleDiagnosticCard(title: "Estimated Cost", content: content, icon: "dollarsign.circle.fill")
            }

            if let content = result.knownIssues, !content.isEmpty {
                VehicleDiagnosticCard(title: "Known Issues", content: content, icon: "doc.text.fill")
            }

            if let content = result.ownerReports, !content.isEmpty {
                VehicleDiagnosticCard(title: "Owner Reports", content: content, icon: "person.2.fill")
            }
        }
    }

    // MARK: - Follow-up Card

    private var followUpCard: some View {
        VStack(alignment: .leading, spacing: CDSpacing.medium) {
            HStack(spacing: CDSpacing.xs) {
                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(.system(size: 14))
                    .foregroundStyle(Color.cdPrimaryBright)

                Text("Ask Follow-up Questions")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color.cdTextPrimary)
            }

            // Quick questions
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: CDSpacing.small) {
                    QuickQuestionButton(text: "Repair cost?") {
                        askQuestion("How much will this repair cost?", isHumanGenerated: false)
                    }
                    QuickQuestionButton(text: "Safe to drive?") {
                        askQuestion("Can I drive to work tomorrow?", isHumanGenerated: false)
                    }
                    QuickQuestionButton(text: "Parts needed?") {
                        askQuestion("What parts might need replacing?", isHumanGenerated: false)
                    }
                    QuickQuestionButton(text: "DIY possible?") {
                        askQuestion("Can I fix this myself?", isHumanGenerated: false)
                    }
                }
            }

            // Chat messages
            if !chatMessages.isEmpty {
                VStack(spacing: CDSpacing.small) {
                    ForEach(chatMessages) { message in
                        ChatBubble(message: message)
                    }

                    if isAskingQuestion {
                        HStack {
                            ProgressView()
                                .scaleEffect(0.8)
                            Text("Thinking...")
                                .font(.system(size: 12))
                                .foregroundStyle(Color.cdTextTertiary)
                            Spacer()
                        }
                        .padding(.leading, CDSpacing.small)
                    }
                }
            }

            // Input field
            HStack(spacing: CDSpacing.small) {
                TextField("Ask a question...", text: $currentQuestion)
                    .font(.system(size: 14))
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
                    .background(Color.cdCardBackgroundLight)
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                Button {
                    askQuestion(currentQuestion)
                    currentQuestion = ""
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 32))
                        .foregroundStyle(Color.cdPrimaryBright)
                }
                .disabled(currentQuestion.isEmpty || isAskingQuestion)
                .opacity(currentQuestion.isEmpty ? 0.5 : 1)
            }
        }
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color.cdCardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(Color.cdPrimary.opacity(0.15), lineWidth: 1)
                )
        )
    }

    // MARK: - Feedback Card

    private var feedbackCard: some View {
        VStack(spacing: CDSpacing.medium) {
            Text("How was this diagnosis?")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Color.cdTextPrimary)

            if feedbackSubmitted {
                HStack(spacing: CDSpacing.xs) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(Color.cdSuccess)
                    Text("Thanks for your feedback!")
                        .font(.system(size: 14))
                        .foregroundStyle(Color.cdTextSecondary)
                }
                .transition(.opacity.combined(with: .scale))
            } else {
                HStack(spacing: CDSpacing.medium) {
                    FeedbackButton(
                        icon: "hand.thumbsdown.fill",
                        label: "Bad",
                        color: .cdCritical,
                        isSelected: selectedFeedback == "bad",
                        isLoading: isSubmittingFeedback && selectedFeedback == "bad"
                    ) {
                        submitFeedback("bad")
                    }

                    FeedbackButton(
                        icon: "hand.thumbsup.fill",
                        label: "OK",
                        color: .cdWarning,
                        isSelected: selectedFeedback == "ok",
                        isLoading: isSubmittingFeedback && selectedFeedback == "ok",
                        rotation: -90
                    ) {
                        submitFeedback("ok")
                    }

                    FeedbackButton(
                        icon: "hand.thumbsup.fill",
                        label: "Good",
                        color: .cdSuccess,
                        isSelected: selectedFeedback == "good",
                        isLoading: isSubmittingFeedback && selectedFeedback == "good"
                    ) {
                        submitFeedback("good")
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color.cdCardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(Color.cdPrimary.opacity(0.15), lineWidth: 1)
                )
        )
    }

    // MARK: - Actions

    private func askQuestion(_ question: String, isHumanGenerated: Bool = true) {
        guard !question.isEmpty else { return }

        chatMessages.append(ChatMessage(role: .user, content: question))
        isAskingQuestion = true

        Task {
            let context: [String: Any] = [
                "vehicle": result.vehicle.displayName,
                "codes": result.codes.map { $0.code },
                "safety_level": result.safetyRating.rawValue,
                "engine": result.engine ?? "",
                "transmission": result.transmission ?? "",
                "drive": result.drive ?? "",
                "summary": result.dontPanic ?? "",
                "likely_causes": result.likelyCauses ?? ""
            ]

            let history = chatMessages.map { ["role": $0.role == .user ? "user" : "assistant", "content": $0.content] }

            do {
                let answer = try await apiClient.askFollowUp(
                    question: question,
                    context: context,
                    history: history,
                    scanId: result.scanId,
                    isHumanGenerated: isHumanGenerated
                )
                await MainActor.run {
                    chatMessages.append(ChatMessage(role: .assistant, content: answer))
                    isAskingQuestion = false
                }
            } catch {
                await MainActor.run {
                    chatMessages.append(ChatMessage(role: .assistant, content: "Sorry, couldn't get an answer. Please try again."))
                    isAskingQuestion = false
                }
            }
        }
    }

    private func submitFeedback(_ rating: String) {
        guard let scanId = result.scanId else { return }
        selectedFeedback = rating
        isSubmittingFeedback = true

        Task {
            do {
                _ = try await apiClient.submitFeedback(scanId: scanId, rating: rating)
                await MainActor.run {
                    withAnimation(.easeInOut(duration: 0.3)) {
                        feedbackSubmitted = true
                    }
                    isSubmittingFeedback = false
                }
            } catch {
                await MainActor.run {
                    isSubmittingFeedback = false
                }
            }
        }
    }
}

// MARK: - Quick Question Button

struct QuickQuestionButton: View {
    let text: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(text)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Color.cdTextPrimary)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(Color.cdCardBackgroundLight)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color.cdPrimary.opacity(0.2), lineWidth: 1)
                )
        }
    }
}

// MARK: - Chat Message

struct ChatMessage: Identifiable {
    let id = UUID()
    let role: Role
    let content: String

    enum Role {
        case user, assistant
    }
}

struct ChatBubble: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.role == .user { Spacer() }

            Text(message.content)
                .font(.system(size: 14))
                .foregroundStyle(Color.cdTextPrimary)
                .padding(CDSpacing.small)
                .background(
                    message.role == .user
                        ? Color.cdPrimary.opacity(0.2)
                        : Color.cdCardBackgroundLight
                )
                .clipShape(RoundedRectangle(cornerRadius: 10))

            if message.role == .assistant { Spacer() }
        }
    }
}

// MARK: - Feedback Button

struct FeedbackButton: View {
    let icon: String
    let label: String
    let color: Color
    var isSelected: Bool = false
    var isLoading: Bool = false
    var rotation: Double = 0
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: CDSpacing.xs) {
                if isLoading {
                    ProgressView()
                        .scaleEffect(0.8)
                        .frame(width: 32, height: 32)
                } else {
                    Image(systemName: icon)
                        .font(.system(size: 24))
                        .rotationEffect(.degrees(rotation))
                        .foregroundStyle(isSelected ? color : Color.cdTextSecondary)
                }

                Text(label)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(isSelected ? color : Color.cdTextTertiary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, CDSpacing.small)
            .background(
                RoundedRectangle(cornerRadius: 10)
                    .fill(isSelected ? color.opacity(0.15) : Color.cdCardBackgroundLight)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .stroke(isSelected ? color.opacity(0.3) : Color.clear, lineWidth: 1)
            )
        }
        .disabled(isLoading)
    }
}

#Preview {
    ResultsView(result: .preview)
        .environmentObject(APIClient())
        .preferredColorScheme(.dark)
}
