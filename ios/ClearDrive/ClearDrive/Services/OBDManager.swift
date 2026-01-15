//
//  OBDManager.swift
//  ClearDrive
//
//  Handles Bluetooth communication with ELM327 OBD-II adapters
//

import Foundation
import CoreBluetooth
import Combine

/// OBD-II Bluetooth Manager - connects to ELM327 adapters and reads vehicle data
@MainActor
class OBDManager: NSObject, ObservableObject {

    // MARK: - Published State

    @Published var connectionState: OBDConnectionState = .disconnected
    @Published var discoveredDevices: [OBDDevice] = []
    @Published var connectedDevice: OBDDevice?
    @Published var lastError: String?

    // Live data
    @Published var currentRPM: Int?
    @Published var currentSpeed: Int?
    @Published var coolantTemp: Int?
    @Published var voltage: Double?

    // MARK: - Private Properties

    private var centralManager: CBCentralManager!
    private var connectedPeripheral: CBPeripheral?
    private var writeCharacteristic: CBCharacteristic?
    private var readCharacteristic: CBCharacteristic?

    private var responseBuffer = ""
    private var responseCompletion: ((String) -> Void)?
    private var responseTimer: Timer?

    // Command serialization - only one command can be in-flight at a time
    private let commandLock = CommandLock()

    // ELM327 UUIDs (common for most BLE adapters)
    private let serviceUUIDs: [CBUUID] = [
        CBUUID(string: "FFE0"),      // Common ELM327 BLE service
        CBUUID(string: "FFF0"),      // Alternative service
        CBUUID(string: "18F0"),      // OBD service
        CBUUID(string: "E7810A71-73AE-499D-8C15-FAA9AEF0C3F2") // Vgate/iCar
    ]

    private let characteristicUUIDs: [CBUUID] = [
        CBUUID(string: "FFE1"),      // Common read/write characteristic
        CBUUID(string: "FFF1"),      // Alternative
        CBUUID(string: "BEF8D6C9-9C21-4C9E-B632-BD58C1009F9F") // Vgate notify
    ]

    // MARK: - Initialization

    override init() {
        super.init()
        centralManager = CBCentralManager(delegate: nil, queue: nil)
        centralManager.delegate = self
    }

    // MARK: - Public Methods

    /// Start scanning for OBD devices
    func startScanning() {
        guard centralManager.state == .poweredOn else {
            lastError = "Bluetooth is not available"
            return
        }

        print("[OBDManager] Starting scan for devices...")
        connectionState = .scanning
        discoveredDevices.removeAll()

        // Scan for devices with OBD service UUIDs, or all devices
        centralManager.scanForPeripherals(withServices: nil, options: [
            CBCentralManagerScanOptionAllowDuplicatesKey: false
        ])

        // Stop scanning after 10 seconds
        DispatchQueue.main.asyncAfter(deadline: .now() + 10) { [weak self] in
            self?.stopScanning()
        }
    }

    /// Stop scanning for devices
    func stopScanning() {
        centralManager.stopScan()
        if connectionState == .scanning {
            connectionState = .disconnected
        }
        print("[OBDManager] Stopped scanning. Found \(discoveredDevices.count) devices")
    }

    /// Connect to a specific OBD device
    func connect(to device: OBDDevice) {
        print("[OBDManager] Connecting to \(device.name)...")
        connectionState = .connecting
        centralManager.connect(device.peripheral, options: nil)
    }

    /// Disconnect from current device
    func disconnect() {
        if let peripheral = connectedPeripheral {
            centralManager.cancelPeripheralConnection(peripheral)
        }
        resetConnection()
    }

    /// Initialize the ELM327 adapter
    func initializeAdapter() async -> Bool {
        print("[OBDManager] Initializing ELM327 adapter...")

        do {
            // Reset adapter
            let _ = try await sendCommand("ATZ", timeout: 3.0)
            try await Task.sleep(nanoseconds: 500_000_000) // 500ms delay

            // Disable echo
            let _ = try await sendCommand("ATE0")

            // Disable line feeds
            let _ = try await sendCommand("ATL0")

            // Disable spaces in responses
            let _ = try await sendCommand("ATS0")

            // Set protocol to auto
            let _ = try await sendCommand("ATSP0")

            // Disable headers
            let _ = try await sendCommand("ATH0")

            print("[OBDManager] Adapter initialized successfully")
            connectionState = .ready
            return true
        } catch {
            print("[OBDManager] Initialization failed: \(error)")
            lastError = "Failed to initialize adapter"
            return false
        }
    }

    // MARK: - OBD Reading Methods

    /// Read VIN from vehicle
    func readVIN() async -> String? {
        do {
            // Mode 09 PID 02 = VIN (needs longer timeout - multi-line response)
            let response = try await sendCommand("0902", timeout: 8.0)
            let vin = parseVIN(response)
            return vin
        } catch {
            return nil
        }
    }

    /// Read Diagnostic Trouble Codes (DTCs)
    func readDTCs() async -> [String] {
        print("[OBDManager] Reading DTCs...")

        do {
            // Mode 03 = Read stored DTCs
            let response = try await sendCommand("03")
            let codes = parseDTCs(response)
            print("[OBDManager] Found \(codes.count) DTCs: \(codes)")
            return codes
        } catch {
            print("[OBDManager] Failed to read DTCs: \(error)")
            return []
        }
    }

    /// Read pending DTCs
    func readPendingDTCs() async -> [String] {
        do {
            // Mode 07 = Read pending DTCs
            let response = try await sendCommand("07")
            return parseDTCs(response)
        } catch {
            return []
        }
    }

    /// Read current RPM
    func readRPM() async -> Int? {
        do {
            // Mode 01 PID 0C = RPM
            let response = try await sendCommand("010C")
            if let rpm = parseRPM(response) {
                await MainActor.run { currentRPM = rpm }
                return rpm
            }
        } catch {
            print("[OBDManager] Failed to read RPM: \(error)")
        }
        return nil
    }

    /// Read current speed
    func readSpeed() async -> Int? {
        do {
            // Mode 01 PID 0D = Vehicle speed
            let response = try await sendCommand("010D")
            if let speed = parseSpeed(response) {
                await MainActor.run { currentSpeed = speed }
                return speed
            }
        } catch {
            print("[OBDManager] Failed to read speed: \(error)")
        }
        return nil
    }

    /// Read coolant temperature
    func readCoolantTemp() async -> Int? {
        do {
            // Mode 01 PID 05 = Coolant temp
            let response = try await sendCommand("0105")
            if let temp = parseCoolantTemp(response) {
                await MainActor.run { coolantTemp = temp }
                return temp
            }
        } catch {
            print("[OBDManager] Failed to read coolant temp: \(error)")
        }
        return nil
    }

    /// Read odometer (may not be supported on all vehicles)
    func readOdometer() async -> Double? {
        do {
            // Mode 01 PID A6 = Odometer (not universally supported)
            let response = try await sendCommand("01A6")
            if let odometer = parseOdometer(response) {
                return odometer
            }
        } catch {
            print("[OBDManager] Failed to read odometer: \(error)")
        }
        return nil
    }

    /// Read fuel level percentage (0-100%)
    func readFuelLevel() async -> Int? {
        do {
            // Mode 01 PID 2F = Fuel Tank Level Input
            let response = try await sendCommand("012F")
            if let level = parseFuelLevel(response) {
                return level
            }
        } catch {
            print("[OBDManager] Failed to read fuel level: \(error)")
        }
        return nil
    }

    /// Read all live data sequentially (OBD adapters only support one command at a time)
    func readLiveData() async -> (rpm: Int?, speed: Int?, coolant: Int?, odometer: Double?, fuelLevel: Int?) {
        // IMPORTANT: Must execute sequentially - OBD adapter can only handle one command at a time
        let rpm = await readRPM()
        let speed = await readSpeed()
        let coolant = await readCoolantTemp()
        let odometer = await readOdometer()
        let fuelLevel = await readFuelLevel()

        print("[OBD-LIVE] RPM=\(rpm ?? -1) Speed=\(speed ?? -1) Coolant=\(coolant ?? -1) Odo=\(odometer ?? -1) Fuel=\(fuelLevel ?? -1)%")
        return (rpm, speed, coolant, odometer, fuelLevel)
    }

    /// Fast live data read - only essential real-time PIDs (RPM, speed, coolant)
    /// Use this for continuous polling to reduce latency
    func readLiveDataFast() async -> (rpm: Int?, speed: Int?, coolant: Int?) {
        // Use shorter timeout (0.8s) for faster response - these PIDs are fast
        let rpm = await readPIDFast("010C", parser: parseRPM)
        let speed = await readPIDFast("010D", parser: parseSpeed)
        let coolant = await readPIDFast("0105", parser: parseCoolantTemp)
        return (rpm, speed, coolant)
    }

    /// Fast PID read with shorter timeout for live polling
    private func readPIDFast<T>(_ command: String, parser: (String) -> T?) async -> T? {
        do {
            let response = try await sendCommand(command, timeout: 0.8)
            return parser(response)
        } catch {
            return nil
        }
    }

    /// Clear DTCs (use with caution)
    func clearDTCs() async -> Bool {
        do {
            // Mode 04 = Clear DTCs and freeze frame
            let response = try await sendCommand("04")
            return response.contains("44") || response.contains("OK")
        } catch {
            return false
        }
    }

    // MARK: - Command Sending

    private var continuationResumed = false

    private func sendCommand(_ command: String, timeout: TimeInterval = 2.0) async throws -> String {
        // Acquire lock to ensure only one command runs at a time
        await commandLock.acquire()
        defer { Task { await commandLock.release() } }

        guard let characteristic = writeCharacteristic,
              let peripheral = connectedPeripheral else {
            throw OBDError.notConnected
        }

        return try await withCheckedThrowingContinuation { continuation in
            continuationResumed = false
            responseBuffer = ""

            responseCompletion = { [weak self] response in
                guard let self = self, !self.continuationResumed else { return }
                self.continuationResumed = true
                self.responseTimer?.invalidate()
                continuation.resume(returning: response)
            }

            // Set timeout
            responseTimer?.invalidate()
            responseTimer = Timer.scheduledTimer(withTimeInterval: timeout, repeats: false) { [weak self] _ in
                guard let self = self else { return }
                Task { @MainActor in
                    guard !self.continuationResumed else { return }
                    self.continuationResumed = true
                    self.responseCompletion = nil
                    continuation.resume(throwing: OBDError.timeout)
                }
            }

            // Send command with carriage return
            // Use correct write type based on characteristic properties
            let data = "\(command)\r".data(using: .utf8)!
            let writeType: CBCharacteristicWriteType = characteristic.properties.contains(.write) ? .withResponse : .withoutResponse
            print("[OBD-DEBUG] Sending: \(command) (writeType: \(writeType == .withResponse ? "withResponse" : "withoutResponse"))")
            peripheral.writeValue(data, for: characteristic, type: writeType)
        }
    }

    private func resetConnection() {
        connectedPeripheral = nil
        writeCharacteristic = nil
        readCharacteristic = nil
        connectedDevice = nil
        connectionState = .disconnected
        currentRPM = nil
        currentSpeed = nil
        coolantTemp = nil
    }

    // MARK: - Response Parsing

    private func parseVIN(_ response: String) -> String? {
        print("[OBD-DEBUG] Parsing VIN from response: \(response)")

        // Handle ISO 15765-4 multi-frame format (CAN protocol)
        // Example: 014\r0:490201574155\r1:464641464C3246\r2:4E303337323533\r\r>
        // Or older format: 49 02 01 XX XX XX ...

        var vinHex = ""

        // Check for multi-frame format (lines starting with 0:, 1:, 2:, etc.)
        let lines = response.components(separatedBy: CharacterSet(charactersIn: "\r\n"))
        var hasMultiFrame = false

        for line in lines {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            // Match frame format: "0:490201574155" or "1:464641464C3246"
            if trimmed.count >= 2 && trimmed.contains(":") {
                let parts = trimmed.split(separator: ":", maxSplits: 1)
                if parts.count == 2, let frameNum = Int(parts[0]) {
                    hasMultiFrame = true
                    var frameData = String(parts[1])

                    // First frame (0:) contains header 490201, skip it
                    if frameNum == 0 {
                        // Remove 490201 header (mode 09, PID 02, line 01)
                        if frameData.hasPrefix("490201") {
                            frameData = String(frameData.dropFirst(6))
                        } else if frameData.hasPrefix("4902") {
                            frameData = String(frameData.dropFirst(4))
                        }
                    }
                    vinHex += frameData
                }
            }
        }

        // Fall back to old format if no multi-frame detected
        if !hasMultiFrame {
            let cleaned = response
                .replacingOccurrences(of: " ", with: "")
                .replacingOccurrences(of: "\r", with: "")
                .replacingOccurrences(of: "\n", with: "")
                .replacingOccurrences(of: ">", with: "")

            vinHex = cleaned
            if let range = vinHex.range(of: "4902") {
                vinHex = String(vinHex[range.upperBound...])
            }

            // Remove line numbers
            for i in 1...5 {
                vinHex = vinHex.replacingOccurrences(of: "49020\(i)", with: "")
            }
        }

        print("[OBD-DEBUG] VIN hex after parsing: \(vinHex)")

        // Convert hex to ASCII
        var vin = ""
        var index = vinHex.startIndex
        while index < vinHex.endIndex {
            let nextIndex = vinHex.index(index, offsetBy: 2, limitedBy: vinHex.endIndex) ?? vinHex.endIndex
            if nextIndex <= vinHex.endIndex {
                let hexByte = String(vinHex[index..<nextIndex])
                if let byte = UInt8(hexByte, radix: 16), byte >= 32, byte <= 126 {
                    vin.append(Character(UnicodeScalar(byte)))
                }
            }
            index = nextIndex
        }

        print("[OBD-DEBUG] Parsed VIN: \(vin) (length: \(vin.count))")

        // VIN should be 17 characters
        return vin.count >= 17 ? String(vin.prefix(17)) : nil
    }

    private func parseDTCs(_ response: String) -> [String] {
        var codes: [String] = []

        // Split response by lines to handle multiple ECU responses
        // Format: "4300\r4300\r" = two ECUs both reporting no codes
        // Format: "430143\r" = one ECU with code P0143
        let lines = response.components(separatedBy: CharacterSet(charactersIn: "\r\n"))

        for line in lines {
            let cleaned = line
                .replacingOccurrences(of: " ", with: "")
                .replacingOccurrences(of: ">", with: "")
                .trimmingCharacters(in: .whitespaces)

            // Skip empty lines or non-DTC responses
            guard cleaned.hasPrefix("43") || cleaned.hasPrefix("47") else { continue }

            // Remove the mode byte (43 for stored DTCs, 47 for pending)
            let hex = String(cleaned.dropFirst(2))

            // "00" after mode byte means no codes stored
            if hex == "00" || hex.isEmpty {
                continue
            }

            // Each DTC is 4 hex characters (2 bytes)
            var index = hex.startIndex
            while index < hex.endIndex {
                guard let endIndex = hex.index(index, offsetBy: 4, limitedBy: hex.endIndex) else {
                    break
                }
                let dtcHex = String(hex[index..<endIndex])

                // Skip "0000" padding and validate we have a real code
                if dtcHex.count == 4 && dtcHex != "0000" {
                    if let code = decodeDTC(dtcHex) {
                        // Avoid duplicates from multiple ECUs
                        if !codes.contains(code) {
                            codes.append(code)
                        }
                    }
                }
                index = endIndex
            }
        }

        print("[OBD-DEBUG] Parsed DTCs: \(codes)")
        return codes
    }

    private func decodeDTC(_ hex: String) -> String? {
        guard hex.count == 4,
              let firstByte = UInt8(String(hex.prefix(2)), radix: 16) else {
            return nil
        }

        // First 2 bits determine the category
        let category: String
        switch (firstByte >> 6) & 0x03 {
        case 0: category = "P"  // Powertrain
        case 1: category = "C"  // Chassis
        case 2: category = "B"  // Body
        case 3: category = "U"  // Network
        default: category = "P"
        }

        // Next 2 bits are first digit (0-3)
        let digit1 = (firstByte >> 4) & 0x03

        // Remaining 12 bits are the code number
        let remaining = String(hex.dropFirst(1))

        return "\(category)\(digit1)\(remaining.suffix(3))"
    }

    private func parseRPM(_ response: String) -> Int? {
        // Response format: 41 0C XX YY
        // RPM = ((A * 256) + B) / 4
        let bytes = parseOBDResponse(response, expectedPID: "0C")
        guard bytes.count >= 2 else { return nil }
        return ((Int(bytes[0]) * 256) + Int(bytes[1])) / 4
    }

    private func parseSpeed(_ response: String) -> Int? {
        // Response format: 41 0D XX
        // Speed in km/h, convert to mph
        let bytes = parseOBDResponse(response, expectedPID: "0D")
        guard bytes.count >= 1 else { return nil }
        let kmh = Int(bytes[0])
        return Int(Double(kmh) * 0.621371) // Convert to mph
    }

    private func parseCoolantTemp(_ response: String) -> Int? {
        // Response format: 41 05 XX
        // Temp = A - 40 (in Celsius), convert to Fahrenheit
        let bytes = parseOBDResponse(response, expectedPID: "05")
        guard bytes.count >= 1 else { return nil }
        let celsius = Int(bytes[0]) - 40
        return Int(Double(celsius) * 9/5 + 32) // Convert to Fahrenheit
    }

    private func parseOdometer(_ response: String) -> Double? {
        // Check for NO DATA response first
        if response.uppercased().contains("NO DATA") || response.uppercased().contains("NODATA") {
            print("[OBD-PARSE] Odometer: NO DATA response, PID not supported")
            return nil
        }

        // Response format: 41 A6 XX XX XX XX
        // Odometer in km (4 bytes, big-endian), convert to miles
        let bytes = parseOBDResponse(response, expectedPID: "A6")

        // Some vehicles return 2 bytes, some return 4
        if bytes.count >= 4 {
            // 4-byte format (standard OBD2 A6)
            let km = (UInt32(bytes[0]) << 24) |
                     (UInt32(bytes[1]) << 16) |
                     (UInt32(bytes[2]) << 8) |
                     UInt32(bytes[3])
            // Value is in 0.1 km units
            let miles = Double(km) / 10.0 * 0.621371
            print("[OBD-PARSE] Odometer (4-byte): \(km) -> \(miles) miles")
            return miles
        } else if bytes.count >= 2 {
            // 2-byte format (some vehicles)
            let km = (UInt32(bytes[0]) << 8) | UInt32(bytes[1])
            let miles = Double(km) * 0.621371
            print("[OBD-PARSE] Odometer (2-byte): \(km) -> \(miles) miles")
            return miles
        }

        print("[OBD-PARSE] Odometer: Not enough bytes (\(bytes.count))")
        return nil
    }

    private func parseFuelLevel(_ response: String) -> Int? {
        // Check for NO DATA response first
        if response.uppercased().contains("NO DATA") || response.uppercased().contains("NODATA") {
            print("[OBD-PARSE] Fuel Level: NO DATA response, PID not supported")
            return nil
        }

        // Response format: 41 2F XX
        // Fuel level = A * 100 / 255 (percentage 0-100%)
        let bytes = parseOBDResponse(response, expectedPID: "2F")
        guard bytes.count >= 1 else {
            print("[OBD-PARSE] Fuel Level: Not enough bytes (\(bytes.count))")
            return nil
        }

        let percentage = Int(Double(bytes[0]) * 100.0 / 255.0)
        print("[OBD-PARSE] Fuel Level: \(bytes[0]) -> \(percentage)%")
        return percentage
    }

    private func parseOBDResponse(_ response: String, expectedPID: String) -> [UInt8] {
        // Handle multi-ECU responses by splitting on \r first
        // Example: "410C0C54\r410C0C60\r\r>" - two ECUs responding
        let lines = response.components(separatedBy: CharacterSet(charactersIn: "\r\n"))

        // Find the first line with the expected response header
        let header = "41\(expectedPID)".uppercased()

        for line in lines {
            let cleaned = line
                .replacingOccurrences(of: " ", with: "")
                .replacingOccurrences(of: ">", with: "")
                .trimmingCharacters(in: .whitespaces)
                .uppercased()

            // Skip empty lines
            guard !cleaned.isEmpty else { continue }

            // Find the response header in this line
            guard let range = cleaned.range(of: header) else { continue }

            // Extract data bytes after the header
            let dataStart = range.upperBound
            let dataHex = String(cleaned[dataStart...])

            // Convert hex string to bytes
            var bytes: [UInt8] = []
            var index = dataHex.startIndex
            while index < dataHex.endIndex {
                let nextIndex = dataHex.index(index, offsetBy: 2, limitedBy: dataHex.endIndex) ?? dataHex.endIndex
                let hexPair = String(dataHex[index..<nextIndex])
                if let byte = UInt8(hexPair, radix: 16) {
                    bytes.append(byte)
                } else {
                    break
                }
                index = nextIndex
            }

            if !bytes.isEmpty {
                print("[OBD-PARSE] PID \(expectedPID): \(bytes.count) bytes -> \(bytes.map { String(format: "%02X", $0) }.joined(separator: " "))")
                return bytes
            }
        }

        print("[OBD-PARSE] PID \(expectedPID): No valid response found")
        return []
    }
}

// MARK: - CBCentralManagerDelegate

extension OBDManager: CBCentralManagerDelegate {
    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        Task { @MainActor in
            switch central.state {
            case .poweredOn:
                print("[OBDManager] Bluetooth powered on")
            case .poweredOff:
                lastError = "Bluetooth is turned off"
                connectionState = .disconnected
            case .unauthorized:
                lastError = "Bluetooth permission denied"
            case .unsupported:
                lastError = "Bluetooth not supported"
            default:
                break
            }
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral, advertisementData: [String : Any], rssi RSSI: NSNumber) {
        Task { @MainActor in
            let name = peripheral.name ?? advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? "Unknown"

            // Filter for likely OBD adapters
            let obdKeywords = ["OBD", "ELM", "OBD2", "OBDII", "Vgate", "iCar", "Veepeak", "BAFX", "Scan", "Car"]
            let isLikelyOBD = obdKeywords.contains { name.localizedCaseInsensitiveContains($0) }

            // Only add if not already in list
            if !discoveredDevices.contains(where: { $0.id == peripheral.identifier }) {
                let device = OBDDevice(
                    peripheral: peripheral,
                    name: name,
                    rssi: RSSI.intValue,
                    isLikelyOBD: isLikelyOBD
                )
                discoveredDevices.append(device)

                // Sort by likelihood and signal strength
                discoveredDevices.sort {
                    if $0.isLikelyOBD != $1.isLikelyOBD {
                        return $0.isLikelyOBD
                    }
                    return $0.rssi > $1.rssi
                }

                // Only log likely OBD devices to prevent console flooding
                if isLikelyOBD {
                    print("[OBDManager] Found OBD device: \(name)")
                }
            }
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        Task { @MainActor in
            print("[OBDManager] Connected to \(peripheral.name ?? "device")")
            connectedPeripheral = peripheral
            peripheral.delegate = self
            peripheral.discoverServices(nil)
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        Task { @MainActor in
            print("[OBDManager] Failed to connect: \(error?.localizedDescription ?? "unknown")")
            lastError = "Failed to connect to device"
            connectionState = .disconnected
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        Task { @MainActor in
            print("[OBDManager] Disconnected from \(peripheral.name ?? "device")")
            resetConnection()
        }
    }
}

// MARK: - CBPeripheralDelegate

extension OBDManager: CBPeripheralDelegate {
    nonisolated func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        Task { @MainActor in
            guard error == nil, let services = peripheral.services else {
                lastError = "Failed to discover services"
                return
            }

            for service in services {
                peripheral.discoverCharacteristics(nil, for: service)
            }
        }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        Task { @MainActor in
            guard error == nil, let characteristics = service.characteristics else { return }

            for characteristic in characteristics {

                // Look for write characteristic
                if characteristic.properties.contains(.write) || characteristic.properties.contains(.writeWithoutResponse) {
                    writeCharacteristic = characteristic
                }

                // Look for notify/read characteristic
                if characteristic.properties.contains(.notify) {
                    readCharacteristic = characteristic
                    peripheral.setNotifyValue(true, for: characteristic)
                }
            }

            // If we have both characteristics, we're connected
            if writeCharacteristic != nil {
                connectionState = .connected
                connectedDevice = discoveredDevices.first { $0.peripheral == peripheral }
                print("[OBDManager] Ready to communicate")
            }
        }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        Task { @MainActor in
            guard error == nil, let data = characteristic.value else { return }

            if let response = String(data: data, encoding: .utf8) {
                responseBuffer += response
                print("[OBD-DEBUG] Received chunk: \(response.replacingOccurrences(of: "\r", with: "\\r").replacingOccurrences(of: "\n", with: "\\n"))")
                print("[OBD-DEBUG] Buffer now: \(responseBuffer.replacingOccurrences(of: "\r", with: "\\r").replacingOccurrences(of: "\n", with: "\\n"))")

                // Check if response is complete
                // ELM327 responses end with ">" prompt, but also check for error responses
                let trimmed = responseBuffer.trimmingCharacters(in: .whitespacesAndNewlines)
                let isComplete = responseBuffer.contains(">") ||
                                 trimmed.hasSuffix("OK") ||
                                 trimmed.hasSuffix("NO DATA") ||
                                 trimmed.hasSuffix("ERROR") ||
                                 trimmed.hasSuffix("UNABLE TO CONNECT") ||
                                 trimmed.hasSuffix("?")

                if isComplete {
                    responseTimer?.invalidate()
                    let completion = responseCompletion
                    responseCompletion = nil
                    completion?(responseBuffer)
                }
            }
        }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        if let error = error {
            print("[OBD-DEBUG] Write ERROR: \(error.localizedDescription)")
        } else {
            print("[OBD-DEBUG] Write successful")
        }
    }
}

// MARK: - Supporting Types

enum OBDConnectionState: Equatable {
    case disconnected
    case scanning
    case connecting
    case connected
    case ready
    case error(String)

    var description: String {
        switch self {
        case .disconnected: return "Disconnected"
        case .scanning: return "Scanning..."
        case .connecting: return "Connecting..."
        case .connected: return "Connected"
        case .ready: return "Ready"
        case .error(let msg): return "Error: \(msg)"
        }
    }

    var isConnected: Bool {
        switch self {
        case .connected, .ready: return true
        default: return false
        }
    }
}

struct OBDDevice: Identifiable {
    let id: UUID
    let peripheral: CBPeripheral
    let name: String
    let rssi: Int
    let isLikelyOBD: Bool

    init(peripheral: CBPeripheral, name: String, rssi: Int, isLikelyOBD: Bool) {
        self.id = peripheral.identifier
        self.peripheral = peripheral
        self.name = name
        self.rssi = rssi
        self.isLikelyOBD = isLikelyOBD
    }
}

enum OBDError: LocalizedError {
    case notConnected
    case timeout
    case invalidResponse
    case noData

    var errorDescription: String? {
        switch self {
        case .notConnected: return "Not connected to OBD adapter"
        case .timeout: return "Command timed out"
        case .invalidResponse: return "Invalid response from adapter"
        case .noData: return "No data available"
        }
    }
}

/// Async semaphore to serialize OBD commands (adapter only handles one at a time)
actor CommandLock {
    private var isLocked = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func acquire() async {
        if !isLocked {
            isLocked = true
            return
        }

        // Wait in queue until lock is available
        await withCheckedContinuation { continuation in
            waiters.append(continuation)
        }
    }

    func release() {
        if let next = waiters.first {
            waiters.removeFirst()
            next.resume()
        } else {
            isLocked = false
        }
    }
}
