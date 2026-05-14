import json
import os
from filelock import FileLock, Timeout
import logging

logger = logging.getLogger(__name__)

class WheelStateMachine:
    def __init__(self):
        """
        Initializes the Wheel Strategy State Machine.
        Safely loads or creates the data/wheel_state.json file to prevent
        race conditions during concurrent/daily executions.
        """
        self.state_file = "data/wheel_state.json"
        self.lock_file = "data/wheel_state.json.lock"

        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)

        self.state = self._load_state()

    def _load_state(self) -> dict:
        """
        Safely loads state from the JSON file using FileLock.
        If the file doesn't exist, initializes an empty state {}.
        """
        try:
            with FileLock(self.lock_file, timeout=10):
                if not os.path.exists(self.state_file):
                    logger.info(f"State file {self.state_file} not found. Initializing empty state.")
                    state = {}
                    with open(self.state_file, 'w') as f:
                        json.dump(state, f, indent=4)
                    return state

                with open(self.state_file, 'r') as f:
                    try:
                        return json.load(f)
                    except json.JSONDecodeError:
                        logger.error(f"State file {self.state_file} is corrupted. Re-initializing empty state.")
                        state = {}
                        with open(self.state_file, 'w') as f:
                            json.dump(state, f, indent=4)
                        return state
        except Timeout:
            logger.error("Timeout acquiring lock for wheel state file.")
            return {}

    def _save_state(self):
        """
        Safely saves the current state to the JSON file using FileLock.
        """
        try:
            with FileLock(self.lock_file, timeout=10):
                with open(self.state_file, 'w') as f:
                    json.dump(self.state, f, indent=4)
        except Timeout:
            logger.error("Timeout acquiring lock to save wheel state file.")

    def ensure_symbol_state(self, symbol: str):
        """
        Ensures that a symbol has the default state initialized.
        If it doesn't exist in the state, initializes it.
        """
        if symbol not in self.state:
            logger.info(f"Initializing state for new symbol: {symbol}")
            self.state[symbol] = {
                "current_stage": "IDLE",
                "active_position": None,
                "inventory": {
                    "assigned_shares": 0,
                    "average_cost_basis": 0.0
                },
                "realized_pnl": 0.0
            }
            self._save_state()
