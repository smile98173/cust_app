import streamlit as st
import uuid
import requests

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(page_title="AI 客服測試中心", page_icon="🤖")

st.title("🤖 智慧客服報修系統")
st.markdown("---")

if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

with st.sidebar:
    st.header("📊 報修單狀態")

    try:
        resp = requests.get(f"{API_BASE}/state/{st.session_state.user_id}", timeout=10)
        if resp.status_code == 200:
            current_state = resp.json()
        else:
            current_state = {}
    except Exception:
        current_state = {}

    service = current_state.get("current_service", "判斷中...")
    st.write(f"**目前情境：** {service}")

    slots = current_state.get("collected_info", {})
    st.write("**已收集資訊：**")
    if not slots:
        st.info("尚無資訊")
    else:
        for key, value in slots.items():
            st.success(f"✅ {key}: {value}")

for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("請描述您的問題 (例如：網路不能用)"):
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        resp = requests.post(
            f"{API_BASE}/chat",
            json={
                "user_id": st.session_state.user_id,
                "user_input": prompt
            },
            timeout=120
        )
        data = resp.json()
        ai_msg = data.get("ai_response", "系統沒有回應")
    except Exception as e:
        ai_msg = f"後端連線失敗：{e}"

    st.session_state.chat_history.append({"role": "assistant", "content": ai_msg})
    with st.chat_message("assistant"):
        st.markdown(ai_msg)

    st.rerun()