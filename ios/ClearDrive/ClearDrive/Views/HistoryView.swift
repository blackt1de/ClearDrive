//
//  HistoryView.swift
//  ClearDrive
//
//  History tab - View past scan records
//

import SwiftUI

struct HistoryView: View {
    @EnvironmentObject var apiClient: APIClient
    @EnvironmentObject var vehicleStore: VehicleStore

    @State private var isLoading = false
    @State private var selectedFilter: HistoryFilter = .all
    @State private var selectedScanResult: ScanResult?

    var body: some View {
        ZStack {
            Color.cdBackground
                .ignoresSafeArea()

            Group {
                if vehicleStore.scanHistory.isEmpty {
                    emptyState
                } else {
                    historyList
                }
            }
        }
        .navigationTitle("History")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    ForEach(HistoryFilter.allCases, id: \.self) { filter in
                        Button(action: { selectedFilter = filter }) {
                            HStack {
                                Text(filter.label)
                                if selectedFilter == filter {
                                    Image(systemName: "checkmark")
                                }
                            }
                        }
                    }

                    Divider()

                    Button(role: .destructive) {
                        vehicleStore.clearAllHistory()
                    } label: {
                        Label("Clear History", systemImage: "trash")
                    }
                } label: {
                    Image(systemName: "line.3.horizontal.decrease.circle")
                        .foregroundStyle(Color.cdPrimary)
                }
            }
        }
        .sheet(item: $selectedScanResult) { result in
            ResultsView(result: result)
        }
    }

    // MARK: - Empty State

    private var emptyState: some View {
        VStack(spacing: CDSpacing.xlarge) {
            Spacer().frame(height: 60)

            ZStack {
                Circle()
                    .fill(Color.cdPrimary.opacity(0.1))
                    .frame(width: 120, height: 120)
                    .blur(radius: 20)

                Image(systemName: "clock.badge.questionmark")
                    .font(.system(size: 60))
                    .foregroundStyle(Color.cdTextTertiary)
            }

            Text("No Scan History")
                .font(.title2)
                .fontWeight(.semibold)

            Text("Your vehicle scan history will appear here\nafter you perform your first scan")
                .font(.subheadline)
                .foregroundStyle(Color.cdTextSecondary)
                .multilineTextAlignment(.center)

            Spacer()
        }
        .padding(CDSpacing.medium)
    }

    // MARK: - History List

    private var historyList: some View {
        ScrollView(showsIndicators: false) {
            LazyVStack(spacing: CDSpacing.medium) {
                ForEach(filteredHistory) { result in
                    historyCard(result)
                        .onTapGesture {
                            selectedScanResult = result
                        }
                }
            }
            .padding(CDSpacing.medium)
        }
    }

    private var filteredHistory: [ScanResult] {
        switch selectedFilter {
        case .all:
            return vehicleStore.scanHistory
        case .critical:
            return vehicleStore.scanHistory.filter { $0.safetyRating == .critical }
        case .warning:
            return vehicleStore.scanHistory.filter { $0.safetyRating == .caution }
        case .safe:
            return vehicleStore.scanHistory.filter { $0.safetyRating == .safe }
        }
    }

    private func historyCard(_ result: ScanResult) -> some View {
        VStack(alignment: .leading, spacing: CDSpacing.medium) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(result.vehicle.displayName)
                        .font(.headline)
                        .foregroundStyle(Color.cdTextPrimary)

                    Text(result.timestamp, style: .date)
                        .font(.caption)
                        .foregroundStyle(Color.cdTextSecondary)
                }

                Spacer()

                CDSafetyBadge(rating: result.safetyRating)
            }

            HStack {
                Label("\(result.codes.count) code\(result.codes.count == 1 ? "" : "s")", systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(Color.cdTextSecondary)

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundStyle(Color.cdTextTertiary)
            }
        }
        .padding(CDSpacing.medium)
        .background(Color.cdCardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }
}

// MARK: - History Filter

enum HistoryFilter: CaseIterable {
    case all
    case critical
    case warning
    case safe

    var label: String {
        switch self {
        case .all: return "All Scans"
        case .critical: return "Critical Only"
        case .warning: return "Warnings Only"
        case .safe: return "Safe Only"
        }
    }
}

#Preview {
    NavigationStack {
        HistoryView()
            .environmentObject(APIClient())
            .environmentObject(VehicleStore())
    }
    .preferredColorScheme(.dark)
}
