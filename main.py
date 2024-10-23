# Import necessary libraries
import os
import wifi
import socketpool
import adafruit_requests
import ssl
import time
import board
import busio
import adafruit_ssd1306
import pwmio
import simpleio
from adafruit_motor import servo
from huskylens_lib import HuskyLensLibrary
import neopixel
import digitalio
from adafruit_apds9960.apds9960 import APDS9960

# Wi-Fi and Telegram setup using environment variables from settings.toml
ssid = os.getenv("CIRCUITPY_WIFI_SSID")
password = os.getenv("CIRCUITPY_WIFI_PASSWORD")
telegrambot = os.getenv("botToken")
chat_id = os.getenv("chat_id")
API_URL = f"https://api.telegram.org/bot{telegrambot}"

# Initialize I2C for OLED
i2c = busio.I2C(board.GP5, board.GP4)
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)

# Initialize HuskyLens with Face Recognition mode
hl = HuskyLensLibrary('I2C', SCL=board.GP27, SDA=board.GP26)
hl.algorithm("ALGORITHM_FACE_RECOGNITION")  # Set HuskyLens to Face Recognition mode

# Initialize Servo for door lock control on GP6
pwm1 = pwmio.PWMOut(board.GP6, duty_cycle=0, frequency=50)
door_servo = servo.Servo(pwm1, min_pulse=750, max_pulse=2250)

# Initialize NeoPixel for RGB status indication on GP14 with 5 LEDs
pixel = neopixel.NeoPixel(board.GP14, 5)
pixel.brightness = 0.1  # Set pixel brightness to 10%

# Initialize USB relay on pin GP22
usb = digitalio.DigitalInOut(board.GP22)
usb.direction = digitalio.Direction.OUTPUT
usb.value = False  # Ensure the relay is off initially

# Initialize APDS9960 gesture sensor
apds9960_sensor = APDS9960(i2c)
apds9960_sensor.enable_proximity = True
apds9960_sensor.enable_gesture = True

# Define piezo buzzer pin for melody playback
PIEZO_AUDIO_L_PIN = board.GP21

# Define colors for NeoPixel LED
GREEN = (0, 255, 0)
RED = (255, 0, 0)
BLACK = (0, 0, 0)
OFF = (0, 0, 0)

# Define melodies for access granted and intruder alert
MELODY_ACCESS_GRANTED = [523, 659, 784]  # C, E, G (ascending)
DURATION_GRANTED = [0.2, 0.2, 0.4]
MELODY_INTRUDER_ALERT = [880, 0]  # High-pitch alternating with silence
DURATION_INTRUDER = [0.2, 0.2]

# Face ID to Name mapping
FACE_ID_NAMES = {
    1: "Ayah",
    2: "Mama",
    3: "Along"
}

# Initialize flags for face detection and gesture detection
intruder_active = False
relay_timer = None

# Wi-Fi connection
print(f"Connecting to WiFi '{ssid}'...")
wifi.radio.connect(ssid, password)
pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())
print("Connected! IP Address:", wifi.radio.ipv4_address)

# Functions for Telegram Bot
def send_telegram_message(message):
    """Send a message via Telegram Bot."""
    url = f"{API_URL}/sendMessage?chat_id={chat_id}&text={message}"
    requests.get(url)

# Define melody playback function
def play_melody(melody_notes, durations):
    """Plays a melody using a list of notes and durations."""
    for note, duration in zip(melody_notes, durations):
        if note == 0:  # Pause if note is 0
            time.sleep(duration)
        else:
            simpleio.tone(PIEZO_AUDIO_L_PIN, note, duration=duration)

# OLED display functions for face recognition
def display_text(line1, line2=""):
    """Display messages on the OLED screen."""
    oled.fill(0)
    oled.text(line1, 0, 20, 1)
    if line2:
        oled.text(line2, 0, 35, 1)
    oled.show()

# Function to unlock the door
def unlock_door(name):
    global intruder_active
    door_servo.angle = 90  # Adjust as needed for unlock position
    display_text(f"Access Granted", f"Hi {name}!")
    pixel.fill(GREEN)  # Set LED to green for access granted
    play_melody(MELODY_ACCESS_GRANTED, DURATION_GRANTED)  # Play access granted melody
    send_telegram_message(f"{name} is home!!")
    print(f"Door Unlocked for {name}")
    time.sleep(5)  # Keep door unlocked for 5 seconds
    intruder_active = False  # Reset intruder alert
    lock_door()

# Function to lock the door
def lock_door():
    door_servo.angle = 0  # Adjust as needed for lock position
    display_text("Door Locked", "Locked")
    pixel.fill(RED)  # Set LED to red for locked state
    print("Door Locked")

# Function for intruder alert
def intruder_alert():
    global intruder_active
    if not intruder_active:  # Avoid multiple alerts
        display_text("Intruder!!!", "Alert!")
        intruder_active = True
        send_telegram_message("Intruder Alert: Unrecognized face detected!")
        while intruder_active:
            pixel.fill(RED)
            play_melody(MELODY_INTRUDER_ALERT, DURATION_INTRUDER)
            pixel.fill(BLACK)
            time.sleep(0.2)
            intruder_active = check_intruder_status()  # Continue until no unrecognized face

# Check intruder status
def check_intruder_status():
    results = hl.blocks()  # Get all detected faces
    return any(result.ID == 0 for result in results)  # True if any face without ID

# Check recognized face ID
def check_face_id():
    results = hl.blocks()  # Get all detected faces (recognized and unrecognized)
    if results:
        for result in results:
            if result.ID in FACE_ID_NAMES:
                name = FACE_ID_NAMES[result.ID]
                print(f"Face ID {result.ID} detected: {name}")
                return name
        # If no recognized face, check for unrecognized faces
        if any(result.ID == 0 for result in results):
            print("Intruder detected!")
            intruder_alert()
            return None
    return None

# Gesture and USB relay control (without OLED display)
def run_gesture_and_relay_control():
    global relay_timer

    gesture = apds9960_sensor.gesture()

    if gesture in [0x01, 0x02, 0x03, 0x04]:  # Any valid gesture
        usb.value = True  # Turn on the relay
        relay_timer = time.monotonic() + 5  # Set the timer to turn off relay after 5 seconds
        print("Gesture detected, USB relay ON")

    # If the timer is set and the time has passed, turn off the relay
    if relay_timer and time.monotonic() > relay_timer:
        usb.value = False  # Turn off the relay
        relay_timer = None  # Reset the timer
        print("No gesture detected, USB relay OFF")

# Main security system logic with Telegram notifications
def run_security_system():
    recognized_name = check_face_id()  # Check for recognized faces
    if recognized_name:
        unlock_door(recognized_name)  # Unlock door for recognized face
    else:
        lock_door()  # Only lock the door, no access denied notification

# Main loop
if __name__ == "__main__": 
    try:
        pixel.fill(OFF)  # Turn off NeoPixel initially
        while True:
            run_security_system()  # Face recognition and security system
            run_gesture_and_relay_control()  # Gesture sensor and USB relay control (no OLED messages)
            time.sleep(0.5)  # Small delay to prevent rapid re-triggering
    finally:
        pwm1.deinit()
        pixel.fill(OFF)  # Turn off the LED when the program ends

