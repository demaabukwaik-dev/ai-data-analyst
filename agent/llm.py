import os
import streamlit as st
from openai import OpenAI
from agent.config import API_BASE, API_MODEL


def get_api_key():
    """The key comes from an environment variable or Streamlit secrets —
    never from the code."""

    key = os.environ.get("API_KEY")
    if key:
        return key
    try:
        return st.secrets["API_KEY"]
    except Exception:
        return None


_client = None

def ask_llm(messages, max_new_tokens=256):
    """Send a prompt to the model and return the reply as text."""
    
    global _client
    if _client is None:
        key = get_api_key()
        if not key:
            raise RuntimeError("No API key found. Add API_KEY to .streamlit/secrets.toml.")
        _client = OpenAI(base_url=API_BASE, api_key=key)

    completion = _client.chat.completions.create(
        model=API_MODEL,
        messages=messages,
        max_tokens=max_new_tokens,
        temperature=0,
    )
    return completion.choices[0].message.content.strip()