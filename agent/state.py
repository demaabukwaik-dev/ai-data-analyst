import uuid

def new_state():
    """A fresh state for one request."""
    return {
        "request_id": str(uuid.uuid4()),
        "request_classified": False,
        "authorized": None,
        "analysis_done": False,
        "result": None,
        "answer_text": None,         
        "filters_text": "",          
        "answered": False,
        "rejection_reason": None,
        "finished": False,
        "history": [],

        # Request decomposition
        "request_parts": [],
        "denied_parts": [],
        "question_to_run": None,     
        "classifier_error": False,

        # Column mapping and tool call
        "column_map": None,
        "tool_call": None,
        "stop_type": None,           

        # Raw model output, kept before extraction
        "follow_up_attempts": [],
        "classifier_attempts": [],
        "map_attempts": [],
        "tool_attempts": [],
        "generated_code": None,


        
        # Reading the conversation
        "conversation_read": False,
        "full_question": None,       # the question after reading the conversation
        "is_follow_up": False,
    }

