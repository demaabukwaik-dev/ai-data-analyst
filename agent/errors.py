class NeedsClarification(Exception):
    """The question is unclear: the message asks the user something."""
    pass

class CannotAnswer(Exception):
    """The question cannot be answered with the supported tools or data."""
    pass

# Shown when the model's reply cannot be read, in any stage.
BROKEN_REPLY = ("Something went wrong while analysing this question. "
                "Please try again, or ask it in a different way.")


# Shown when the model says the question asks for more than one result
ONE_AT_A_TIME_REPLY = ("Your question asks for more than one result. "
                       "Please ask them one at a time.")

