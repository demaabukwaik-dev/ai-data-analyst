import json
import uuid
import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel
from agent.agent import run_agent
from agent.context_manager import remember_turn
from agent.data import load_uploaded_csv
from agent.memory_store import MemoryStore

app = FastAPI(title="AI Data Analyst API")

datasets = {}
memories = {}       # one conversation memory per uploaded file


class Question(BaseModel):
    question: str


def to_json(result):

    if isinstance(result, pd.Series):
        result = result.reset_index()

    if isinstance(result, pd.DataFrame):
        return json.loads(result.to_json(orient="records", date_format="iso"))
    
    return result.item() if hasattr(result, "item") else result


@app.post("/datasets")
async def upload(file: UploadFile):

    df, error = load_uploaded_csv(file.filename, await file.read())

    if error:
        raise HTTPException(400, error)

    dataset_id = str(uuid.uuid4())
    datasets[dataset_id] = df
    memories[dataset_id] = MemoryStore()

    return {
            "dataset_id": dataset_id,
            "rows": len(df),
            "columns": list(df.columns),
            "first_rows": to_json(df.head(5))
            }


@app.post("/datasets/{dataset_id}/ask")
def ask(dataset_id: str, request: Question):
    
    if dataset_id not in datasets:
        raise HTTPException(404, "Unknown dataset. Upload the file again.")

    memory = memories[dataset_id]
    state = run_agent(request.question, datasets[dataset_id], memory=memory)
    remember_turn(memory, state)

    if state["answered"]:

        return {
                "outcome": "answer",
                "understood_as": state["full_question"],
                "answer": state["answer_text"],
                "filters": state["filters_text"],
                "result": to_json(state["result"]),
                "tool_call": state["tool_call"]
                }
    
    return {"outcome": state["stop_type"] or "NotAllowed",
            "understood_as": state["full_question"],
            "message": state["rejection_reason"]}