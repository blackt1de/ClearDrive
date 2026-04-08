//
//  ServiceView.swift
//  ClearDrive
//
//  Service reminders and maintenance tracking
//

import SwiftUI
import UserNotifications

struct ServiceView: View {
    @EnvironmentObject var vehicleStore: VehicleStore
    @Binding var selectedVehicle: VehicleInfo?
    @Binding var liveData: LiveOBDData?

    @State private var showingAddService = false
    @State private var showingServiceHistory = false
    @State private var notificationsEnabled = false

    var currentVehicle: SavedVehicle? {
        guard let selected = selectedVehicle else { return nil }
        return vehicleStore.savedVehicles.first {
            $0.vehicle.year == selected.year &&
            $0.vehicle.make == selected.make &&
            $0.vehicle.model == selected.model
        }
    }

    var body: some View {
        ZStack {
            Color.cdBackground
                .ignoresSafeArea()

            ScrollView {
                VStack(spacing: CDSpacing.large) {
                    // Header
                    headerSection

                    // Current mileage card
                    mileageCard

                    // Service items
                    serviceItemsSection

                    // Quick actions
                    quickActionsSection

                    Spacer(minLength: 100)
                }
                .padding(CDSpacing.medium)
            }
        }
        .navigationTitle("Service")
        .sheet(isPresented: $showingAddService) {
            AddServiceSheet(vehicle: currentVehicle)
                .environmentObject(vehicleStore)
        }
        .sheet(isPresented: $showingServiceHistory) {
            ServiceHistorySheet(vehicle: currentVehicle)
                .environmentObject(vehicleStore)
        }
        .onAppear {
            checkNotificationPermission()
        }
    }

    // MARK: - Header

    private var headerSection: some View {
        VStack(spacing: CDSpacing.small) {
            if let vehicle = selectedVehicle {
                Text(vehicle.displayName)
                    .font(.headline)
                    .foregroundStyle(Color.cdTextPrimary)
            } else {
                Text("No Vehicle Selected")
                    .font(.headline)
                    .foregroundStyle(Color.cdTextSecondary)
            }
        }
    }

    // MARK: - Mileage Card

    private var mileageCard: some View {
        VStack(spacing: CDSpacing.medium) {
            HStack {
                Image(systemName: "speedometer")
                    .font(.title2)
                    .foregroundStyle(Color.cdPrimaryBright)

                Text("Current Mileage")
                    .font(.headline)
                    .foregroundStyle(Color.cdTextPrimary)

                Spacer()

                if liveData?.odometer != nil {
                    HStack(spacing: 4) {
                        Circle()
                            .fill(Color.cdSuccess)
                            .frame(width: 8, height: 8)
                        Text("LIVE")
                            .font(.caption2)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.cdSuccess)
                    }
                }
            }

            HStack(alignment: .bottom, spacing: 4) {
                if let odometer = liveData?.odometer {
                    Text(formatMileage(odometer))
                        .font(.system(size: 36, weight: .bold))
                        .foregroundStyle(Color.cdTextPrimary)
                } else if let saved = currentVehicle?.currentMileage {
                    Text(formatMileage(saved))
                        .font(.system(size: 36, weight: .bold))
                        .foregroundStyle(Color.cdTextPrimary)
                } else {
                    Text("--")
                        .font(.system(size: 36, weight: .bold))
                        .foregroundStyle(Color.cdTextSecondary)
                }

                Text("miles")
                    .font(.subheadline)
                    .foregroundStyle(Color.cdTextSecondary)
                    .padding(.bottom, 6)
            }

            if liveData?.odometer == nil && currentVehicle?.currentMileage == nil {
                Text("Connect OBD to read mileage automatically")
                    .font(.caption)
                    .foregroundStyle(Color.cdTextTertiary)
            }
        }
        .padding(CDSpacing.large)
        .background(Color.cdCardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Service Items

    private var serviceItemsSection: some View {
        VStack(alignment: .leading, spacing: CDSpacing.medium) {
            Text("MAINTENANCE")
                .font(.caption)
                .fontWeight(.semibold)
                .foregroundStyle(Color.cdTextTertiary)
                .tracking(0.5)

            // Oil Change
            ServiceItemRow(
                type: .oilChange,
                lastService: currentVehicle?.lastOilChangeDate,
                lastMileage: currentVehicle?.lastOilChangeMileage,
                currentMileage: liveData?.odometer ?? currentVehicle?.currentMileage,
                intervalMiles: 5000,
                intervalMonths: 6
            )

            // Tire Rotation
            ServiceItemRow(
                type: .tireRotation,
                lastService: currentVehicle?.serviceHistory.first(where: { $0.type == .tireRotation })?.date,
                lastMileage: currentVehicle?.serviceHistory.first(where: { $0.type == .tireRotation })?.mileage,
                currentMileage: liveData?.odometer ?? currentVehicle?.currentMileage,
                intervalMiles: 7500,
                intervalMonths: 6
            )

            // Brake Service
            ServiceItemRow(
                type: .brakeService,
                lastService: currentVehicle?.serviceHistory.first(where: { $0.type == .brakeService })?.date,
                lastMileage: currentVehicle?.serviceHistory.first(where: { $0.type == .brakeService })?.mileage,
                currentMileage: liveData?.odometer ?? currentVehicle?.currentMileage,
                intervalMiles: 30000,
                intervalMonths: 24
            )

            // Air Filter
            ServiceItemRow(
                type: .airFilter,
                lastService: currentVehicle?.serviceHistory.first(where: { $0.type == .airFilter })?.date,
                lastMileage: currentVehicle?.serviceHistory.first(where: { $0.type == .airFilter })?.mileage,
                currentMileage: liveData?.odometer ?? currentVehicle?.currentMileage,
                intervalMiles: 15000,
                intervalMonths: 12
            )
        }
    }

    // MARK: - Quick Actions

    private var quickActionsSection: some View {
        VStack(spacing: CDSpacing.small) {
            Button {
                showingAddService = true
            } label: {
                HStack {
                    Image(systemName: "plus.circle.fill")
                    Text("Log Service")
                }
                .font(.headline)
                .foregroundStyle(Color.cdPrimaryBright)
                .frame(maxWidth: .infinity)
                .padding(CDSpacing.medium)
                .background(Color.cdPrimary.opacity(0.15))
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }

            Button {
                showingServiceHistory = true
            } label: {
                HStack {
                    Image(systemName: "clock.arrow.circlepath")
                    Text("View History")
                }
                .font(.subheadline)
                .foregroundStyle(Color.cdTextSecondary)
                .frame(maxWidth: .infinity)
                .padding(CDSpacing.medium)
                .background(Color.cdCardBackground)
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }

            // Notification toggle
            Toggle(isOn: $notificationsEnabled) {
                HStack {
                    Image(systemName: "bell.fill")
                        .foregroundStyle(Color.cdPrimaryBright)
                    Text("Service Reminders")
                        .foregroundStyle(Color.cdTextPrimary)
                }
            }
            .padding(CDSpacing.medium)
            .background(Color.cdCardBackground)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .onChange(of: notificationsEnabled) { _, newValue in
                if newValue {
                    requestNotificationPermission()
                }
            }
        }
    }

    // MARK: - Helpers

    private func formatMileage(_ miles: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = 0
        return formatter.string(from: NSNumber(value: miles)) ?? "\(Int(miles))"
    }

    private func checkNotificationPermission() {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            DispatchQueue.main.async {
                notificationsEnabled = settings.authorizationStatus == .authorized
            }
        }
    }

    private func requestNotificationPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { granted, _ in
            DispatchQueue.main.async {
                notificationsEnabled = granted
                if granted {
                    scheduleServiceReminders()
                }
            }
        }
    }

    private func scheduleServiceReminders() {
        guard let vehicle = currentVehicle else { return }

        // Schedule oil change reminder if due within 500 miles or 2 weeks
        if let nextMileage = vehicle.nextOilChangeMileage,
           let currentMileage = liveData?.odometer ?? vehicle.currentMileage {
            let milesRemaining = nextMileage - currentMileage
            if milesRemaining <= 500 && milesRemaining > 0 {
                scheduleNotification(
                    title: "Oil Change Due Soon",
                    body: "Your \(vehicle.vehicle.displayName) needs an oil change in \(Int(milesRemaining)) miles.",
                    identifier: "oil-change-\(vehicle.id)"
                )
            }
        }

        // Schedule date-based reminder
        if let nextDate = vehicle.nextOilChangeDate {
            let daysUntil = Calendar.current.dateComponents([.day], from: Date(), to: nextDate).day ?? 0
            if daysUntil <= 14 && daysUntil > 0 {
                scheduleNotification(
                    title: "Oil Change Due Soon",
                    body: "Your \(vehicle.vehicle.displayName) oil change is due in \(daysUntil) days.",
                    identifier: "oil-change-date-\(vehicle.id)",
                    date: Calendar.current.date(byAdding: .day, value: -7, to: nextDate)
                )
            }
        }
    }

    private func scheduleNotification(title: String, body: String, identifier: String, date: Date? = nil) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default

        let trigger: UNNotificationTrigger
        if let date = date {
            let components = Calendar.current.dateComponents([.year, .month, .day, .hour], from: date)
            trigger = UNCalendarNotificationTrigger(dateMatching: components, repeats: false)
        } else {
            // Schedule for tomorrow morning at 9am
            var components = DateComponents()
            components.hour = 9
            components.minute = 0
            trigger = UNCalendarNotificationTrigger(dateMatching: components, repeats: false)
        }

        let request = UNNotificationRequest(identifier: identifier, content: content, trigger: trigger)
        UNUserNotificationCenter.current().add(request)
    }
}

// MARK: - Service Item Row

struct ServiceItemRow: View {
    let type: ServiceType
    let lastService: Date?
    let lastMileage: Double?
    let currentMileage: Double?
    let intervalMiles: Int
    let intervalMonths: Int

    var status: ServiceStatus {
        guard let lastMileage = lastMileage, let currentMileage = currentMileage else {
            return .unknown
        }

        let milesSince = currentMileage - lastMileage
        let milesRemaining = Double(intervalMiles) - milesSince

        if milesRemaining <= 0 {
            return .overdue(Int(abs(milesRemaining)))
        } else if milesRemaining <= Double(intervalMiles) * 0.1 {
            return .dueSoon(Int(milesRemaining))
        } else {
            return .ok(Int(milesRemaining))
        }
    }

    enum ServiceStatus {
        case unknown
        case ok(Int)
        case dueSoon(Int)
        case overdue(Int)

        var color: Color {
            switch self {
            case .unknown: return .cdTextSecondary
            case .ok: return .cdSuccess
            case .dueSoon: return .cdWarning
            case .overdue: return .cdCritical
            }
        }

        var icon: String {
            switch self {
            case .unknown: return "questionmark.circle"
            case .ok: return "checkmark.circle.fill"
            case .dueSoon: return "exclamationmark.circle.fill"
            case .overdue: return "xmark.circle.fill"
            }
        }
    }

    var body: some View {
        HStack(spacing: CDSpacing.medium) {
            // Icon
            ZStack {
                Circle()
                    .fill(status.color.opacity(0.15))
                    .frame(width: 44, height: 44)

                Image(systemName: type.icon)
                    .font(.system(size: 18))
                    .foregroundStyle(status.color)
            }

            // Info
            VStack(alignment: .leading, spacing: 4) {
                Text(type.rawValue)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.cdTextPrimary)

                switch status {
                case .unknown:
                    Text("Not tracked")
                        .font(.caption)
                        .foregroundStyle(Color.cdTextTertiary)
                case .ok(let miles):
                    Text("\(formatNumber(miles)) miles remaining")
                        .font(.caption)
                        .foregroundStyle(Color.cdTextSecondary)
                case .dueSoon(let miles):
                    Text("Due in \(formatNumber(miles)) miles")
                        .font(.caption)
                        .foregroundStyle(Color.cdWarning)
                case .overdue(let miles):
                    Text("Overdue by \(formatNumber(miles)) miles")
                        .font(.caption)
                        .foregroundStyle(Color.cdCritical)
                }
            }

            Spacer()

            // Status icon
            Image(systemName: status.icon)
                .font(.title3)
                .foregroundStyle(status.color)
        }
        .padding(CDSpacing.medium)
        .background(Color.cdCardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func formatNumber(_ num: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        return formatter.string(from: NSNumber(value: num)) ?? "\(num)"
    }
}

// MARK: - Add Service Sheet

struct AddServiceSheet: View {
    @EnvironmentObject var vehicleStore: VehicleStore
    @Environment(\.dismiss) private var dismiss

    let vehicle: SavedVehicle?

    @State private var selectedType: ServiceType = .oilChange
    @State private var date = Date()
    @State private var mileageText = ""
    @State private var notes = ""
    @State private var costText = ""

    var body: some View {
        NavigationStack {
            ZStack {
                Color.cdBackground
                    .ignoresSafeArea()

                Form {
                    Section {
                        Picker("Service Type", selection: $selectedType) {
                            ForEach(ServiceType.allCases) { type in
                                Label(type.rawValue, systemImage: type.icon)
                                    .tag(type)
                            }
                        }

                        DatePicker("Date", selection: $date, displayedComponents: .date)

                        HStack {
                            Text("Mileage")
                            Spacer()
                            TextField("Enter mileage", text: $mileageText)
                                .keyboardType(.numberPad)
                                .multilineTextAlignment(.trailing)
                        }

                        HStack {
                            Text("Cost")
                            Spacer()
                            TextField("Optional", text: $costText)
                                .keyboardType(.decimalPad)
                                .multilineTextAlignment(.trailing)
                        }
                    }
                    .listRowBackground(Color.cdCardBackground)

                    Section("Notes") {
                        TextField("Optional notes", text: $notes, axis: .vertical)
                            .lineLimit(3...6)
                    }
                    .listRowBackground(Color.cdCardBackground)
                }
                .scrollContentBackground(.hidden)
            }
            .navigationTitle("Log Service")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        saveService()
                    }
                    .disabled(mileageText.isEmpty)
                }
            }
        }
    }

    private func saveService() {
        guard let vehicle = vehicle,
              let mileage = Double(mileageText) else { return }

        let cost = Double(costText)

        let record = ServiceRecord(
            type: selectedType,
            date: date,
            mileage: mileage,
            notes: notes.isEmpty ? nil : notes,
            cost: cost
        )

        // Update vehicle store
        if selectedType == .oilChange {
            vehicleStore.updateServiceInfo(for: vehicle.id, date: date, mileage: mileage)
        }

        vehicleStore.addServiceRecord(for: vehicle.id, record: record)

        dismiss()
    }
}

// MARK: - Service History Sheet

struct ServiceHistorySheet: View {
    @EnvironmentObject var vehicleStore: VehicleStore
    @Environment(\.dismiss) private var dismiss

    let vehicle: SavedVehicle?

    var body: some View {
        NavigationStack {
            ZStack {
                Color.cdBackground
                    .ignoresSafeArea()

                if let vehicle = vehicle, !vehicle.serviceHistory.isEmpty {
                    List {
                        ForEach(vehicle.serviceHistory.sorted(by: { $0.date > $1.date })) { record in
                            ServiceHistoryRow(record: record)
                        }
                        .listRowBackground(Color.cdCardBackground)
                    }
                    .scrollContentBackground(.hidden)
                } else {
                    VStack(spacing: CDSpacing.medium) {
                        Image(systemName: "doc.text")
                            .font(.system(size: 48))
                            .foregroundStyle(Color.cdTextTertiary)
                        Text("No service history")
                            .font(.headline)
                            .foregroundStyle(Color.cdTextSecondary)
                        Text("Log your first service to start tracking")
                            .font(.subheadline)
                            .foregroundStyle(Color.cdTextTertiary)
                    }
                }
            }
            .navigationTitle("Service History")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
    }
}

struct ServiceHistoryRow: View {
    let record: ServiceRecord

    var body: some View {
        HStack(spacing: CDSpacing.medium) {
            Image(systemName: record.type.icon)
                .font(.title3)
                .foregroundStyle(Color.cdPrimaryBright)
                .frame(width: 32)

            VStack(alignment: .leading, spacing: 2) {
                Text(record.type.rawValue)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.cdTextPrimary)

                Text("\(formatDate(record.date)) at \(formatMileage(record.mileage)) mi")
                    .font(.caption)
                    .foregroundStyle(Color.cdTextSecondary)

                if let notes = record.notes {
                    Text(notes)
                        .font(.caption)
                        .foregroundStyle(Color.cdTextTertiary)
                        .lineLimit(2)
                }
            }

            Spacer()

            if let cost = record.cost {
                Text("$\(Int(cost))")
                    .font(.subheadline)
                    .foregroundStyle(Color.cdTextSecondary)
            }
        }
        .padding(.vertical, 4)
    }

    private func formatDate(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        return formatter.string(from: date)
    }

    private func formatMileage(_ miles: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = 0
        return formatter.string(from: NSNumber(value: miles)) ?? "\(Int(miles))"
    }
}

#Preview {
    NavigationStack {
        ServiceView(
            selectedVehicle: .constant(VehicleInfo.preview),
            liveData: .constant(nil)
        )
        .environmentObject(VehicleStore())
    }
    .preferredColorScheme(.dark)
}
