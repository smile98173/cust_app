import json
from typing import TypedDict, Optional, Dict, Any

from fastapi import FastAPI
from pydantic import BaseModel

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3


SERVICE_SOP = {
    "network": {
        "slots": ["modem_light", "reboot_done"],
        "prompt": "你是網路報修助手。請確認數據機燈號(紅/綠/沒亮)以及用戶是否嘗試過重啟。"
    },
    "television": {
        "slots": ["error_code", "screen_status"],
        "prompt": "你是電視客服。請確認螢幕上的錯誤代碼（如E200）以及畫面狀況（黑屏/無訊號）。"
    },
    "billing": {
        "slots": ["id_last_four", "issue_type"],
        "prompt": "你是帳務專員。請核對用戶身分證末四碼，並確認問題類型。"
    }
}

class AgentState(TypedDict, total=False):
    current_service: Optional[str]
    extracted_slots: Dict[str, Any]
    user_input: str
    ai_response: str

llm = ChatOllama(
    model="gemma4:e4b",
    temperature=0.5
)

def supervisor_node(state: AgentState):
    if state.get("current_service"):
        return {}

    prompt = ChatPromptTemplate.from_template(
        "根據用戶輸入：'{user_input}'，判斷屬於以下哪類：network, television, billing。"
        "只需回覆類別名稱，若無法判斷請回覆 unknown。"
    )
    chain = prompt | llm
    response = chain.invoke({"user_input": state["user_input"]})
    service = response.content.strip().lower()

    return {"current_service": service if service in SERVICE_SOP else None}

def extractor_node(state: AgentState):
    service = state.get("current_service")
    if not service or service == "unknown":
        return {}

    sop = SERVICE_SOP[service]
    prompt = ChatPromptTemplate.from_template(
        "你是一個資訊提取助手。當前情境：{service}。需提取欄位：{slots}。\n"
        "用戶說：'{user_input}'。\n"
        "請以 JSON 格式回覆已識別的資訊，若未提及則不需包含該欄位。\n"
        "不要輸出 JSON 以外的任何文字。"
    )
    chain = prompt | llm
    response = chain.invoke({
        "service": service,
        "slots": sop["slots"],
        "user_input": state["user_input"]
    })

    try:
        raw_content = response.content.strip()
        raw_content = raw_content.replace("```json", "").replace("```", "").strip()
        new_data = json.loads(raw_content)
        if not isinstance(new_data, dict):
            new_data = {}
    except Exception:
        new_data = {}

    updated_slots = {**state.get("extracted_slots", {}), **new_data}
    return {"extracted_slots": updated_slots}

def manager_node(state: AgentState):
    service = state.get("current_service")
    if not service or service == "unknown":
        return {
            "ai_response": "抱歉，我不確定您需要哪種服務。請描述您遇到的是網路、電視還是帳務問題？"
        }

    sop = SERVICE_SOP[service]
    current_info = state.get("extracted_slots", {})
    missing = [s for s in sop["slots"] if s not in current_info]

    if missing:
        prompt = ChatPromptTemplate.from_template(
            "情境：{prompt}\n"
            "目前已掌握資訊：{info}\n"
            "下一個要詢問的欄位是：{missing}\n"
            "請寫一句親切、精簡的客服詢問語句，並適度提供選項，引導用戶簡短回答。"
        )
        chain = prompt | llm
        resp = chain.invoke({
            "prompt": sop["prompt"],
            "info": current_info,
            "missing": missing[0]
        })
        return {"ai_response": resp.content.strip()}
    else:
        return {
            "ai_response": f"感謝提供資訊！您的 {service} 問題已填寫完畢，我們將儘速處理。"
        }

workflow = StateGraph(AgentState)
workflow.add_node("supervisor", supervisor_node)
workflow.add_node("extractor", extractor_node)
workflow.add_node("manager", manager_node)

workflow.set_entry_point("supervisor")
workflow.add_edge("supervisor", "extractor")
workflow.add_edge("extractor", "manager")
workflow.add_edge("manager", END)

conn = sqlite3.connect("customer_state.db", check_same_thread=False)
memory = SqliteSaver(conn)
graph = workflow.compile(checkpointer=memory)

app = FastAPI()

class ChatRequest(BaseModel):
    user_id: str
    user_input: str

@app.post("/chat")
async def chat(request: ChatRequest):
    config = {"configurable": {"thread_id": request.user_id}}

    current_state = graph.get_state(config)
    old_slots = current_state.values.get("extracted_slots", {}) if current_state and current_state.values else {}
    old_service = current_state.values.get("current_service") if current_state and current_state.values else None

    result = graph.invoke(
        {
            "user_input": request.user_input,
            "extracted_slots": old_slots,
            "current_service": old_service
        },
        config=config
    )

    return {
        "status": "success",
        "ai_response": result.get("ai_response", ""),
        "current_service": result.get("current_service"),
        "collected_info": result.get("extracted_slots", {})
    }

@app.get("/state/{user_id}")
async def get_state(user_id: str):
    config = {"configurable": {"thread_id": user_id}}
    state = graph.get_state(config)

    values = state.values if state and state.values else {}

    return {
        "user_id": user_id,
        "current_service": values.get("current_service"),
        "collected_info": values.get("extracted_slots", {})
    }

if __name__ == "__main__":
    import uvicorn
    print("啟動本地測試服務：http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)