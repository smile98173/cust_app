"""Replay the active 2026-09-18 feedback cases against the existing 8123 backend."""

from __future__ import annotations

import verify_feedback_20260917 as runner


def fee_comparison_check(turns: list[dict]) -> list[str]:
    errors: list[str] = []
    for index in (1, 2, 3):
        if index >= len(turns):
            continue
        answer = turns[index]["answer"]
        errors += [
            f"第 {index + 1} 輪：{error}"
            for error in runner.require_text(answer, "550", "6,550")
        ]
        errors += [
            f"第 {index + 1} 輪：{error}"
            for error in runner.forbid_text(answer, "銷售價格（客戶實際支付金額）：")
            if answer.strip().endswith("：")
        ]
    difference_answer = turns[2]["answer"] if len(turns) > 2 else ""
    if "50" not in difference_answer:
        errors.append("詢問月繳與年繳差別時，未說明月繳 12 個月比年繳多 50 元")
    return errors


def remote_learning_check(turns: list[dict]) -> list[str]:
    turn = turns[-1]
    answer = turn["answer"]
    errors = runner.require_text(answer, "學習", "燈")
    errors += runner.forbid_text(answer, "基本收費", "裝機費", "LINE TV")
    if turn.get("router", {}).get("intent") != "remote_power_learning":
        errors.append(f"intent 應為 remote_power_learning，實際為 {turn.get('router', {}).get('intent')}")
    if turn.get("router", {}).get("route") != "knowledge_query":
        errors.append(f"route 應為 knowledge_query，實際為 {turn.get('router', {}).get('route')}")
    return errors


def install_visit_check(turns: list[dict]) -> list[str]:
    answer = turns[-1]["answer"]
    return runner.require_text(answer, "排程", "預約時段", "聯繫") + runner.forbid_text(
        answer, "真人", "客服電話", "(04)"
    )


def points_merge_check(turns: list[dict]) -> list[str]:
    answer = turns[-1]["answer"]
    return runner.require_text(answer, "不同用戶編號", "分開累積", "無法合併", "轉移") + runner.forbid_text(
        answer, "購買台數科商品", "優惠福利"
    )


def broadband_termination_check(turns: list[dict]) -> list[str]:
    errors: list[str] = []
    for turn in turns:
        errors += runner.require_text(turn["answer"], "數據機")
        errors += runner.forbid_text(turn["answer"], "轉真人", "真人文字客服", "客服電話", "(04)")
    return errors


CASES = [
    {
        "id": "FB-20260918105830-9D49AE",
        "messages": ["月繳跟年繳差多少？", "有線電視", "金額呢?差別?", "沒有看到金額", "電視費用多少?"],
        "check": fee_comparison_check,
    },
    {
        "id": "FB-20260918104208-4B4B50",
        "messages": ["中投的遙控要怎麼用電視遙控", "中投機上盒遙控器」控制電視的電源／音量"],
        "check": remote_learning_check,
    },
    {
        "id": "FB-20260918100959-1B5ECE",
        "messages": ["請問 今天早上會來我家裝網路嗎？"],
        "check": install_visit_check,
    },
    {
        "id": "FB-20260918100304-399762",
        "messages": ["請問我兩個用戶編號的哈point點數可以合起來嗎？"],
        "check": points_merge_check,
    },
    {
        "id": "FB-20260918100135-C75AB2",
        "messages": ["退租網路", "要帶那些設備?"],
        "check": broadband_termination_check,
    },
    {
        "id": "FB-20260917133914-005410",
        "messages": ["我有預約今早到府維修的工作", "人員是否會到？", "要怎麼聯絡"],
        "check": runner.repair_visit_check,
    },
    {
        "id": "FB-20260917130649-785DF9",
        "messages": ["我要移機", "移機流程與可能收費", "移機流程和費用"],
        "check": runner.relocation_check,
    },
]


if __name__ == "__main__":
    runner.CASES = CASES
    runner.main()
