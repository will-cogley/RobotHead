class SequencePlayer:
    def __init__(self):
        self.is_playing = False
        self.timer = 0.0
        self.current_frame = 0
        self.sequence = []
        self.blend_weights = {}

    def play(self, sequence):
        """Starts playing a list of keyframes."""
        if not sequence: return
        self.sequence = sequence
        self.current_frame = 0
        self.is_playing = True
        
        # Load the very first frame
        frame = self.sequence[0]
        self.blend_weights = frame.get("weights", {})
        self.timer = frame.get("duration", 0.0)

    def stop(self):
        self.is_playing = False
        self.blend_weights = {} # Clear weights so the face relaxes

    def update(self, dt):
        """Called every loop to tick the timeline forward."""
        if not self.is_active():
            return

        self.timer -= dt
        
        # When the timer for the current frame runs out, move to the next one!
        if self.timer <= 0:
            self.current_frame += 1
            
            if self.current_frame >= len(self.sequence):
                self.stop() 
                return
                
            # Load next frame
            frame = self.sequence[self.current_frame]
            self.blend_weights = frame.get("weights", {})
            
            # Add any leftover negative time to keep the rhythm mathematically perfect
            self.timer = frame.get("duration", 0.0) + self.timer 

    def is_active(self):
        return self.is_playing