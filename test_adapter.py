"""
Direct OBD Adapter Test Script
Sends raw AT commands to the ELM327 adapter to diagnose connection issues.
"""
import serial
import time

def test_adapter(port="COM3"):
    """Test the OBD adapter with raw AT commands."""
    print(f"Testing OBD adapter on {port}...")
    print("Make sure car ignition is ON!\n")

    try:
        # Open serial connection
        ser = serial.Serial(port, baudrate=38400, timeout=3)
        time.sleep(2)  # Wait for adapter to initialize

        print("[1/6] Sending ATZ (Reset adapter)...")
        ser.write(b'ATZ\r')
        response = ser.read(100).decode('utf-8', errors='ignore')
        print(f"Response: {response.strip()}")
        time.sleep(1)

        print("\n[2/6] Sending ATE0 (Echo off)...")
        ser.write(b'ATE0\r')
        response = ser.read(100).decode('utf-8', errors='ignore')
        print(f"Response: {response.strip()}")
        time.sleep(1)

        print("\n[3/6] Sending ATI (Get adapter ID)...")
        ser.write(b'ATI\r')
        response = ser.read(100).decode('utf-8', errors='ignore')
        print(f"Response: {response.strip()}")
        time.sleep(1)

        print("\n[4/6] Sending ATSP0 (Auto protocol)...")
        ser.write(b'ATSP0\r')
        response = ser.read(100).decode('utf-8', errors='ignore')
        print(f"Response: {response.strip()}")
        time.sleep(1)

        print("\n[5/6] Sending 0100 (Get supported PIDs)...")
        ser.write(b'0100\r')
        response = ser.read(200).decode('utf-8', errors='ignore')
        print(f"Response: {response.strip()}")

        if "41 00" in response or "4100" in response:
            print("\n✓ SUCCESS! Adapter is communicating with vehicle!")
        elif "UNABLE TO CONNECT" in response or "NO DATA" in response:
            print("\n✗ Adapter found but CANNOT connect to vehicle ECU")
            print("  Possible causes:")
            print("  - Wrong protocol (try ATSP6 for ISO 15765-4 CAN)")
            print("  - Incompatible/fake adapter chip")
            print("  - Vehicle ECU not responding")
        else:
            print(f"\n? Unexpected response - adapter may not be working correctly")

        print("\n[6/6] Sending ATDPN (Display protocol number)...")
        ser.write(b'ATDPN\r')
        response = ser.read(100).decode('utf-8', errors='ignore')
        print(f"Protocol: {response.strip()}")

        ser.close()

    except serial.SerialException as e:
        print(f"✗ Serial port error: {e}")
        print(f"  Make sure {port} is the correct COM port")
    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == "__main__":
    print("=== OBD Adapter Diagnostic Tool ===\n")

    # Try COM3 first, then COM4
    for port in ["COM3", "COM4"]:
        try:
            print(f"\n{'='*50}")
            test_adapter(port)
            print(f"{'='*50}\n")
        except Exception as e:
            print(f"Could not test {port}: {e}\n")
            continue

        input("Press Enter to continue to next port or Ctrl+C to exit...")
