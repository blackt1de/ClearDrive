# ClearDrive iOS App

Native iOS app for ClearDrive car diagnostics with Bluetooth OBD support.

## Setup Instructions

### 1. Create Xcode Project

On your Mac mini:

1. Open Xcode
2. Create a new iOS App project:
   - **Product Name:** ClearDrive
   - **Team:** Your Apple Developer account
   - **Organization Identifier:** com.yourname (e.g., com.conor)
   - **Interface:** SwiftUI
   - **Language:** Swift

3. Delete the auto-generated files (ContentView.swift, ClearDriveApp.swift)

4. Drag all files from this `ClearDrive` folder into your Xcode project:
   - ClearDriveApp.swift
   - ContentView.swift
   - Views/ folder
   - Services/ folder
   - Models/ folder
   - Info.plist (merge with existing or replace)

### 2. Configure Project Settings

1. In Project Settings → Info, ensure these keys exist:
   - `NSBluetoothAlwaysUsageDescription`
   - `NSBluetoothPeripheralUsageDescription`

2. In Signing & Capabilities:
   - Add **Background Modes** capability
   - Check **Uses Bluetooth LE accessories**

### 3. Update Server URL

In `SettingsView.swift`, update the default server URL:
```swift
@AppStorage("serverURL") private var serverURL = "http://YOUR-SERVER-IP:8000"
```

### 4. Build and Run

1. Connect your iPhone
2. Select your device as the build target
3. Press Cmd+R to build and run

## Features

- **Bluetooth OBD Connection**: Connects to ELM327-based Bluetooth adapters
- **DTC Code Reading**: Reads diagnostic trouble codes from your vehicle
- **AI Diagnosis**: Sends codes to your ClearDrive server for AI-powered analysis
- **Vehicle Images**: Displays stock images of your vehicle
- **Scan History**: View previous diagnostic scans

## Supported OBD Adapters

- OBDLink MX+ (Recommended)
- OBDLink CX
- Veepeak OBDCheck BLE+
- Generic ELM327 Bluetooth adapters

## Server Requirements

The app requires a running ClearDrive server. Make sure:
1. Server is running on port 8000
2. Server is accessible from your phone's network
3. Ollama is running for AI diagnosis

## Troubleshooting

### Bluetooth Issues
- Ensure Bluetooth is enabled on your iPhone
- Turn car ignition to ON position
- Wait 10-15 seconds after plugging in adapter

### Connection Issues
- Verify server URL in Settings
- Check that server and phone are on same network
- Test connection using the button in Settings
