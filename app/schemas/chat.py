from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


class ChatRequest(BaseModel):
    user_id: str
    user_input: str
    tv_cable: str = "tdtv"
    receipt_evidence_token: Optional[str] = None


class ApiTokenRequest(BaseModel):
    name: str
    password: str


class WebChatRequest(BaseModel):
    user_id: str
    user_input: str
    tv_cable: str
    metadata: Dict[str, Any] = {}
    receipt_evidence_token: Optional[str] = None


class ChatUser(BaseModel):
    user_id: str
    member_id: Optional[str] = None
    custnum: Optional[str] = None
    custNo: Optional[str] = None
    cust_no: Optional[str] = None
    customerNo: Optional[str] = None
    customer_number: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    is_logged_in: Optional[bool] = None


class ChatCompany(BaseModel):
    company_code: str = "tdtv"


class ChatMessage(BaseModel):
    type: str = "text"
    text: str


class ChatHistoryMessage(BaseModel):
    role: str
    content: str


class ExternalChatRequest(BaseModel):
    user_id: Optional[str] = None
    member_id: Optional[str] = None
    custnum: Optional[str] = None
    custNo: Optional[str] = None
    cust_no: Optional[str] = None
    customerNo: Optional[str] = None
    customer_number: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    is_logged_in: Optional[bool] = None
    company_code: Optional[str] = None
    tv_cable: Optional[str] = None
    msg: Optional[str] = None
    request_id: Optional[str] = None
    channel: str = "web"
    user: Optional[ChatUser] = None
    company: ChatCompany = Field(default_factory=ChatCompany)
    message: Optional[ChatMessage] = None
    ai_state: Optional[Dict[str, Any]] = None
    history: List[ChatHistoryMessage] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    receipt_evidence_token: Optional[str] = None


class ImageTextRequest(BaseModel):
    image_base64: str
    mime_type: Optional[str] = None
    prompt: Optional[str] = None
    source: str = "api"
    user_id: Optional[str] = None


class KnowledgeUploadRequest(BaseModel):
    file_name: str
    file_base64: str
    title: Optional[str] = None
    knowledge_base: str = "通用"
    category: Optional[str] = None
    status: str = "active"


class KnowledgeSearchRequest(BaseModel):
    plan_name: str
    knowledge_base: str = "通用"
    category: Optional[str] = None
    limit: int = 5


class FeedbackRequest(BaseModel):
    user_id: str
    tv_cable: str = "tdtv"
    feedback_type: str = "bad_answer"
    suggestion: str
    user_message: Optional[str] = None
    ai_response: Optional[str] = None
    conversation: List[Dict[str, Any]] = []


class CompanyProfileUpdateRequest(BaseModel):
    address_phone: Optional[str] = None
    business_hours: Optional[str] = None
    service_area: Optional[str] = None
    service_products: Optional[str] = None
    area_outage: Optional[str] = None
    promotion_activity: Optional[str] = None
    urls: Optional[str] = None
    value_added_urls: Optional[str] = None
