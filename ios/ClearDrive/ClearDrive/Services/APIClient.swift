//
//  APIClient.swift
//  ClearDrive
//
//  Handles all communication with the Python backend server
//

import Foundation
import Combine
import SwiftUI

@MainActor
class APIClient: ObservableObject {
    @Published var baseURL: String {
        didSet {
            UserDefaults.standard.set(baseURL, forKey: "serverURL")
        }
    }

    @Published var isConnected = false

    /// Demo mode - uses mock data instead of real OBD connection
    @Published var isDemoMode: Bool {
        didSet {
            UserDefaults.standard.set(isDemoMode, forKey: "demoMode")
        }
    }

    init() {
        self.baseURL = UserDefaults.standard.string(forKey: "serverURL") ?? "http://localhost:8000"
        self.isDemoMode = UserDefaults.standard.bool(forKey: "demoMode")
    }

    // MARK: - Health Check

    func checkHealth() async throws -> Bool {
        let url = URL(string: "\(baseURL)/health")!
        let (_, response) = try await URLSession.shared.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse else { return false }
        isConnected = httpResponse.statusCode == 200
        return isConnected
    }

    // MARK: - OBD Endpoints

    /// Connect to OBD adapter on the server (or simulate in demo mode)
    func connectOBD(port: String? = nil) async throws -> Bool {
        // In demo mode, always succeed
        if isDemoMode {
            return true
        }

        let url = URL(string: "\(baseURL)/obd/connect")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let port = port {
            let body = ["port": port]
            request.httpBody = try JSONEncoder().encode(body)
        }

        let (data, _) = try await URLSession.shared.data(for: request)
        let response = try JSONDecoder().decode(OBDConnectResponse.self, from: data)
        return response.connected
    }

    /// Disconnect from OBD adapter
    func disconnectOBD() async throws {
        let url = URL(string: "\(baseURL)/obd/disconnect")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        _ = try await URLSession.shared.data(for: request)
    }

    /// Get live OBD data (RPM, Speed, Coolant)
    func getLiveData() async throws -> LiveOBDData {
        let url = URL(string: "\(baseURL)/obd/live")!
        let (data, _) = try await URLSession.shared.data(from: url)
        return try JSONDecoder().decode(LiveOBDData.self, from: data)
    }

    /// Check OBD adapter connection status
    func checkOBDStatus() async throws -> OBDStatusResponse {
        let url = URL(string: "\(baseURL)/obd/status")!
        let (data, _) = try await URLSession.shared.data(from: url)
        return try JSONDecoder().decode(OBDStatusResponse.self, from: data)
    }

    /// Read VIN from vehicle and decode
    func readVIN() async throws -> VehicleInfo {
        let url = URL(string: "\(baseURL)/obd/read-vin")!
        let (data, _) = try await URLSession.shared.data(from: url)
        let response = try JSONDecoder().decode(VINResponse.self, from: data)

        guard response.success else {
            throw APIError.vinReadFailed
        }

        return VehicleInfo(
            vin: response.vin,
            year: response.year ?? "",
            make: response.make ?? "",
            model: response.model ?? "",
            trim: response.trim,
            engine: response.engine,
            fuelType: response.fuelType,
            driveType: response.driveType,
            transmission: response.transmission,
            bodyStyle: response.bodyStyle
        )
    }

    // MARK: - Vehicle Endpoints

    /// Decode a VIN manually entered
    func decodeVIN(_ vin: String) async throws -> VehicleInfo {
        let url = URL(string: "\(baseURL)/vin/decode")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = ["vin": vin]
        request.httpBody = try JSONEncoder().encode(body)

        let (data, _) = try await URLSession.shared.data(for: request)
        let response = try JSONDecoder().decode(VINResponse.self, from: data)

        return VehicleInfo(
            vin: response.vin,
            year: response.year ?? "",
            make: response.make ?? "",
            model: response.model ?? "",
            trim: response.trim,
            engine: response.engine,
            fuelType: response.fuelType,
            driveType: response.driveType,
            transmission: response.transmission,
            bodyStyle: response.bodyStyle
        )
    }

    /// Get available trims for a vehicle
    func getTrims(year: String, make: String, model: String) async throws -> [TrimOption] {
        let url = URL(string: "\(baseURL)/trims")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = ["year": year, "make": make, "model": model]
        request.httpBody = try JSONEncoder().encode(body)

        let (data, _) = try await URLSession.shared.data(for: request)

        // Log raw JSON for debugging
        if let jsonString = String(data: data, encoding: .utf8) {
            print("[APIClient] Raw JSON response (first 2000 chars):")
            print(String(jsonString.prefix(2000)))
        }

        // Try to decode as wrapped response first, then as direct array
        do {
            let response = try JSONDecoder().decode(TrimsResponse.self, from: data)
            print("[APIClient] Successfully decoded \(response.trims.count) trims")
            for trim in response.trims {
                print("  - \(trim.name): hasBodyChoice=\(trim.hasBodyStyleChoice), bodyOptions=\(trim.bodyStyleOptions.count), hasTrans=\(trim.hasTransmissionChoice), transOptions=\(trim.transmissionOptions.count)")
                if trim.hasBodyStyleChoice { print("    bodyStyles: \(trim.bodyStyleOptions.map { $0.name })") }
                if trim.hasTransmissionChoice { print("    transmissions: \(trim.transmissionOptions.map { $0.label })") }
            }
            return response.trims
        } catch {
            // Try decoding as direct array
            do {
                let trims = try JSONDecoder().decode([TrimOption].self, from: data)
                print("[APIClient] Got \(trims.count) trims (direct array)")
                for trim in trims {
                    print("  - \(trim.name): hasBodyChoice=\(trim.hasBodyStyleChoice), hasTrans=\(trim.hasTransmissionChoice)")
                    if trim.hasBodyStyleChoice { print("    bodyStyles: \(trim.bodyStyleOptions.map { $0.name })") }
                    if trim.hasTransmissionChoice { print("    transmissions: \(trim.transmissionOptions.map { $0.label })") }
                }
                return trims
            } catch let arrayError {
                print("[APIClient] Failed to decode trims: \(error)")
                print("[APIClient] Also failed as array: \(arrayError)")
                print("[APIClient] Raw response: \(String(data: data, encoding: .utf8) ?? "unable to read")")
                throw error
            }
        }
    }

    /// Get vehicle image from CarsXE
    func getVehicleImage(year: String, make: String, model: String, trim: String, color: String? = nil) async throws -> String? {
        let url = URL(string: "\(baseURL)/vehicle-image")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        var body: [String: String] = [
            "year": year,
            "make": make,
            "model": model,
            "trim": trim
        ]
        if let color = color {
            body["color"] = color
        }
        request.httpBody = try JSONEncoder().encode(body)

        print("[APIClient] Fetching image for \(year) \(make) \(model) \(trim) color=\(color ?? "none")")

        let (data, _) = try await URLSession.shared.data(for: request)
        let response = try JSONDecoder().decode(VehicleImageResponse.self, from: data)

        print("[APIClient] Image response: success=\(response.success), url=\(response.url ?? "nil")")

        if response.success, let imageURL = response.url, !imageURL.isEmpty {
            // Return full URL (backend returns proxied URL)
            let fullURL = "\(baseURL)\(imageURL)"
            print("[APIClient] Full image URL: \(fullURL)")
            return fullURL
        }
        print("[APIClient] No image found")
        return nil
    }

    // MARK: - AI Diagnosis

    /// Interpret OBD data read locally from phone's Bluetooth connection
    /// Sends raw codes and live data to server for AI analysis
    func interpretOBDData(
        vehicle: VehicleInfo,
        trimId: String?,
        codes: [String],
        rpm: Int?,
        speed: Int?,
        coolantTemp: Int?,
        color: String? = nil
    ) async throws -> ScanResult {
        // Fetch vehicle image in parallel with diagnostic
        async let imageTask = getVehicleImage(
            year: vehicle.year,
            make: vehicle.make,
            model: vehicle.model,
            trim: vehicle.trim ?? "",
            color: color
        )

        // Build the interpret request with client-provided OBD data
        let url = URL(string: "\(baseURL)/interpret")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120

        // Use trim ID if provided, otherwise build from vehicle info
        let vehicleId = trimId ?? "\(vehicle.year)_\(vehicle.make)_\(vehicle.model)".lowercased().replacingOccurrences(of: " ", with: "_")

        let body: [String: Any] = [
            "vehicle_id": vehicleId,
            "trim": vehicle.trim ?? "",
            "use_live_obd": false,  // We're providing the data from client
            "client_codes": codes,  // DTCs read from phone's Bluetooth
            "client_rpm": rpm as Any,
            "client_speed": speed as Any,
            "client_coolant_temp": coolantTemp as Any,
            "obd_source": "Bluetooth (iOS)"
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        print("[APIClient] Sending client OBD data: \(codes.count) codes, rpm=\(rpm ?? -1)")

        let (data, _) = try await URLSession.shared.data(for: request)
        let response = try JSONDecoder().decode(InterpretResponse.self, from: data)

        // Get the image URL (may be nil)
        let imageURL = try? await imageTask

        // Convert response codes to DTCCode array
        let dtcCodes = response.codes.map { code in
            DTCCode(code: code, description: "", severity: response.safetyLevel)
        }

        // Build the full ScanResult
        var result = ScanResult(
            vehicle: vehicle,
            codes: dtcCodes,
            safetyRating: SafetyRating(from: response.safetyLevel),
            timestamp: Date()
        )

        // Populate all diagnostic sections
        result.dontPanic = response.dontPanic
        result.likelyCauses = response.likelyCauses
        result.symptoms = response.symptoms
        result.ifIgnored = response.ifIgnored
        result.quickChecks = response.quickChecks
        result.diyFix = response.diyFix
        result.urgency = response.urgency
        result.repairCost = response.repairCost
        result.knownIssues = response.knownIssues
        result.ownerReports = response.ownerReports

        // Vehicle details - use backend data, fallback to user's selection
        // Check for both nil AND empty strings before falling back
        print("[APIClient] Vehicle specs - response.engine: '\(response.engine ?? "nil")', vehicle.engine: '\(vehicle.engine ?? "nil")'")
        print("[APIClient] Vehicle specs - response.transmission: '\(response.transmission ?? "nil")', vehicle.transmission: '\(vehicle.transmission ?? "nil")'")
        result.engine = (response.engine?.isEmpty == false) ? response.engine : vehicle.engine
        result.transmission = (response.transmission?.isEmpty == false) ? response.transmission : vehicle.transmission
        result.drive = (response.drive?.isEmpty == false) ? response.drive : vehicle.driveType
        result.fuelType = response.fuelType
        print("[APIClient] Final result.transmission: '\(result.transmission ?? "nil")'")
        result.isTurbo = response.turbocharged ?? false
        result.isSupercharged = response.supercharged ?? false
        result.isHybrid = response.hybrid ?? false
        result.isElectric = response.electric ?? false

        // Data sources and OBD info
        result.dataSources = response.dataSources ?? []
        result.obdSource = "Bluetooth (iOS)"

        // Live data (from client)
        result.rpm = rpm
        result.speed = speed
        result.coolantTemp = coolantTemp

        // Vehicle image - use backend URL, fallback to separate image fetch
        if let backendImageURL = response.vehicleImageURL, !backendImageURL.isEmpty {
            if backendImageURL.starts(with: "/") {
                result.vehicleImageURL = baseURL + backendImageURL
            } else {
                result.vehicleImageURL = backendImageURL
            }
        } else {
            result.vehicleImageURL = imageURL
        }

        return result
    }

    /// Full scan using the /interpret endpoint
    /// This endpoint handles everything: OBD reading, AI diagnosis, cost estimates
    func performFullScan(vehicle: VehicleInfo, trimId: String? = nil, color: String? = nil) async throws -> ScanResult {
        // Fetch vehicle image in parallel with diagnostic
        async let imageTask = getVehicleImage(
            year: vehicle.year,
            make: vehicle.make,
            model: vehicle.model,
            trim: vehicle.trim ?? "",
            color: color
        )

        // Build the interpret request
        let url = URL(string: "\(baseURL)/interpret")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120 // AI + data gathering can take time

        // Use trim ID if provided, otherwise build from vehicle info
        let vehicleId = trimId ?? "\(vehicle.year)_\(vehicle.make)_\(vehicle.model)".lowercased().replacingOccurrences(of: " ", with: "_")

        let body: [String: Any] = [
            "vehicle_id": vehicleId,
            "trim": vehicle.trim ?? "",
            "use_live_obd": !isDemoMode
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, _) = try await URLSession.shared.data(for: request)
        let response = try JSONDecoder().decode(InterpretResponse.self, from: data)

        // Get the image URL (may be nil)
        let imageURL = try? await imageTask

        // Convert response codes to DTCCode array
        let codes = response.codes.map { code in
            DTCCode(code: code, description: "", severity: response.safetyLevel)
        }

        // Build the full ScanResult
        var result = ScanResult(
            vehicle: vehicle,
            codes: codes,
            safetyRating: SafetyRating(from: response.safetyLevel),
            timestamp: Date()
        )

        // Populate all diagnostic sections
        result.dontPanic = response.dontPanic
        result.likelyCauses = response.likelyCauses
        result.symptoms = response.symptoms
        result.ifIgnored = response.ifIgnored
        result.quickChecks = response.quickChecks
        result.diyFix = response.diyFix
        result.urgency = response.urgency
        result.repairCost = response.repairCost
        result.knownIssues = response.knownIssues
        result.ownerReports = response.ownerReports

        // Vehicle details - use backend data, fallback to user's selection
        // Check for both nil AND empty strings before falling back
        print("[APIClient] Vehicle specs - response.engine: '\(response.engine ?? "nil")', vehicle.engine: '\(vehicle.engine ?? "nil")'")
        print("[APIClient] Vehicle specs - response.transmission: '\(response.transmission ?? "nil")', vehicle.transmission: '\(vehicle.transmission ?? "nil")'")
        result.engine = (response.engine?.isEmpty == false) ? response.engine : vehicle.engine
        result.transmission = (response.transmission?.isEmpty == false) ? response.transmission : vehicle.transmission
        result.drive = (response.drive?.isEmpty == false) ? response.drive : vehicle.driveType
        result.fuelType = response.fuelType
        print("[APIClient] Final result.transmission: '\(result.transmission ?? "nil")'")
        result.isTurbo = response.turbocharged ?? false
        result.isSupercharged = response.supercharged ?? false
        result.isHybrid = response.hybrid ?? false
        result.isElectric = response.electric ?? false

        // Data sources and OBD info
        result.dataSources = response.dataSources ?? []
        result.obdSource = response.obdSource

        // Live data
        result.rpm = response.rpm
        result.speed = response.speed
        result.coolantTemp = response.coolantTemp

        // Vehicle image - use backend URL (from /interpret), fallback to separate image fetch
        if let backendImageURL = response.vehicleImageURL, !backendImageURL.isEmpty {
            // Backend returns relative URL like /image-proxy?url=...
            // Prepend base URL to make it absolute
            if backendImageURL.starts(with: "/") {
                result.vehicleImageURL = baseURL + backendImageURL
            } else {
                result.vehicleImageURL = backendImageURL
            }
            print("[APIClient] Using backend image URL: \(result.vehicleImageURL ?? "nil")")
        } else {
            // Fallback to separate image fetch
            result.vehicleImageURL = imageURL
            print("[APIClient] Using fallback image URL: \(result.vehicleImageURL ?? "nil")")
        }

        return result
    }

    // MARK: - Follow-up Questions

    /// Ask a follow-up question about the diagnosis
    func askFollowUp(
        question: String,
        context: [String: Any],
        history: [[String: String]]
    ) async throws -> String {
        let url = URL(string: "\(baseURL)/followup")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 60

        let body: [String: Any] = [
            "question": question,
            "context": context,
            "history": history
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, _) = try await URLSession.shared.data(for: request)
        let response = try JSONDecoder().decode(FollowUpResponse.self, from: data)
        return response.answer
    }
}

struct FollowUpResponse: Codable {
    let answer: String
}

// MARK: - API Errors

enum APIError: LocalizedError {
    case vinReadFailed
    case connectionFailed
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .vinReadFailed: return "Failed to read VIN from vehicle"
        case .connectionFailed: return "Could not connect to server"
        case .invalidResponse: return "Invalid response from server"
        }
    }
}

// MARK: - Response Models

struct OBDConnectResponse: Codable {
    let connected: Bool
    let port: String?
}

struct OBDStatusResponse: Codable {
    let connected: Bool
    let port: String?
    let message: String?
    let availablePorts: [OBDPort]?

    enum CodingKeys: String, CodingKey {
        case connected, port, message
        case availablePorts = "available_ports"
    }
}

struct OBDPort: Codable, Identifiable {
    var id: String { device }
    let device: String
    let description: String?
}

struct VINResponse: Codable {
    let success: Bool
    let vin: String?
    let year: String?
    let make: String?
    let model: String?
    let trim: String?
    let engine: String?
    let fuelType: String?
    let driveType: String?
    let transmission: String?
    let bodyStyle: String?

    enum CodingKeys: String, CodingKey {
        case success, vin, year, make, model, trim, engine
        case fuelType = "fuel_type"
        case driveType = "drive_type"
        case transmission
        case bodyStyle = "body_style"
    }
}

struct TrimsResponse: Decodable {
    let trims: [TrimOption]
}

// Helper struct for body style options from API
struct BodyStyleOption: Codable, Identifiable {
    var id: String { name }
    let name: String
    let fullName: String?

    enum CodingKeys: String, CodingKey {
        case name
        case fullName = "full_name"
    }
}

// Helper struct for transmission options from API
struct TransmissionOption: Codable, Identifiable {
    var id: String { name }
    let name: String
    let label: String

    enum CodingKeys: String, CodingKey {
        case name, label
    }
}

// Helper struct for color options from API
struct TrimColor: Codable, Identifiable, Equatable {
    var id: String { name }
    let name: String
    let rgb: String

    var color: Color {
        let components = rgb.split(separator: ",").compactMap { Double($0.trimmingCharacters(in: .whitespaces)) }
        guard components.count == 3 else { return .gray }
        return Color(red: components[0] / 255, green: components[1] / 255, blue: components[2] / 255)
    }
}

struct TrimOption: Identifiable, Decodable {
    let id: String
    let name: String
    let engine: String?
    let bodyStyle: String?
    let transmission: String?
    let driveType: String?
    let bodyStyleOptions: [BodyStyleOption]
    let transmissionOptions: [TransmissionOption]
    let hasBodyStyleChoice: Bool
    let hasTransmissionChoice: Bool

    // Performance specs
    let horsepower: String?
    let torque: String?

    // Fuel economy
    let mpgCity: String?
    let mpgHighway: String?
    let mpgCombined: String?
    let tankCapacity: String?
    let fuelType: String?

    // Colors
    let colorsExterior: [TrimColor]
    let colorsInterior: [TrimColor]

    // Vehicle type flags
    let isTruck: Bool
    let isElectric: Bool
    let isPluginHybrid: Bool

    enum CodingKeys: String, CodingKey {
        case id, name, engine
        case bodyStyle = "body_style"
        case transmission, drivetrain
        case driveType = "drive_type"
        case bodyStyleOptions = "body_style_options"
        case transmissionOptions = "transmission_options"
        case hasBodyStyleChoice = "has_body_style_choice"
        case hasTransmissionChoice = "has_transmission_choice"
        case horsepower, torque
        case mpgCity = "mpg_city"
        case mpgHighway = "mpg_highway"
        case mpgCombined = "mpg_combined"
        case tankCapacity = "tank_capacity"
        case fuelType = "fuel_type"
        case colorsExterior = "colors_exterior"
        case colorsInterior = "colors_interior"
        case isTruck = "is_truck"
        case isElectric = "is_electric"
        case isPluginHybrid = "is_plugin_hybrid"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        // Handle both string and int IDs from API
        if let intId = try? container.decode(Int.self, forKey: .id) {
            id = String(intId)
        } else {
            id = try container.decode(String.self, forKey: .id)
        }
        name = try container.decode(String.self, forKey: .name)
        engine = try container.decodeIfPresent(String.self, forKey: .engine)
        bodyStyle = try container.decodeIfPresent(String.self, forKey: .bodyStyle)
        transmission = try container.decodeIfPresent(String.self, forKey: .transmission)

        // driveType can be "drive_type" or "drivetrain"
        if let dt = try container.decodeIfPresent(String.self, forKey: .driveType) {
            driveType = dt
        } else {
            driveType = try container.decodeIfPresent(String.self, forKey: .drivetrain)
        }

        // body_style_options - decode as array of objects
        do {
            bodyStyleOptions = try container.decode([BodyStyleOption].self, forKey: .bodyStyleOptions)
            print("[TrimOption] Decoded \(bodyStyleOptions.count) body style options for \(name): \(bodyStyleOptions.map { $0.name })")
        } catch {
            print("[TrimOption] Failed to decode body_style_options for \(name): \(error)")
            bodyStyleOptions = []
        }

        // transmission_options - decode as array of TransmissionOption objects
        do {
            transmissionOptions = try container.decode([TransmissionOption].self, forKey: .transmissionOptions)
            print("[TrimOption] Decoded \(transmissionOptions.count) transmission options for \(name): \(transmissionOptions.map { $0.label })")
        } catch {
            print("[TrimOption] Failed to decode transmission_options for \(name): \(error)")
            transmissionOptions = []
        }

        // Parse the choice flags from API
        hasBodyStyleChoice = (try? container.decode(Bool.self, forKey: .hasBodyStyleChoice)) ?? (bodyStyleOptions.count > 1)
        hasTransmissionChoice = (try? container.decode(Bool.self, forKey: .hasTransmissionChoice)) ?? (transmissionOptions.count > 1)

        // Performance specs
        horsepower = try container.decodeIfPresent(String.self, forKey: .horsepower)
        torque = try container.decodeIfPresent(String.self, forKey: .torque)

        // Fuel economy
        mpgCity = try container.decodeIfPresent(String.self, forKey: .mpgCity)
        mpgHighway = try container.decodeIfPresent(String.self, forKey: .mpgHighway)
        mpgCombined = try container.decodeIfPresent(String.self, forKey: .mpgCombined)
        tankCapacity = try container.decodeIfPresent(String.self, forKey: .tankCapacity)
        fuelType = try container.decodeIfPresent(String.self, forKey: .fuelType)

        // Colors
        colorsExterior = (try? container.decode([TrimColor].self, forKey: .colorsExterior)) ?? []
        colorsInterior = (try? container.decode([TrimColor].self, forKey: .colorsInterior)) ?? []

        // Vehicle type flags
        isTruck = (try? container.decode(Bool.self, forKey: .isTruck)) ?? false
        isElectric = (try? container.decode(Bool.self, forKey: .isElectric)) ?? false
        isPluginHybrid = (try? container.decode(Bool.self, forKey: .isPluginHybrid)) ?? false

        print("[TrimOption] \(name): hasBodyStyleChoice=\(hasBodyStyleChoice), hasTransmissionChoice=\(hasTransmissionChoice)")
    }

    /// Check if this trim matches the given OBD2 specs
    func matchesSpecs(engine obdEngine: String?, driveType obdDrive: String?, transmission obdTrans: String?) -> Bool {
        // If we don't have OBD data for a field, consider it a match
        // If we do have OBD data, check if trim's value matches (case-insensitive, contains)

        if let obdEngine = obdEngine, let trimEngine = self.engine {
            // Check if engines are compatible (e.g., "5.7L" matches "5.7L V8 HEMI")
            let obdNormalized = obdEngine.lowercased()
            let trimNormalized = trimEngine.lowercased()
            if !trimNormalized.contains(obdNormalized) && !obdNormalized.contains(trimNormalized) {
                // Try matching just displacement (e.g., "5.7" or "2.0")
                let obdDisplacement = extractDisplacement(from: obdEngine)
                let trimDisplacement = extractDisplacement(from: trimEngine)
                if let obd = obdDisplacement, let trim = trimDisplacement, obd != trim {
                    return false
                }
            }
        }

        if let obdDrive = obdDrive, let trimDrive = self.driveType {
            let obdNormalized = normalizeDriveType(obdDrive)
            let trimNormalized = normalizeDriveType(trimDrive)
            if obdNormalized != trimNormalized && !obdNormalized.isEmpty && !trimNormalized.isEmpty {
                return false
            }
        }

        if let obdTrans = obdTrans, let trimTrans = self.transmission {
            let obdNormalized = normalizeTransmission(obdTrans)
            let trimNormalized = normalizeTransmission(trimTrans)
            if obdNormalized != trimNormalized && !obdNormalized.isEmpty && !trimNormalized.isEmpty {
                return false
            }
        }

        return true
    }

    private func extractDisplacement(from engine: String) -> String? {
        // Extract displacement like "5.7" from "5.7L V8 HEMI"
        let pattern = #"(\d+\.?\d*)L?"#
        if let match = engine.range(of: pattern, options: .regularExpression) {
            var result = String(engine[match])
            result = result.replacingOccurrences(of: "L", with: "")
            return result
        }
        return nil
    }

    private func normalizeDriveType(_ drive: String) -> String {
        let lower = drive.lowercased()
        if lower.contains("rear") || lower.contains("rwd") { return "rwd" }
        if lower.contains("front") || lower.contains("fwd") { return "fwd" }
        if lower.contains("all") || lower.contains("awd") { return "awd" }
        if lower.contains("4wd") || lower.contains("4x4") || lower.contains("four") { return "4wd" }
        return lower
    }

    private func normalizeTransmission(_ trans: String) -> String {
        let lower = trans.lowercased()
        if lower.contains("manual") || lower.contains("mt") { return "manual" }
        if lower.contains("auto") || lower.contains("at") { return "automatic" }
        if lower.contains("cvt") { return "cvt" }
        if lower.contains("dct") || lower.contains("dual") { return "dct" }
        return lower
    }
}

struct VehicleImageResponse: Codable {
    let success: Bool
    let url: String?
    let width: Int?
    let height: Int?
}

/// Response from /interpret endpoint
struct InterpretResponse: Codable {
    let codes: [String]
    let vehicle: String
    let engine: String?
    let drive: String?
    let fuelType: String?
    let transmission: String?
    let safetyLevel: String
    let safetyMeaning: String?
    let dontPanic: String?
    let likelyCauses: String?
    let symptoms: String?
    let ifIgnored: String?
    let quickChecks: String?
    let diyFix: String?
    let urgency: String?
    let repairCost: String?
    let knownIssues: String?
    let ownerReports: String?
    let dataSources: [String]?
    let obdSource: String?
    let rpm: Int?
    let speed: Int?
    let coolantTemp: Int?
    let supercharged: Bool?
    let turbocharged: Bool?
    let hybrid: Bool?
    let electric: Bool?
    let vehicleImageURL: String?

    enum CodingKeys: String, CodingKey {
        case codes, vehicle, engine, drive, transmission
        case fuelType = "fuel_type"
        case safetyLevel = "safety_level"
        case safetyMeaning = "safety_meaning"
        case dontPanic = "dont_panic"
        case likelyCauses = "likely_causes"
        case symptoms
        case ifIgnored = "if_ignored"
        case quickChecks = "quick_checks"
        case diyFix = "diy_fix"
        case urgency
        case repairCost = "repair_cost"
        case knownIssues = "known_issues"
        case ownerReports = "owner_reports"
        case dataSources = "data_sources"
        case obdSource = "obd_source"
        case rpm, speed
        case coolantTemp = "coolant_temp"
        case supercharged, turbocharged, hybrid, electric
        case vehicleImageURL
    }
}
