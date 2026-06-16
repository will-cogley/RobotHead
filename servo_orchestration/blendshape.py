class BlendshapeEngine:
    def __init__(self, brain_data):
        self.brain = brain_data
        self.poses = {}
        self.neutral = {}
        self.deltas = {}
        self.reload(self.brain)

    def reload(self, brain_data):
        """Called on boot, or whenever you save a new pose."""
        self.brain = brain_data
        self.poses = self.brain.get("poses", {})
        self.neutral = self.poses.get("Neutral", {})
        self.deltas = {}
        self._calculate_deltas()

    def _calculate_deltas(self):
        """Calculates how far each servo moves from Neutral for every pose."""
        for pose_name, pose_data in self.poses.items():
            if pose_name == "Neutral":
                continue
            
            self.deltas[pose_name] = {}
            for servo_name, angle in pose_data.items():
                # Default to 90 if for some reason a servo isn't in Neutral yet
                neutral_angle = self.neutral.get(servo_name, 90.0) 
                self.deltas[pose_name][servo_name] = angle - neutral_angle

    def calculate_targets(self, weights):
        """
        Pass in a dictionary of weights, e.g., {"Smile": 1.0, "Angry": 0.5}
        Returns a dictionary of final calculated angles for every servo.
        """
        # 1. Start with a fresh copy of the Neutral face
        targets = dict(self.neutral)

        # 2. Add the weighted offsets for every requested pose
        for pose_name, weight in weights.items():
            if pose_name in self.deltas:
                for servo_name, delta in self.deltas[pose_name].items():
                    if servo_name in targets:
                        targets[servo_name] += (delta * weight)
                        
        return targets