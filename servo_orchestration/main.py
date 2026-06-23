# ===============================================================================
# ANIMATRONIC CONTROL SYSTEM
# ===============================================================================
# 
# --- HARDWARE MODES (Toggle Switch) ---
# MODE 0 (Calibration): Locks servos into the 'Calibrate' maintenance pose. 
#                       Adjust servos by cycling through and fine-tuning.
# MODE 1 (Run/Pose):    The main animation mode. Defaults to 'Neutral' pose.
#                       Use this to sculpt new expressions and run animations.
#
# --- THE "MANUAL OVERRIDE" WORKFLOW ---
# 1. Turn the physical knob -> "Manual Override" engages. Engines go to sleep.
# 2. You are now the pilot. You can sculpt the active servo without fighting the code.
# 3. Type a command (like 'test' or 'life on') -> Engines wake up and take control back.
#
# --- CLI COMMAND CHEAT SHEET ---
# save <Name>           : Saves the current pose. (e.g. 'save Smile')
#                         *Only saves servos that moved from Neutral.
# test <Name>           : Snaps the face to a saved pose. (e.g. 'test Blink')
# blend <Name> <Weight> : Blends a pose from 0.0 to 1.0. (e.g. 'blend Smile 0.5')
# neutral               : Clears all manual blends and returns to base Neutral.
# life on / life off    : Toggles the autonomous idling (saccades, micro-jitters, blinks).
# play <Sequence>       : Plays an animation timeline. (e.g. 'play test')
# ===============================================================================#

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
from animator import SequencePlayer

CONFIG_FILE = "robot_config.json"

TEST_SPEECH = [
    {"duration": 0.3, "weights": {"Open": 0.2}}, 
    {"duration": 0.2, "weights": {"Open": 0.0}}, 
    {"duration": 0.3, "weights": {"Open": 0.1}}, 
    {"duration": 0.1, "weights": {"Open": 0.0}}, 
    {"duration": 0.4, "weights": {"Open": 0.4}}, 
    {"duration": 0.5, "weights": {}}              
]

# --- 1. Init Hardware ---
i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=400000)
hw = SystemHardware(i2c)

mode_switch = Pin(10, Pin.IN, Pin.PULL_UP)
action_btn = DebouncedButton(11)
encoder_sw = DebouncedButton(13)
encoder = RotaryEncoder(14, 12)
manual_override = False 

# --- 2. Load the "Brain" ---
try:
    with open(CONFIG_FILE, 'r') as f:
        brain = json.load(f)
except Exception as e:
    print(f"CRITICAL: Failed to load config: {e}")
    brain = {"hardware": {}, "poses": {"Neutral": {}}}
    
bs_engine = BlendshapeEngine(brain)
life_engine = LifeEngine()
animator = SequencePlayer() 
current_manual_weights = {}


# --- 3. Init Servos ---
servos = {}
servo_names = sorted(
    list(brain["hardware"].keys()), 
    key=lambda name: brain["hardware"][name]["channel"]
)
selected_idx = 0

print("\nStarting Ordered Servo Initialization...")

for name in servo_names:
    config = brain["hardware"][name]
    start_pos = 90.0
    if "Neutral" in brain.get("poses", {}) and name in brain["poses"]["Neutral"]:
        start_pos = brain["poses"]["Neutral"][name]
    
    servos[name] = SmartServo(
        hw, 
        channel=config["channel"], 
        min_angle=config.get("min_angle", 10), 
        max_angle=config.get("max_angle", 170),
        max_speed=config.get("max_speed", 150),
        max_accel=config.get("max_accel", 300),
        start_angle=start_pos 
    )
    time.sleep_ms(10) 

print("All servos initialized.")


# --- 4. CLI Helper Functions ---
def find_pose_name(raw_name):
    formatted_name = raw_name[0].upper() + raw_name[1:].lower() if len(raw_name) > 0 else raw_name
    if "poses" not in brain:
        return formatted_name 
    for saved_name in brain["poses"]:
        if saved_name.lower() == raw_name.lower():
            return saved_name
    return formatted_name 

def save_pose(raw_name):
    pose_name = find_pose_name(raw_name) 
    if "poses" not in brain: brain["poses"] = {}
    brain["poses"][pose_name] = {}
    
    neutral_pose = brain["poses"].get("Neutral", {})
    TOLERANCE = 1.0 
    
    saved_count = 0
    for name, servo in servos.items():
        if pose_name in ["Neutral", "Calibrate"]:
            brain["poses"][pose_name][name] = servo.target
            saved_count += 1
        else:
            neutral_angle = neutral_pose.get(name, 90.0)
            if abs(servo.target - neutral_angle) > TOLERANCE:
                brain["poses"][pose_name][name] = servo.target
                saved_count += 1
                
    with open(CONFIG_FILE, 'w') as f:
        json.dump(brain, f)
    
    bs_engine.reload(brain)
    print(f"\n[SUCCESS] Saved pose '{pose_name}' to flash! ({saved_count} servos recorded)")
    
def save_config():
    with open(CONFIG_FILE, 'w') as f:
        json.dump(brain, f)
    bs_engine.reload(brain) 
    print(f"\n[SUCCESS] Configuration saved to flash!")

def test_pose(raw_name):
    pose_name = find_pose_name(raw_name) 
    if pose_name in brain.get("poses", {}):
        set_blend({pose_name: 1.0})
    else:
        print(f"\n[ERROR] Pose '{pose_name}' not found!")

def set_blend(weights_dict):
    global current_manual_weights
    current_manual_weights = weights_dict
#     print(f"\n[BLENDING] Active manual weights: {current_manual_weights}")

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

    mode = 0 if mode_switch.value() == 0 else 1
    
        # --- Update Targets & Kinematics ---
    if current_mode == 1:
        if not manual_override:
            life_engine.update(dt)
            animator.update(dt)
            
            is_manual_adjusting = (delta != 0) 
            
            # Combine all weights cleanly
            combined_weights = dict(current_manual_weights)
            
            for pose, weight in life_engine.blend_weights.items():
                combined_weights[pose] = combined_weights.get(pose, 0.0) + weight
                
            for pose, weight in animator.blend_weights.items(): 
                combined_weights[pose] = combined_weights.get(pose, 0.0) + weight
                
            targets = bs_engine.calculate_targets(combined_weights)
            
            for servo_name, offset in life_engine.offsets.items():
                if servo_name in targets:
                    targets[servo_name] += offset
            
            for name, angle in targets.items():
                if name in servos:
                    if is_manual_adjusting and name == servo_names[selected_idx]:
                        continue 
                    servos[name].set_target(angle)
                    
        else:
            pass # Manual override is active

    for s in servos.values():
        s.update(dt)
    
    if mode != current_mode:
        if current_mode == 0 and mode == 1:
            save_config()
            if "Neutral" in brain.get("poses", {}):
                test_pose("Neutral") 
            
        current_mode = mode
        mode_name = "CALIBRATION/HARDWARE" if mode == 0 else "POSING/RUN MODE"
        print(f"\n\n--- {mode_name} ---")
        print(f"Selected: {servo_names[selected_idx]}\n> ", end="")

        if mode == 0 and "Calibrate" in brain.get("poses", {}):
            test_pose("Calibrate")

    # --- CLI Input Polling ---
    # --- CLI Input Polling ---
    # --- CLI Input Polling ---
    if spoll.poll(0):                     
        line = sys.stdin.readline()       
        if line:
            clean_buf = line.strip()
            
            # 1. ADD THESE TWO LINES TO CATCH EMPTY STRINGS:
            if not clean_buf:
                pass
                
            # 2. CHANGE THIS 'if' TO an 'elif':
            elif clean_buf.startswith("{") and clean_buf.endswith("}"):
                try:
                    # ... (the rest of your json loading code stays the same)
                
#             # 1. IS IT WEBCAM JSON DATA?
#             if clean_buf.startswith("{") and clean_buf.endswith("}"):
#                 try:
                    incoming_weights = json.loads(clean_buf)
                    
                    manual_override = False
                    current_manual_weights.clear()
                    for pose_name, weight in incoming_weights.items():
                        # AUTOMATIC FORMATTING: "jawOpen" -> "Jawopen"
                        formatted_name = pose_name[0].upper() + pose_name[1:].lower() if len(pose_name) > 0 else pose_name
                        current_manual_weights[formatted_name] = weight
                        
                    # DEBUG PRINT: Verify it translated correctly!
#                         print(f"\r[WEBCAM] {current_manual_weights}          ", end="")
                except Exception as e:
                    pass 
                    
            # 2. OR IS IT A TYPED COMMAND?
            else:
                parts = clean_buf.split(" ")
                cmd = parts[0].lower()
                
                if cmd == "save" and len(parts) > 1:
                    save_pose(parts[1])
                elif cmd == "test" and len(parts) > 1:
                    manual_override = False 
                    test_pose(parts[1])
                elif cmd == "blend" and len(parts) > 2:
                    try:
                        weight = float(parts[2])
                        pose_name = find_pose_name(parts[1])
                        manual_override = False 
                        set_blend({pose_name: weight})
                    except ValueError:
                        print("\n[ERROR] Weight must be a number (e.g., 0.5)")
                elif cmd == "neutral":
                    manual_override = False 
                    set_blend({}) 
                elif cmd == "life" and len(parts) > 1:
                    if parts[1].lower() == "on":
                        manual_override = False 
                        life_engine.enable(servos["EYE_LATERAL"].target, servos["EYE_VERTICAL"].target)
                        print("\n[LIFE] Autonomous idling ENABLED.")
                    elif parts[1].lower() == "off":
                        manual_override = True 
                        life_engine.disable()
                        print("\n[LIFE] Autonomous idling DISABLED.")
                elif cmd == "play" and len(parts) > 1:
                    if parts[1].lower() == "test":
                        manual_override = False 
                        animator.play(TEST_SPEECH)
                        print("\n[ANIMATOR] Playing Test Speech...")
                else:
                    print(f"\nUnknown command: '{clean_buf}'.")
                
                print("\n> ", end="") 
                 
            
    # Read Hardware Inputs
    delta = encoder.get_delta()
    
    if delta != 0:
        manual_override = True 
        btn_cycle = encoder_sw.is_pressed()
        btn_action = action_btn.is_pressed()
        
        current_servo_name = servo_names[selected_idx]
        active_servo = servos[current_servo_name]

        if btn_cycle:
            if current_mode == 0: 
                if "Calibrate" not in brain["poses"]: brain["poses"]["Calibrate"] = {}
                brain["poses"]["Calibrate"][current_servo_name] = active_servo.target
                
            selected_idx = (selected_idx + 1) % len(servo_names)
            print(f"\nSelected: {servo_names[selected_idx]}\n> ", end="")
            
        if delta != 0:
            multiplier = 5 if (current_mode == 0 and action_btn.pin.value() == 0) else 1
            active_servo.set_target(active_servo.target + (delta * multiplier))
            print(f"\r{current_servo_name} Angle: {active_servo.target:>5.1f}    ", end="")
        


    time.sleep_ms(1)