import machine
from machine import Pin, I2C
import time

# --- Button Abstraction ---
class DebouncedButton:
    def __init__(self, pin_num, debounce_ms=50):
        self.pin = Pin(pin_num, Pin.IN, Pin.PULL_UP)
        self.debounce_ms = debounce_ms
        self.last_press_time = 0
        self.last_state = 1 # 1 is unpressed (PULL_UP)

    def is_pressed(self):
        current_state = self.pin.value()
        current_time = time.ticks_ms()
        
        # Check for falling edge (button press) with debounce
        if self.last_state == 1 and current_state == 0:
            if time.ticks_diff(current_time, self.last_press_time) > self.debounce_ms:
                self.last_press_time = current_time
                self.last_state = 0
                return True
                
        # Reset state on release
        if current_state == 1:
            self.last_state = 1
            
        return False

# --- Quadrature Encoder Abstraction ---
class RotaryEncoder:
    def __init__(self, pin_a_num, pin_b_num):
        self.pin_a = Pin(pin_a_num, Pin.IN, Pin.PULL_UP)
        self.pin_b = Pin(pin_b_num, Pin.IN, Pin.PULL_UP)
        
        self.position = 0
        self.last_state = self.pin_a.value()
        
        # Use an interrupt on Pin A so we never miss a step while the main loop runs
        self.pin_a.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._encoder_isr)

    def _encoder_isr(self, pin):
        # Read the current states
        a_val = self.pin_a.value()
        b_val = self.pin_b.value()
        
        # If A changed, check B to determine direction
        if a_val != self.last_state:
            if b_val != a_val:
                self.position += 1 # Clockwise
            else:
                self.position -= 1 # Counter-Clockwise
            self.last_state = a_val

    def get_delta(self):
        # Read how many steps have occurred since we last checked, and reset
        # Disable interrupts briefly so position doesn't change while reading
        state = machine.disable_irq()
        delta = self.position
        self.position = 0
        machine.enable_irq(state)
        return delta

# --- Main Hardware Manager ---
class SystemHardware:
    def __init__(self, i2c):
        self.i2c = i2c
        # Init the servo drivers
        self._init_pca(0x40)
        self._init_pca(0x41)
        # Banish the LED wheel init here
        self._init_led_wheel(0x3C)
        
    def _init_pca(self, addr):
        try:
            self.i2c.writeto_mem(addr, 0x00, b'\x00')
            self.i2c.writeto_mem(addr, 0x00, b'\x10')
            self.i2c.writeto_mem(addr, 0xFE, b'\x79') 
            self.i2c.writeto_mem(addr, 0x00, b'\x80')
            time.sleep_ms(1)
            self.i2c.writeto_mem(addr, 0x00, b'\xA1')
        except Exception as e:
            print(f"Failed to init PCA9685 at {hex(addr)}: {e}")

    def _init_led_wheel(self, addr):
        self.led_addr = addr
        try:
            self.i2c.writeto_mem(addr, 0x00, b'\x01')
            self.i2c.writeto_mem(addr, 0x4A, b'\x40')
            # Keeping your existing LED logic out of the way
            for i in range(1, 37):
                self.i2c.writeto_mem(addr, i, b'\x00')
            self.i2c.writeto_mem(addr, 0x00, b'\x01')
        except Exception as e:
            print(f"Failed to init LED wheel at {hex(addr)}: {e}")

