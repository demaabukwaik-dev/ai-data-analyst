class MemoryStore:
    """The conversation about one file: every message, and a short summary
    of the older ones."""

    def __init__(self):
        self.history = []
        self.summary = ""

    def add_user_message(self, message):
        self.history.append({"role": "user", "content": message})

    def add_ai_message(self, message, computed=None):
        self.history.append({"role": "ai", "content": message, "computed": computed})

    def get_history(self):
        return list(self.history)

    def set_summary(self, summary):
        self.summary = summary

    def get_summary(self):
        return self.summary

    def clear_memory(self):
        self.history = []
        self.summary = ""
