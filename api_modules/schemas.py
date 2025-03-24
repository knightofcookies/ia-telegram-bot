from datetime import datetime
from pydantic import BaseModel, confloat, conint
from typing import List, Optional

# Update SubscriptionCreate to remove duration_days
class SubscriptionCreate(BaseModel):
    telegram_user_id: int
    plan: str  # Plan name (should reference Plan ID in production)

# Update PlanCreate with validation
class PlanCreate(BaseModel):
    name: str
    price: confloat(gt=0)  # Ensures positive value
    duration_days: conint(gt=0)
    telegram_group_id: Optional[str] = None  # New field for Telegram group ID

class SubscriptionUpdate(BaseModel):
    plan: str | None = None
    status: str | None = None

class UserCreate(BaseModel):
    user_id: int
    name: str | None = None
    username: str | None = None

class PaymentDetails(BaseModel):
    subscription_id: int
    amount: float
    currency: str = "INR"

class SupportTicketUpdate(BaseModel):
    issue: str | None = None
    resolved: bool | None = None  # Add resolved field

class TicketReplyCreate(BaseModel):
    ticket_id: int
    reply: str
    replied_by: int

class PaymentCreate(BaseModel):
    subscription_id: int
    amount: float
    receipt_url: str  # Local URL of the receipt

class CustomerCarePersonnelCreate(BaseModel):
    name: str
    email: str

class SubscriptionResponse(BaseModel):
    id: int
    telegram_user_id: int  # Add this field
    plan: str  # Ensure this is a string, not a Plan object
    status: str
    created_at: datetime | None = None
    expires_at: datetime | None = None

class Attachment(BaseModel):
    type: str  # e.g., "photo", "document"
    file_id: str  # Telegram file ID

class SupportTicketCreate(BaseModel):
    telegram_user_id: int
    issue: str
    attachments: Optional[List[Attachment]] = None  # List of attachments

class SupportTicketResponse(BaseModel):
    id: int
    user_id: int
    issue: str
    resolved: bool
    attachments: Optional[List[dict]] = None  # Store as list of dicts
    created_at: datetime

    class Config:
        orm_mode = True  # Enable ORM compatibility

class StaffLogin(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    id: int
    user_id: int
    name: Optional[str] = None
    username: Optional[str] = None

    class Config:
        orm_mode = True
