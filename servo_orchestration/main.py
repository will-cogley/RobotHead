import machine
from machine import Pin, I2C
import time
import json
import random
import sys
import uselect

from hardware import DebouncedButton, RotaryEncoder, SystemHardware
from kinematics import SmartServo
from blendshape import BlendshapeEngine
from autonomy import LifeEngine

CONFIG_FILE = "robot_config.json"

# --- 1. Init Hardware ---
i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=400000)
hw = SystemHardware(i2c)

mode_switch = Pin(10, Pin.IN, Pin.PULL_UP)
action_btn = DebouncedButton(11)
encoder_sw = DebouncedButton(13)
encoder = RotaryEncoder(14, 12)
manual_override = False # Global state to track who has control

# --- 2. Load the "Brain" ---
try:
    with open(CONFIG_FILE, 'r') as f:
        brain = json.load(f)
except Exception as e:
    print(f"CRITICAL: Failed to load config: {e}")
    brain = {"hardware": {}, "poses": {"Neutral": {}}}
    
# Initialize the Blendshape Engine
bs_engine = BlendshapeEngine(brain)
life_engine = LifeEngine()
current_manual_weights = {}

# --- 3. Init Servos (Staggered & Ordered Startup) ---
servos = {}
servo_names = sorted(
    list(brain["hardware"].keys()), 
    key=lambda name: brain["hardware"][name]["channel"]
)
selected_idx = 0

print("\nStarting Ordered Servo Initialization...")

for name in servo_names:
    config = brain["hardware"][name]
    
    # Check what the Neutral angle should be before waking the servo up
    start_pos = 90.0
    if "Neutral" in brain.get("poses", {}) and name in brain["poses"]["Neutral"]:
        start_pos = brain["poses"]["Neutral"][name]
    
    # Initialize the servo and pass the starting angle
    servos[name] = SmartServo(
        hw, 
        channel=config["channel"], 
        min_angle=config.get("min_angle", 10), 
        max_angle=config.get("max_angle", 170),
        max_speed=config.get("max_speed", 150),
        max_accel=config.get("max_accel", 300),
        start_angle=start_pos # <--- FIX: Passes the exact Neutral angle to wake up at
    )
    
    time.sleep_ms(100) 
    print(f"Initialized {name} (Channel {config['channel']}) at {start_pos} deg...")

print("All servos initialized.")


# --- 4. CLI Helper Functions ---
def find_pose_name(raw_name):
    """Makes input case-insensitive by finding the actual saved name."""
    # MicroPython doesn't have .title(), so we do it manually: "smile" -> "Smile"
    formatted_name = raw_name[0].upper() + raw_name[1:].lower() if len(raw_name) > 0 else raw_name
    
    if "poses" not in brain:
        return formatted_name 
    
    # Check if a lowercase version of the input matches any saved poses
    for saved_name in brain["poses"]:
        if saved_name.lower() == raw_name.lower():
            return saved_name
            
    return formatted_name # If it's a brand new pose, return the formatted version

def save_pose(raw_name):
    pose_name = find_pose_name(raw_name) # Fix Case
    
    if "poses" not in brain: brain["poses"] = {}
    brain["poses"][pose_name] = {}
    
    # Grab the neutral face for comparison
    neutral_pose = brain["poses"].get("Neutral", {})
    
    # We ignore any movements smaller than 1 degree to account for sensor noise
    TOLERANCE = 1.0 
    
    saved_count = 0
    for name, servo in servos.items():
        # If we are saving the base poses, we MUST save every single servo
        if pose_name in ["Neutral", "Calibrate"]:
            brain["poses"][pose_name][name] = servo.target
            saved_count += 1
        else:
            # For all other poses (like Blink), ONLY save if it moved from Neutral
            neutral_angle = neutral_pose.get(name, 90.0)
            if abs(servo.target - neutral_angle) > TOLERANCE:
                brain["poses"][pose_name][name] = servo.target
                saved_count += 1
                
    with open(CONFIG_FILE, 'w') as f:
        json.dump(brain, f)
    
    bs_engine.reload(brain)
    print(f"\n[SUCCESS] Saved pose '{pose_name}' to flash! ({saved_count} servos recorded)")
    
def save_config():
    """Writes the entire current 'brain' dictionary to the JSON file."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(brain, f)
    # Don't forget to reload the blendshape engine so it knows about the changes!
    bs_engine.reload(brain) 
    print(f"\n[SUCCESS] Configuration saved to flash!")

def test_pose(raw_name):
    pose_name = find_pose_name(raw_name) # Fix Case
    if pose_name in brain.get("poses", {}):
        set_blend({pose_name: 1.0})
    else:
        print(f"\n[ERROR] Pose '{pose_name}' not found!")

def set_blend(weights_dict):
    global current_manual_weights
    current_manual_weights = weights_dict
    print(f"\n[BLENDING] Active manual weights: {current_manual_weights}")

# --- 5. Custom Command Line Setup ---
spoll = uselect.poll()
spoll.register(sys.stdin, uselect.POLLIN)
input_buffer = ""

# --- Main Loop State ---
last_time = time.ticks_ms()
current_mode = -1

print("\n=== SYSTEM BOOT COMPLETE ===")
print("COMMANDS: Type 'save [name]' or 'test [name]' and press Enter.")

while True:
    current_time = time.ticks_ms()
    dt = time.ticks_diff(current_time, last_time) / 1000.0
    last_time = current_time

    # Determine Mode
# Determine Mode
    mode = 0 if mode_switch.value() == 0 else 1
    
# --- ADD THIS LOGIC TO AUTO-SAVE AND AUTO-POSE ---
    if mode != current_mode:
        # If we were in Calibration (0) and just switched to Puppet (1)
        if current_mode == 0 and mode == 1:
            save_config()
            # Jump to the awake animation baseline
            if "Neutral" in brain.get("poses", {}):
                test_pose("Neutral") 
            
        current_mode = mode
        mode_name = "CALIBRATION/HARDWARE" if mode == 0 else "POSING/RUN MODE"
        print(f"\n\n--- {mode_name} ---")
        print(f"Selected: {servo_names[selected_idx]}\n> ", end="")

        # If we just entered Calibration mode, jump to the mechanical setup pose
        if mode == 0 and "Calibrate" in brain.get("poses", {}):
            test_pose("Calibrate")

# --- CLI Input Polling ---
    if spoll.poll(0):
        char = sys.stdin.read(1)
        if char == '\n' or char == '\r':
            if input_buffer:
                parts = input_buffer.strip().split(" ")
                cmd = parts[0].lower()
                
                if cmd == "save" and len(parts) > 1:
                    save_pose(parts[1])
                elif cmd == "test" and len(parts) > 1:
                    manual_override = False  # Let the engine take control
                    test_pose(parts[1])
                elif cmd == "blend" and len(parts) > 2:
                    try:
                        weight = float(parts[2])
                        pose_name = find_pose_name(parts[1])
                        manual_override = False  # Let the engine take control
                        set_blend({pose_name: weight})
                    except ValueError:
                        print("\n[ERROR] Weight must be a number (e.g., 0.5)")
                elif cmd == "neutral":
                    manual_override = False  # Let the engine take control
                    set_blend({}) 
                elif cmd == "life" and len(parts) > 1:
                    if parts[1].lower() == "on":
                        manual_override = False # Wake the engines
                        # Pass current positions so eyes don't jump
                        life_engine.enable(servos["EYE_LATERAL"].target, servos["EYE_VERTICAL"].target)
                        print("\n[LIFE] Autonomous idling ENABLED.")
                    elif parts[1].lower() == "off":
                        manual_override = True # Kill the engines
                        life_engine.disable()
                        print("\n[LIFE] Autonomous idling DISABLED.")
                else:
                    print(f"\nUnknown command: '{input_buffer}'.")
                
                input_buffer = ""
            print("\n> ", end="") 
        else:
            input_buffer += char    # Read Hardware Inputs
    delta = encoder.get_delta()
    
    if delta != 0:
        manual_override = True # TRIP THE CIRCUIT BREAKER
        # ... (Your existing manual move code) ...
    
    btn_cycle = encoder_sw.is_pressed()
    btn_action = action_btn.is_pressed()
    
    current_servo_name = servo_names[selected_idx]
    active_servo = servos[current_servo_name]

    # --- Interaction Logic ---
    if btn_cycle:
        if current_mode == 0: # Cache hardware calibration
            if "Calibrate" not in brain["poses"]: brain["poses"]["Calibrate"] = {}
            brain["poses"]["Calibrate"][current_servo_name] = active_servo.target
            
        selected_idx = (selected_idx + 1) % len(servo_names)
        print(f"\nSelected: {servo_names[selected_idx]}\n> ", end="")
        
    if delta != 0:
        multiplier = 5 if (current_mode == 0 and action_btn.pin.value() == 0) else 1
        active_servo.set_target(active_servo.target + (delta * multiplier))
        # The magic \r clears the line and writes over it!
        print(f"\r{current_servo_name} Angle: {active_servo.target:>5.1f}    ", end="")
        
# --- Update Targets & Kinematics ---
    if current_mode == 1:
        if not manual_override:
            # 1. Update autonomy
            life_engine.update(dt)
            
            # 2. Check if user is currently turning the knob
            is_manual_adjusting = (delta != 0) 
            
            # 3. Calculate blendshape targets
            combined_weights = dict(current_manual_weights)
            for pose, weight in life_engine.blend_weights.items():
                combined_weights[pose] = combined_weights.get(pose, 0.0) + weight
            targets = bs_engine.calculate_targets(combined_weights)
            
            # 4. Add Life Engine physical tracking offsets
            for servo_name, offset in life_engine.offsets.items():
                if servo_name in targets:
                    targets[servo_name] += offset
            
            # 5. Apply targets ONLY IF not manually adjusting
            for name, angle in targets.items():
                if name in servos:
                    # If we are manually adjusting the current servo, skip the engine's update
                    if is_manual_adjusting and name == current_servo_name:
                        continue 
                    servos[name].set_target(angle)
                    
        else:
            targets = {}

    # Actually move the hardware
    for s in servos.values():
        s.update(dt)

    time.sleep_ms(20)
