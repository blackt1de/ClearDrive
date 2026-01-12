import Foundation

/// Client for communicating with the ClearDrive server
class APIClient: ObservableObject {
    @Published var baseURL: String {
        didSet {
            UserDefaults.standard.set(baseURL, forKey: "serverURL")
        }
    }

    init() {
        self.baseURL = UserDefaults.standard.string(forKey: "serverURL") ?? "http://192.168.1.254:8000"
    }

    // MARK: - Health Check

    func checkHealth() async throws -> Bool {
        let url = URL(string: "\(baseURL)/health")!
        let (_, response) = try await URLSession.shared.data(from: url)

        guard let httpResponse = response as? HTTPURLResponse else {
            return false
        }

        return httpResponse.statusCode == 200
    }

    // MARK: - Vehicle Data

    func getTrims(year: String, make: String, model: String) async throws -> [Trim] {
        var components = URLComponents(string: "\(baseURL)/vehicle/trims")!
        components.queryItems = [
            URLQueryItem(name: "year", value: year),
            URLQueryItem(name: "make", value: make),
            URLQueryItem(name: "model", value: model)
        ]

        let (data, _) = try await URLSession.shared.data(from: components.url!)
        let response = try JSONDecoder().decode(TrimsResponse.self, from: data)
        return response.trims
    }

    func getVehicleImage(year: String, make: String, model: String, trim: String = "") async throws -> URL? {
        var components = URLComponents(string: "\(baseURL)/vehicle/image")!
        components.queryItems = [
            URLQueryItem(name: "year", value: year),
            URLQueryItem(name: "make", value: make),
            URLQueryItem(name: "model", value: model),
            URLQueryItem(name: "trim", value: trim)
        ]

        let (data, _) = try await URLSession.shared.data(from: components.url!)
        let response = try JSONDecoder().decode(ImageResponse.self, from: data)

        if let urlString = response.url {
            return URL(string: urlString)
        }
        return nil
    }

    // MARK: - Diagnosis

    func diagnose(year: String, make: String, model: String, trim: String, codes: [String]) async throws -> ScanResult {
        let url = URL(string: "\(baseURL)/interpret")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = DiagnoseRequest(
            year: year,
            make: make,
            model: model,
            trim: trim,
            codes: codes.map { DTCCodeInput(code: $0) }
        )

        request.httpBody = try JSONEncoder().encode(body)

        let (data, _) = try await URLSession.shared.data(for: request)
        let response = try JSONDecoder().decode(DiagnoseResponse.self, from: data)

        // Get vehicle image
        let imageURL = try? await getVehicleImage(year: year, make: make, model: model, trim: trim)

        return ScanResult(
            vehicleDescription: "\(year) \(make) \(model) \(trim)".trimmingCharacters(in: .whitespaces),
            vehicleImageURL: imageURL,
            codes: response.codes.map { DTCCode(code: $0.code, description: $0.description, severity: $0.severity) },
            diagnosis: response.diagnosis,
            safetyRating: SafetyRating(from: response.safetyRating),
            estimatedCosts: response.estimatedCosts.map {
                EstimatedCosts(parts: $0.parts, labor: $0.labor, total: $0.total)
            }
        )
    }

    // MARK: - History

    func getHistory() async throws -> [ScanHistory] {
        let url = URL(string: "\(baseURL)/history")!
        let (data, _) = try await URLSession.shared.data(from: url)
        let response = try JSONDecoder().decode(HistoryResponse.self, from: data)

        return response.scans.map { scan in
            ScanHistory(
                id: scan.id,
                vehicleDescription: "\(scan.year) \(scan.make) \(scan.model)",
                date: ISO8601DateFormatter().date(from: scan.timestamp) ?? Date(),
                codeCount: scan.codeCount,
                safetyRating: scan.safetyRating
            )
        }
    }
}

// MARK: - Request Models

struct DiagnoseRequest: Encodable {
    let year: String
    let make: String
    let model: String
    let trim: String
    let codes: [DTCCodeInput]
}

struct DTCCodeInput: Encodable {
    let code: String
}

// MARK: - Response Models

struct TrimsResponse: Decodable {
    let trims: [Trim]
}

struct ImageResponse: Decodable {
    let url: String?
    let width: Int?
    let height: Int?
}

struct DiagnoseResponse: Decodable {
    let codes: [DiagnoseCodeResponse]
    let diagnosis: String?
    let safetyRating: String
    let estimatedCosts: EstimatedCostsResponse?

    enum CodingKeys: String, CodingKey {
        case codes
        case diagnosis
        case safetyRating = "safety_rating"
        case estimatedCosts = "estimated_costs"
    }
}

struct DiagnoseCodeResponse: Decodable {
    let code: String
    let description: String
    let severity: String?
}

struct EstimatedCostsResponse: Decodable {
    let parts: String
    let labor: String
    let total: String
}

struct HistoryResponse: Decodable {
    let scans: [HistoryScanResponse]
}

struct HistoryScanResponse: Decodable {
    let id: String
    let year: String
    let make: String
    let model: String
    let timestamp: String
    let codeCount: Int
    let safetyRating: String

    enum CodingKeys: String, CodingKey {
        case id
        case year
        case make
        case model
        case timestamp
        case codeCount = "code_count"
        case safetyRating = "safety_rating"
    }
}
