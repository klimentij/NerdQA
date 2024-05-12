import litellm

class LiteLLMWrapper:
    def __init__(self):
        self.original_state = {}

    def __setattr__(self, name, value):
        if name == "original_state":
            # Allow setting the original_state attribute normally
            super().__setattr__(name, value)
        else:
            # Any other attribute is stored in the original_state dictionary
            self.original_state[name] = value

    def __getattr__(self, name):
        if name in self.original_state:
            return self.original_state[name]
        else:
            raise AttributeError(f"'LiteLLMWrapper' object has no attribute '{name}'")

    def set_state(self, state):
        self.original_state = state.copy()

    def run_with_state(self, state, tool, *args, **kwargs):
        # Save the original state
        original_state = self.original_state.copy()

        # Set the new state
        for key, value in state.items():
            setattr(litellm, key, value)

        # Run the tool
        result = tool(*args, **kwargs)

        # Restore the original state
        for key, value in original_state.items():
            setattr(litellm, key, value)

        return result

    def completion(self, *args, **kwargs):
        return self.run_with_state(self.original_state, litellm.completion, *args, **kwargs)

    def batch_completion(self, *args, **kwargs):
        return self.run_with_state(self.original_state, litellm.batch_completion, *args, **kwargs)
