from __future__ import annotations

import json
import os
import uuid

import requests


BASE_URL = "http://127.0.0.1:8123"
QUERIES = [
    ("stb_password_1", "機上盒出現要輸入密碼?"),
    ("stb_password_2", "機上盒出現要輸入密碼?"),
    ("stb_password_3", "機上盒出現要輸入密碼?"),
    ("account_transfer", "第四台及光纖，要更換用戶需要怎麼申辦呢？"),
    ("invoice_carrier", "發票加入手機條碼"),
]


def main() -> None:
    name = os.environ["TEST_API_AUTH_NAME"]
    password = os.environ["TEST_API_AUTH_PASSWORD"]
    auth = requests.post(
        f"{BASE_URL}/api/auth/token",
        json={"name": name, "password": password},
        timeout=30,
    )
    auth.raise_for_status()
    headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}

    results = []
    for label, message in QUERIES:
        user_id = f"targeted_{label}_{uuid.uuid4().hex}"
        response = requests.post(
            f"{BASE_URL}/chat",
            headers=headers,
            json={
                "user_id": user_id,
                "user_input": message,
                "tv_cable": "tdtv",
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        results.append(
            {
                "label": label,
                "question": message,
                "answer": payload.get("ai_response") or payload,
            }
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
