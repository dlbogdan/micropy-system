# MicroPython Water Heater Controller Interface

A lightweight web interface for controlling and configuring a water heater controller running on MicroPython.

## Features

- Control water heater temperature and operation
- Configure WiFi settings
- Adjust system parameters (PID controller, MQTT, etc.)
- Responsive design works on mobile and desktop browsers

## Hardware Requirements

- MicroPython-compatible microcontroller (e.g., Raspberry Pi Pico W, ESP32, ESP8266)
- Minimum 2MB flash storage recommended
- WiFi connectivity

## Installation

1. Copy the following files to your MicroPython device:
   - `main.py` - The main application code
   - `index.html` - The web interface
   - Optional: `config.json` - Default configuration (will be created automatically if not present)

2. Reset your device to start the application

## Usage

### Initial Setup

When first powered on, the device will:
1. Try to connect to WiFi using stored credentials
2. If connection fails, create an access point named "HeaterController" with password "password"
3. Connect to this access point to configure your WiFi settings

### Accessing the Interface

Once connected to your network, access the web interface by navigating to the device's IP address in a browser:
- `http://[device-ip]/` (e.g., `http://192.168.1.105/`)

### Interface Tabs

1. **Control Tab**
   - View current and target temperatures
   - Adjust target temperature
   - Toggle heating and DHW (Domestic Hot Water)
   - Monitor system status

2. **WiFi Tab**
   - Configure WiFi connection settings
   - Set device hostname
   - View connection status

3. **Configuration Tab**
   - Adjust all system parameters
   - PID controller settings
   - MQTT configuration
   - Firmware update settings
   - And more...

## Configuration Parameters

The configuration is stored in JSON format and includes the following sections:

- **HARDWARE** - Hardware pin assignments and I/O configuration
- **WIFI** - Network connection settings
- **DEVICE** - Device identification and model
- **FIRMWARE** - Update settings and GitHub repository information
- **OT** (OpenTherm) - Heating control parameters
- **AUTOH** - Automatic heating control settings
- **PID** - PID controller tuning parameters
- **MQTT** - Message broker configuration

## Customization

You can modify the HTML and JavaScript to add additional features or adjust the user interface without needing to modify the Python backend in many cases.

## Troubleshooting

- If the device doesn't appear on your network, check that WiFi credentials are correct
- If the web interface doesn't load, try resetting the device
- For persistent issues, connect to the device using a serial connection and check for error messages

## Security Considerations

This is a basic implementation with minimal security. For production use, consider:
- Implementing authentication for the web interface
- Using HTTPS instead of HTTP (requires additional libraries)
- Encrypting stored passwords
- Adding rate limiting for failed connection attempts 