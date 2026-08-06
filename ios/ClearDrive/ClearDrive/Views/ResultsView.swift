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
        let formatted = formatTransmission(value)
        if formatted.count <= 14 { return formatted }
        return String(formatted.prefix(12)) + ".."
    }

    private func formatTransmission(_ raw: String) -> String {
        let upper = raw.uppercased().trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "()"))

        // Extract speed count
        let pattern = try? NSRegularExpression(pattern: "(\\d+)\\s*(?:SP|SPD|SPEED|-SPEED)", options: [])
        let range = NSRange(upper.startIndex..., in: upper)
        var speeds = ""
        if let match = pattern?.firstMatch(in: upper, range: range),
           let speedRange = Range(match.range(at: 1), in: upper) {
            speeds = String(upper[speedRange])
        } else if let first = upper.first, first.isNumber {
            speeds = String(first)
        }

        // Determine type
        var transType = ""
        if upper.contains("CVT") { transType = "CVT"; speeds = "" }
        else if upper.contains("DCT") || upper.contains("DUAL CLUTCH") || upper.contains("PDK") || upper.contains("DSG") { transType = "Dual-Clutch" }
        else if upper.contains("MANUAL") || upper.contains("MT") || upper.contains("M/T") { transType = "Manual" }
        else if upper.contains("AUTO") || upper.contains("AT") || upper.contains("A/T") { transType = "Automatic" }
        else { return raw } // Don't mangle unknown formats

        if !speeds.isEmpty && transType != "CVT" {
            return "\(speeds)-Speed \(transType)"
        }
        return transType.isEmpty ? raw : transType
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
            if result.isSynthetic {
                SyntheticDataBanner()
            }

            if let content = result.dontPanic, !content.isEmpty {
                VehicleDiagnosticCard(title: "What's Happening", content: content, icon: "info.circle.fill")
            }

            // The evidence-backed differential replaces the prose "Likely Causes"
            // whenever the rule engine reached a conclusion, because it can show
            // each cause next to the reading from THIS vehicle that supports it.
            // The prose version stays as the fallback for older backends.
            if !result.differential.isEmpty {
                EvidenceCausesCard(causes: result.differential)
            } else if let content = result.likelyCauses, !content.isEmpty {
                VehicleDiagnosticCard(title: "Likely Causes", content: content, icon: "questionmark.circle.fill")
            }

            if !result.notAssessed.isEmpty || !result.capabilityLimitations.isEmpty {
                NotAssessedCard(items: result.notAssessed,
                                limitations: result.capabilityLimitations)
            }

            if !result.codeStatus.isEmpty {
                CodeStatusCard(notes: result.codeStatus)
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

// MARK: - Evidence-backed causes
//
// This is the card that distinguishes ClearDrive from a web search: every cause
// is shown with the reading from THIS vehicle that points at it. The causes and
// their evidence are computed by the backend rule engine, not written by the
// language model, so what is rendered here is traceable to a measurement.

struct EvidenceCausesCard: View {
    let causes: [DiagnosticCause]

    var body: some View {
        VStack(alignment: .leading, spacing: CDSpacing.medium) {
            HStack(spacing: CDSpacing.small) {
                Image(systemName: "list.bullet.clipboard.fill")
                    .font(.system(size: 14))
                    .foregroundStyle(Color.cdPrimaryBright)
                Text("WHAT THE READINGS POINT TO")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color.cdPrimaryBright)
                    .tracking(0.5)
            }

            ForEach(Array(causes.enumerated()), id: \.element.id) { index, cause in
                VStack(alignment: .leading, spacing: CDSpacing.small) {
                    HStack(alignment: .top, spacing: CDSpacing.small) {
                        Text("\(index + 1)")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(Color.cdBackground)
                            .frame(width: 20, height: 20)
                            .background(Circle().fill(cause.confidenceColor))

                        Text(cause.conclusion)
                            .font(.system(size: 14))
                            .foregroundStyle(Color.cdTextPrimary.opacity(0.92))
                            .lineSpacing(4)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    // The evidence lines are the whole point — a reading from this
                    // specific car, not a generic claim about the model.
                    ForEach(cause.evidence) { item in
                        HStack(alignment: .top, spacing: 6) {
                            Image(systemName: "chart.bar.doc.horizontal")
                                .font(.system(size: 10))
                                .foregroundStyle(Color.cdPrimaryBright.opacity(0.8))
                                .padding(.top, 2)
                            Text(item.restatement)
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(Color.cdPrimaryBright.opacity(0.95))
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .padding(.leading, 28)
                    }

                    HStack(spacing: 6) {
                        Text(cause.confidence.uppercased())
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(cause.confidenceColor)
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(Capsule().fill(cause.confidenceColor.opacity(0.15)))
                        Text(cause.basisLabel)
                            .font(.system(size: 10))
                            .foregroundStyle(Color.cdTextSecondary)
                    }
                    .padding(.leading, 28)

                    if index < causes.count - 1 {
                        Divider().background(Color.cdTextSecondary.opacity(0.15))
                            .padding(.top, 4)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color.cdCardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(Color.cdPrimary.opacity(0.18), lineWidth: 1)
                )
        )
    }
}

// MARK: - What could not be checked
//
// Showing the gaps is what makes the rest trustworthy. A scan that quietly omits
// what it could not see reads as more confident than it has any right to be.

struct NotAssessedCard: View {
    let items: [NotAssessedItem]
    let limitations: [String]

    private var lines: [String] {
        var seen = Set<String>()
        var out: [String] = []
        for text in items.map(\.reason) + limitations where !seen.contains(text) {
            seen.insert(text)
            out.append(text)
        }
        return out
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CDSpacing.small) {
            HStack(spacing: CDSpacing.small) {
                Image(systemName: "eye.slash.fill")
                    .font(.system(size: 14))
                    .foregroundStyle(Color.cdTextSecondary)
                Text("WHAT WE COULDN'T CHECK")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color.cdTextSecondary)
                    .tracking(0.5)
            }

            ForEach(lines, id: \.self) { line in
                HStack(alignment: .top, spacing: 6) {
                    Text("•")
                        .font(.system(size: 13))
                        .foregroundStyle(Color.cdTextSecondary)
                    Text(line)
                        .font(.system(size: 13))
                        .foregroundStyle(Color.cdTextPrimary.opacity(0.75))
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            Text("These gaps are listed rather than guessed at.")
                .font(.system(size: 11))
                .foregroundStyle(Color.cdTextSecondary.opacity(0.8))
                .padding(.top, 2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color.cdCardBackground.opacity(0.6))
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(Color.cdTextSecondary.opacity(0.18), lineWidth: 1)
                )
        )
    }
}

// MARK: - Code status (pending / permanent)

struct CodeStatusCard: View {
    let notes: [CodeStatusNote]

    var body: some View {
        VStack(alignment: .leading, spacing: CDSpacing.small) {
            HStack(spacing: CDSpacing.small) {
                Image(systemName: "clock.badge.exclamationmark.fill")
                    .font(.system(size: 14))
                    .foregroundStyle(Color.cdWarning)
                Text("CODE STATUS")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color.cdWarning)
                    .tracking(0.5)
            }

            ForEach(notes) { note in
                Text(note.conclusion)
                    .font(.system(size: 13))
                    .foregroundStyle(Color.cdTextPrimary.opacity(0.85))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color.cdWarning.opacity(0.07))
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(Color.cdWarning.opacity(0.2), lineWidth: 1)
                )
        )
    }
}

// MARK: - Synthetic fixture banner
//
// A scenario run must never be mistakable for a real scan of a real car.

struct SyntheticDataBanner: View {
    var body: some View {
        HStack(spacing: CDSpacing.small) {
            Image(systemName: "testtube.2")
                .foregroundStyle(Color.cdWarning)
            Text("Test scenario — synthetic data, not a real vehicle scan")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Color.cdWarning)
            Spacer()
        }
        .padding(CDSpacing.small)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.cdWarning.opacity(0.12))
        )
    }
}

// MARK: - Scenario Picker (DEBUG)
//
// Drives the full pipeline from a named backend fixture so UI work needs no car
// and no adapter. Deterministic: the same scenario returns identical data every
// run, so anything that changes on screen is a change you made.

#if DEBUG
struct ScenarioPickerView: View {
    @EnvironmentObject var apiClient: APIClient
    @State private var scenarios: [APIClient.ScenarioSummary] = []
    @State private var result: ScanResult?
    @State private var loadingName: String?
    @State private var errorText: String?

    var body: some View {
        List {
            if let errorText {
                Text(errorText)
                    .font(.caption)
                    .foregroundStyle(Color.cdCritical)
                    .listRowBackground(Color.cdCardBackground)
            }

            ForEach(scenarios) { scenario in
                Button {
                    run(scenario.name)
                } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(scenario.vehicle)
                                .font(.system(size: 15, weight: .semibold))
                                .foregroundStyle(Color.cdTextPrimary)
                            Spacer()
                            if loadingName == scenario.name {
                                ProgressView()
                            }
                        }
                        Text(scenario.codes.isEmpty ? "no codes" : scenario.codes.joined(separator: ", "))
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(Color.cdPrimaryBright)
                        Text(scenario.description)
                            .font(.system(size: 11))
                            .foregroundStyle(Color.cdTextSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .disabled(loadingName != nil)
                .listRowBackground(Color.cdCardBackground)
            }
        }
        .scrollContentBackground(.hidden)
        .background(Color.cdBackground)
        .navigationTitle("Test Scenarios")
        .task {
            do { scenarios = try await apiClient.listScenarios() }
            catch { errorText = "Could not load scenarios: \(error.localizedDescription)" }
        }
        .sheet(item: $result) { scan in
            // Environment objects are passed explicitly — sheet content does not
            // reliably inherit them across presentation boundaries.
            ResultsView(result: scan)
                .environmentObject(apiClient)
        }
    }

    private func run(_ name: String) {
        loadingName = name
        errorText = nil
        Task {
            do { result = try await apiClient.interpretScenario(name) }
            catch { errorText = "Scenario failed: \(error.localizedDescription)" }
            loadingName = nil
        }
    }
}
#endif

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
