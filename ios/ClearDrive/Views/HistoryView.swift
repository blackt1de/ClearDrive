import SwiftUI

struct HistoryView: View {
    @EnvironmentObject var apiClient: APIClient
    @State private var scans: [ScanHistory] = []
    @State private var isLoading = false

    var body: some View {
        NavigationStack {
            Group {
                if isLoading {
                    ProgressView("Loading history...")
                } else if scans.isEmpty {
                    VStack(spacing: 16) {
                        Image(systemName: "clock.badge.questionmark")
                            .font(.system(size: 50))
                            .foregroundStyle(.secondary)

                        Text("No Scan History")
                            .font(.headline)

                        Text("Your previous scans will appear here")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                } else {
                    List(scans) { scan in
                        HistoryRow(scan: scan)
                    }
                    .listStyle(.plain)
                }
            }
            .navigationTitle("History")
            .onAppear {
                loadHistory()
            }
            .refreshable {
                loadHistory()
            }
        }
    }

    private func loadHistory() {
        isLoading = true
        Task {
            do {
                let history = try await apiClient.getHistory()
                await MainActor.run {
                    scans = history
                    isLoading = false
                }
            } catch {
                await MainActor.run {
                    isLoading = false
                }
            }
        }
    }
}

struct HistoryRow: View {
    let scan: ScanHistory

    var body: some View {
        HStack(spacing: 12) {
            Circle()
                .fill(scan.safetyColor)
                .frame(width: 12, height: 12)

            VStack(alignment: .leading, spacing: 4) {
                Text(scan.vehicleDescription)
                    .font(.headline)

                Text("\(scan.codeCount) code\(scan.codeCount == 1 ? "" : "s") found")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Text(scan.date, style: .relative)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 8)
    }
}

#Preview {
    HistoryView()
        .environmentObject(APIClient())
}
