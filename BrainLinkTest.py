import tkinter as tk
import time
from cushy_serial import CushySerial
from BrainLinkParser import BrainLinkParser             # pyright: ignore[reportMissingImports]

eeg_data = {                                            # Dictionary that will collect values throughout duration.
    "attention": [],
    "meditation": [],
    "delta": [],
    "theta": [],
    "lowAlpha": [],
    "highAlpha": [],
    "lowBeta": [],
    "highBeta": [],
    "lowGamma": [],
    "highGamma": []
}                                      

def onEEG(data):                                        # Adding as value to the key since the value is a list of values
    eeg_data["attention"].append(data.attention)
    eeg_data["meditation"].append(data.meditation)
    eeg_data["delta"].append(data.delta)
    eeg_data["theta"].append(data.theta)
    eeg_data["lowAlpha"].append(data.lowAlpha)
    eeg_data["highAlpha"].append(data.highAlpha)
    eeg_data["lowBeta"].append(data.lowBeta)
    eeg_data["highBeta"].append(data.highBeta)
    eeg_data["lowGamma"].append(data.lowGamma)
    eeg_data["highGamma"].append(data.highGamma)

def onRaw(raw):                                         # Callback Functions 
    return                                              # This function is supposed to show the raw data the device outputs (Example - b'\x02\x10\x03\x1a\xff\x05'). This is useless, we never get HZ value.

def onExtendEEG(data):
    return                                              # This is what is actually allowing us to get Delta, Theta, Beta values etc.

def onGyro(x, y, z):
    return                                              # Useless, useful to detect head movement but I've used it since the parser needs it anyway.

def onRR(rr1, rr2, rr3):
    return                                              # For Heart Rate and Pulse if the device supports it, I think BrainLink Pro does. Useless for me. (BrainLink Lite)

parser = BrainLinkParser(onEEG, onExtendEEG, onGyro, onRR, onRaw)       # Parsing with the BrainLinkParser.

try:                                                                    # It will only connect to COM3 or COM4, I've hardcoded this. Depending on how many Bluetooth devices are there the COM port can change. Check Bluetooth settings
    serial = CushySerial('COM4', 115200)                                # You'll get detailed error message. Understand it.
except Exception as e:
    print(f"Could not connect on COM4 - '{e}'")
    try:
        serial = CushySerial('COM3', 115200)
    except Exception as e2:
        print(f"Could not connect on COM3 either - '{e2}'")
        exit(1)

@serial.on_message()                                                    # Listen message from serial and register callback function. It will callback when serial receive message from serial. (According to _core.py)
def handle_serial_message(msg: bytes):                                  # Finally going to Parse here.
    parser.parse(msg)

try:
    print("Recording EEG signals for 3 minute...")
    time.sleep(180)

    # Compute averages
    print("\nAverage EEG values after 3 minutes of runtime")
    for key, values in eeg_data.items():
        if values:
            avg_val = sum(values) / len(values)
            print(f"{key}: {avg_val:.2f}")
        else:
            print(f"{key}: No data")
    
    lowAlpha_avg = sum(eeg_data['lowAlpha']) / len(eeg_data['lowAlpha']) if eeg_data['lowAlpha'] else 0
    highAlpha_avg = sum(eeg_data['highAlpha']) / len(eeg_data['highAlpha']) if eeg_data['highAlpha'] else 0
    lowBeta_avg = sum(eeg_data['lowBeta']) / len(eeg_data['lowBeta']) if eeg_data['lowBeta'] else 0
    highBeta_avg = sum(eeg_data['highBeta']) / len(eeg_data['highBeta']) if eeg_data['highBeta'] else 0                             

    alpha_beta_ratio = (lowAlpha_avg + highAlpha_avg) / (lowBeta_avg + highBeta_avg) if (lowBeta_avg + highBeta_avg) != 0 else 0        # Ratio for the project
    print(f"Ratio of Alpha/Beta: {alpha_beta_ratio:.2f}")

finally:
    print("\nReleasing serial port.")
    serial.close()
    print("Port closed.")
