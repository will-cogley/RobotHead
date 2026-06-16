import time

class SmartServo:
    def __init__(self, hardware_manager, channel, min_angle=10, max_angle=170, max_speed=150, max_accel=300, start_angle=90.0):
        self.hw = hardware_manager
        
        # 1. Calculate the 0-indexed channel (Assuming 1-based input)
        # If your "Slot 1" is actually "PCA Pin 0", then channel - 1 is correct.
        internal_channel = channel - 1
        
        # 2. Use internal_channel for ALL hardware addressing
        self.i2c_addr = 0x40 if internal_channel < 16 else 0x41
        self.local_channel = internal_channel % 16
        
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.max_speed = max_speed
        self.max_accel = max_accel
        
        # Motion State
        self.pos = start_angle
        self.vel = 0.0
        self.target = start_angle
        
        # Snapping Tolerances to prevent micro-jitters
        self.pos_tolerance = 0.5  # degrees
        self.vel_tolerance = 5.0  # degrees/sec
        
        # Pre-calculate to save division operations in the hot loop
        self._inv_2_accel = 1.0 / (2.0 * self.max_accel)
        
        # Move to default position immediately
        self._write_pwm(self.pos)

    def set_target(self, target_angle):
        # Always clamp target requests to safe physical hardware limits
        self.target = max(self.min_angle, min(self.max_angle, target_angle))

    def update(self, dt):
        if dt <= 0: return

        error = self.target - self.pos
        dist = abs(error)

        # 1. The Snap Check: Are we close enough with low enough speed to just stop?
        if dist <= self.pos_tolerance and abs(self.vel) <= self.vel_tolerance:
            if self.pos != self.target: # Only update hardware if we aren't already there
                self.pos = self.target
                self.vel = 0.0
                self._write_pwm(self.pos)
            return

        # 2. Calculate Deceleration Profile
        dir_to_target = 1.0 if error > 0 else -1.0
        stopping_dist = (self.vel * self.vel) * self._inv_2_accel

        # 3. Determine Acceleration
        if dist <= stopping_dist:
            # We are inside the braking zone, apply brakes against our velocity
            accel = -1.0 * (1.0 if self.vel > 0 else -1.0) * self.max_accel
        else:
            # We are outside the braking zone, accelerate toward target
            accel = dir_to_target * self.max_accel

        # 4. Update Velocity (Euler Integration)
        self.vel += accel * dt
        # Clamp velocity to max speed limits
        self.vel = max(-self.max_speed, min(self.max_speed, self.vel))

        # 5. Predict the New Position
        new_pos = self.pos + (self.vel * dt)

        # 6. ANTI-OVERSHOOT MAGIC: Did this step cross the target?
        if (self.pos < self.target and new_pos >= self.target) or \
           (self.pos > self.target and new_pos <= self.target):
            # We crossed it! Snap exactly to target and kill momentum.
            self.pos = self.target
            self.vel = 0.0
        else:
            # Safe to move normally
            self.pos = new_pos

        # 7. Final Safety Clamp and Hardware Write
        self.pos = max(self.min_angle, min(self.max_angle, self.pos))
        self._write_pwm(self.pos)

    def _write_pwm(self, angle):
        # Convert 0-180 angle to PCA9685 12-bit pulse width
        # Standard servos generally use 150 to 600
        pulse = int(150 + (angle / 180.0) * (600 - 150))
        
        reg_base = 0x06 + 4 * self.local_channel
        
        try:
            self.hw.i2c.writeto_mem(self.i2c_addr, reg_base, b'\x00') 
            self.hw.i2c.writeto_mem(self.i2c_addr, reg_base + 1, b'\x00') 
            self.hw.i2c.writeto_mem(self.i2c_addr, reg_base + 2, bytes([pulse & 0xFF])) 
            self.hw.i2c.writeto_mem(self.i2c_addr, reg_base + 3, bytes([pulse >> 8])) 
        except Exception:
            pass # Fail silently to keep the loop running fast
