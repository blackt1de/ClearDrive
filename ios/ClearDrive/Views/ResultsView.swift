import SwiftUI

struct ResultsView: View {
    let result: ScanResult
    @Environment(\.dismiss) var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Vehicle Header with Image
                    if let imageURL = result.vehicleImageURL {
                        AsyncImage(url: imageURL) { image in
                            image
                                .resizable()
                                .aspectRatio(contentMode: .fit)
                        } placeholder: {
                            Rectangle()
                                .fill(Color(.systemGray5))
                                .overlay {
                                    ProgressView()
                                }
                        }
                        .frame(height: 200)
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                    }

                    // Vehicle Info
                    Text(result.vehicleDescription)
                        .font(.title2)
                        .fontWeight(.bold)

                    // Safety Rating
                    SafetyBadge(rating: result.safetyRating)

                    // Codes Found
                    if !result.codes.isEmpty {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("CODES FOUND")
                                .font(.caption)
                                .fontWeight(.semibold)
                                .foregroundStyle(.secondary)

                            ForEach(result.codes, id: \.code) { code in
                                CodeCard(code: code)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    } else {
                        VStack(spacing: 12) {
                            Image(systemName: "checkmark.circle.fill")
                                .font(.system(size: 50))
                                .foregroundStyle(.green)

                            Text("No Trouble Codes Found")
                                .font(.headline)

                            Text("Your vehicle is running great!")
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 30)
                    }

                    // AI Diagnosis
                    if let diagnosis = result.diagnosis {
                        VStack(alignment: .leading, spacing: 12) {
                            HStack {
                                Image(systemName: "brain")
                                    .foregroundStyle(.purple)
                                Text("AI DIAGNOSIS")
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                    .foregroundStyle(.secondary)
                            }

                            Text(diagnosis)
                                .font(.body)
                                .padding()
                                .background(Color(.systemGray6))
                                .clipShape(RoundedRectangle(cornerRadius: 12))
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    // Estimated Costs
                    if let costs = result.estimatedCosts {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("ESTIMATED REPAIR COSTS")
                                .font(.caption)
                                .fontWeight(.semibold)
                                .foregroundStyle(.secondary)

                            HStack {
                                VStack(alignment: .leading) {
                                    Text("Parts")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                    Text(costs.parts)
                                        .font(.headline)
                                }

                                Spacer()

                                VStack(alignment: .leading) {
                                    Text("Labor")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                    Text(costs.labor)
                                        .font(.headline)
                                }

                                Spacer()

                                VStack(alignment: .leading) {
                                    Text("Total")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                    Text(costs.total)
                                        .font(.headline)
                                        .foregroundStyle(.green)
                                }
                            }
                            .padding()
                            .background(Color(.systemGray6))
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding()
            }
            .navigationTitle("Scan Results")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
    }
}

struct SafetyBadge: View {
    let rating: SafetyRating

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: rating.icon)
            Text(rating.label)
                .fontWeight(.semibold)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(rating.color.opacity(0.2))
        .foregroundStyle(rating.color)
        .clipShape(Capsule())
    }
}

struct CodeCard: View {
    let code: DTCCode

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(code.code)
                    .font(.headline)
                    .fontWeight(.bold)
                    .foregroundStyle(.orange)

                Spacer()

                if let severity = code.severity {
                    Text(severity)
                        .font(.caption)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(severityColor(severity).opacity(0.2))
                        .foregroundStyle(severityColor(severity))
                        .clipShape(Capsule())
                }
            }

            Text(code.description)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding()
        .background(Color(.systemGray6))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func severityColor(_ severity: String) -> Color {
        switch severity.lowercased() {
        case "critical", "stop": return .red
        case "warning", "caution": return .orange
        default: return .green
        }
    }
}

#Preview {
    ResultsView(result: ScanResult.preview)
}
