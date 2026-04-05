"""Order state machine."""

VALID_TRANSITIONS = {
    "pending": ["confirmed", "cancelled"],
    "confirmed": ["shipped", "cancelled"],
    "shipped": ["delivered"],
    "delivered": [],
    "cancelled": [],
}

class Order:
    def __init__(self, order_id):
        self.order_id = order_id
        self.state = "pending"
        self.history = []

    def transition(self, new_state):
        if new_state not in VALID_TRANSITIONS.get(self.state, []):
            raise ValueError(f"Invalid transition from {self.state} to {new_state}. Valid transitions: {VALID_TRANSITIONS.get(self.state, [])}")
        self.state = new_state
        self.history.append({"from": self.history[-1]["to"] if self.history else "pending", "to": new_state, "timestamp": str(__import__("datetime").datetime.now())})

    def can_transition(self, new_state):
        return new_state in VALID_TRANSITIONS.get(self.state, [])

    def cancel(self):
        if not self.can_transition("cancelled"):
            raise ValueError(f"Cannot cancel from current state {self.state}")
        self.state = "cancelled"

    def get_history(self):
        return self.history
