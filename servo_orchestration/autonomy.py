import random

class LifeEngine:
    def __init__(self):
        self.is_active = False

        # Timers
        self.timer_macro = 0.0
        self.timer_micro = 0.0
        self.timer_blink = 0.0

        # Current Offsets
        self.focal_pan = 0.0
        self.focal_tilt = 0.0
        self.micro_pan = 0.0
        self.micro_tilt = 0.0

        # Blink State Machine
        self.blink_state = "IDLE" # Can be IDLE, CLOSING, HOLDING, or OPENING
        self.blink_timer = 0.0
        
        # Output variables for main.py to read
        self.offsets = {}
        self.blend_weights = {}

    def enable(self, current_pan, current_tilt):
        self.is_active = True
        # Initialize the engine to where the eyes currently are to prevent jumping
        self.focal_pan = current_pan
        self.focal_tilt = current_tilt
        
        # Reset timers so it starts fresh
        self.timer_macro = 0.0
        self.timer_micro = 0.0
        self.timer_blink = random.uniform(2.0, 4.0)
        
    def disable(self):
        self.is_active = False
        self.offsets.clear()
        self.blend_weights.clear()
        self.blink_state = "IDLE"

    def update(self, dt):
        if not self.is_active:
            return

        self.timer_macro -= dt
        self.timer_micro -= dt
        self.timer_blink -= dt

        # 1. Macro Saccades (Big Darts)
        if self.timer_macro <= 0:
            self.timer_macro = random.uniform(3.0, 6.0) # Hold gaze for 2-5 seconds
            old_pan, old_tilt = self.focal_pan, self.focal_tilt
            
            # Pick new look target (+/- 15 degrees)
            self.focal_pan = random.uniform(-22.5, 22.50)
            self.focal_tilt = random.uniform(-22.5, 22.50)
            
# Saccade-Linked Blink check (Blink if moving eyes REALLY far)
            dist = abs(self.focal_pan - old_pan) + abs(self.focal_tilt - old_tilt)
            
            # CHANGE the 15.0 to 25.0 here:
            if dist > 25.0 and self.blink_state == "IDLE":
                self._trigger_blink()

        # 2. Micro Saccades (Jitter)
        if self.timer_micro <= 0:
            self.timer_micro = random.uniform(0.5, 1.5) # Twitch every 0.5-1.5 seconds
            self.micro_pan = random.uniform(-2.0, 2.0)
            self.micro_tilt = random.uniform(-2.0, 2.0)

        # 3. Autonomous Blinks (Standard Timeout)
        if self.timer_blink <= 0 and self.blink_state == "IDLE":
            self._trigger_blink()

        # 4. Handle Blink State Machine & Easing
        if self.blink_state != "IDLE":
            self.blink_timer -= dt
            
            if self.blink_state == "CLOSING":
                if self.blink_timer <= 0:
                    self.blink_state = "HOLDING"
                    self.blink_timer = random.uniform(0.01, 0.05) # Hold shut for 20-60ms
                    self.blend_weights["Blink"] = 1.0
                else:
                    # Snap shut extremely fast (Linear interpolation over 30ms)
                    t = 1.0 - (self.blink_timer / 0.03)
                    self.blend_weights["Blink"] = min(1.0, max(0.0, t))
                    
            elif self.blink_state == "HOLDING":
                self.blend_weights["Blink"] = 1.0
                if self.blink_timer <= 0:
                    self.blink_state = "OPENING"
                    self.blink_timer = 0.35 # Total time to open (150ms)
                    
            elif self.blink_state == "OPENING":
                if self.blink_timer <= 0:
                    self.blink_state = "IDLE"
                    self.blend_weights.pop("Blink", None) # Release the blendshape
                else:
                    # BIOLOGICAL EASING CURVE (Cubic Ease-Out)
                    t = 1.0 - (self.blink_timer / 0.35) 
                    self.blend_weights["Blink"] = max(0.0, (1.0 - t) ** 5)

        # 5. Calculate Kinematic Tracking Offsets
        total_tilt = self.focal_tilt + self.micro_tilt
        total_pan = self.focal_pan + self.micro_pan
        
        # --- Eyelid Tracking Multipliers ---
        # Adjust these +/- depending on your hardware polarity tests
        tl_ratio =  -0.8  
        tr_ratio = 0.8  
        ll_ratio = 0.4  
        lr_ratio = -0.4  
        
        self.offsets = {
            "EYE_LATERAL": total_pan,
            "EYE_VERTICAL": total_tilt,
            "TOP_LEFT_LID": total_tilt * tl_ratio,
            "TOP_RIGHT_LID": total_tilt * tr_ratio,
            "LOW_LEFT_LID": total_tilt * ll_ratio,
            "LOW_RIGHT_LID": total_tilt * lr_ratio
        }

    def _trigger_blink(self):
        self.blink_state = "CLOSING"
        self.blink_timer = 0.03 # 30ms to snap shut
        self.timer_blink = random.uniform(1.0, 4.0) # Next natural blink in 3-6s