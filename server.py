from fastapi import FastAPI, Depends, HTTPException, Security
from sqlalchemy.orm import Session
from api_modules import crud, models, schemas
from api_modules.database import engine, get_db
from fastapi.security import APIKeyHeader
import logging
from dotenv import load_dotenv
from os import getenv
import os
from fastapi.staticfiles import StaticFiles
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse
import uvicorn

class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        password = form.get("password")
        if password == getenv("ADMIN_PASSWORD"):
            request.session.update({"authenticated": True})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return request.session.get("authenticated", False)

load_dotenv()

# Add security middleware
api_key_header = APIKeyHeader(name="X-API-Key")

async def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API Key")

# Add structured logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Initialize the app
app = FastAPI()
authentication_backend = AdminAuth(secret_key=getenv("SECRET_KEY"))  # Add SECRET_KEY to .env
admin = Admin(app, engine, authentication_backend=authentication_backend)

class UserAdmin(ModelView, model=models.User):
    column_list = [models.User.id, models.User.username, models.User.user_id, models.User.name, models.User.subscriptions]

class SubscriptionAdmin(ModelView, model=models.Subscription):
    column_list = [models.Subscription.id, models.Subscription.plan_id, models.Subscription.plan, models.Subscription.status, models.Subscription.user_id, models.Subscription.user, models.Subscription.payments, models.Subscription.created_at, models.Subscription.expires_at]

class PlanAdmin(ModelView, model=models.Plan):
    column_list = [models.Plan.id, models.Plan.name, models.Plan.price, models.Plan.duration_days, models.Plan.telegram_channel_id, models.Plan.description]

class PaymentAdmin(ModelView, model=models.Payment):
    column_list = [models.Payment.subscription, models.Payment.id, models.Payment.amount, models.Payment.status, models.Payment.receipt_url, models.Payment.subscription_id]

class TicketReplyAdmin(ModelView, model=models.TicketReply):
    column_list = [models.TicketReply.id, models.TicketReply.ticket_id, models.TicketReply.reply, models.TicketReply.replied_by, models.TicketReply.timestamp, models.TicketReply.ticket, models.TicketReply.replier]

class CustomerCarePersonnelAdmin(ModelView, model=models.CustomerCarePersonnel):
    column_list = [models.CustomerCarePersonnel.id, models.CustomerCarePersonnel.name, models.CustomerCarePersonnel.email, models.CustomerCarePersonnel.telegram_user_id]

class SupportTicketAdmin(ModelView, model=models.SupportTicket):
    column_list = [models.SupportTicket.id, models.SupportTicket.user_id, models.SupportTicket.issue, models.SupportTicket.resolved, models.SupportTicket.attachments, models.SupportTicket.replies, models.SupportTicket.created_at]

admin.add_view(UserAdmin)
admin.add_view(SubscriptionAdmin)
admin.add_view(PlanAdmin)
admin.add_view(PaymentAdmin)
admin.add_view(TicketReplyAdmin)
admin.add_view(CustomerCarePersonnelAdmin)
admin.add_view(SupportTicketAdmin)


os.makedirs("receipts", exist_ok=True)
app.mount("/receipts", StaticFiles(directory="receipts"), name="receipts")

# Create tables on startup
@app.on_event("startup")
async def startup_event():
    models.Base.metadata.create_all(bind=engine)

@app.get("/subscriptions/")
def read_subscriptions(db: Session = Depends(get_db)):
    # Join Subscription with Plan to access plan name
    subscriptions = db.query(models.Subscription).join(models.Plan).all()

    # Build response with plan name
    response = []
    for sub in subscriptions:
        response.append({
            "id": sub.id,
            "telegram_user_id": sub.user.user_id,  # Show Telegram ID
            "plan": sub.plan.name,  # Access plan name via relationship
            "status": sub.status,
            "created_at": sub.created_at,
            "expires_at": sub.expires_at
        })
    return response

@app.get("/subscriptions/{subscription_id}")
def read_subscription(subscription_id: int, db: Session = Depends(get_db)):
    db_subscription = crud.get_subscription(db, subscription_id)
    if db_subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return db_subscription

@app.put("/subscriptions/{subscription_id}")
def update_subscription(subscription_id: int, subscription: schemas.SubscriptionUpdate, db: Session = Depends(get_db)):
    db_subscription = crud.update_subscription(db, subscription_id, subscription)
    if db_subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return db_subscription

@app.delete("/subscriptions/{subscription_id}")
def delete_subscription(subscription_id: int, db: Session = Depends(get_db)):
    if crud.delete_subscription(db, subscription_id):
        return {"message": "Subscription deleted"}
    raise HTTPException(status_code=404, detail="Subscription not found")

# Support tickets endpoints
@app.post("/support/tickets/", response_model=schemas.SupportTicketResponse)  # Updated response model
def create_support_ticket(ticket: schemas.SupportTicketCreate, db: Session = Depends(get_db)):
    return crud.create_support_ticket(db, ticket)

@app.get("/support/tickets/")
def read_support_tickets(db: Session = Depends(get_db)):
    tickets = crud.get_support_tickets(db)
    return tickets

@app.get("/support/tickets/{ticket_id}")
def read_support_ticket(ticket_id: int, db: Session = Depends(get_db)):
    db_ticket = crud.get_support_ticket(db, ticket_id)
    if db_ticket is None:
        raise HTTPException(status_code=404, detail="Support ticket not found")
    return db_ticket

@app.put("/support/tickets/{ticket_id}")
def update_support_ticket(ticket_id: int, ticket: schemas.SupportTicketUpdate, db: Session = Depends(get_db)):
    db_ticket = crud.update_support_ticket(db, ticket_id, ticket)
    if db_ticket is None:
        raise HTTPException(status_code=404, detail="Support ticket not found")
    return db_ticket

@app.delete("/support/tickets/{ticket_id}")
def delete_support_ticket(ticket_id: int, db: Session = Depends(get_db)):
    if crud.delete_support_ticket(db, ticket_id):
        return {"message": "Support ticket deleted"}
    raise HTTPException(status_code=404, detail="Support ticket not found")

# Users endpoints
@app.post("/users/", response_model=schemas.UserCreate)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    return crud.create_user(db, user)

@app.get("/users/telegram/{telegram_user_id}", response_model=schemas.UserCreate)
def read_user_by_telegram_id(telegram_user_id: int, db: Session = Depends(get_db)):
    db_user = crud.get_user_by_telegram_id(db, telegram_user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

@app.post("/payments/confirm/")
def confirm_payment(payment_details: schemas.PaymentDetails, db: Session = Depends(get_db)):
    subscription = crud.get_subscription(db, payment_details.subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # In confirm_payment endpoint (FastAPI main.py)
    # Add error handling for missing payment
    payment = crud.get_payment_by_subscription(db, payment_details.subscription_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found")
    if payment.status == "verified":
        raise HTTPException(400, "Payment already verified")

    payment.status = "verified"
    subscription.status = "active"
    db.commit()

    # In real implementation: Create payment record, send notifications, etc.
    return {
        "message": "Payment confirmed",
        "subscription_id": subscription.id,
        "new_status": subscription.status
    }

@app.get("/subscriptions/telegram/{telegram_user_id}")
def read_subscriptions_by_telegram(
    telegram_user_id: int,
    db: Session = Depends(get_db)
):
    user = crud.get_user_by_telegram_id(db, telegram_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Join Subscription with Plan to access plan name
    subscriptions = db.query(models.Subscription).join(models.Plan).filter(models.Subscription.user_id == user.id).all()

    # Build response with plan name
    response = []
    for sub in subscriptions:
        response.append({
            "id": sub.id,
            "telegram_user_id": user.user_id,
            "plan": sub.plan.name,  # Access plan name via relationship
            "status": sub.status,
            "created_at": sub.created_at,
            "expires_at": sub.expires_at
        })
    return response

@app.post("/plans/", response_model=schemas.PlanCreate)
def create_plan(plan: schemas.PlanCreate, db: Session = Depends(get_db)):
    return crud.create_plan(db, plan)

@app.get("/plans/")
def read_plans(db: Session = Depends(get_db)):
    return db.query(models.Plan).all()

@app.post("/payments/{subscription_id}/initiate")
def initiate_payment(subscription_id: int, db: Session = Depends(get_db)):
    subscription = crud.get_subscription(db, subscription_id)
    if not subscription:
        raise HTTPException(404, "Subscription not found")

    plan = db.query(models.Plan).get(subscription.plan_id)

    # Create actual payment record
    payment_data = {
        "subscription_id": subscription_id,
        "amount": plan.price,
        "status": "pending",
        "receipt_url": "pending_upload"  # Temporary value
    }

    db_payment = models.Payment(**payment_data)
    db.add(db_payment)
    db.commit()
    db.refresh(db_payment)

    return {
        "vpa": getenv("VPA"),
        "amount": plan.price,
        "payment_id": db_payment.id  # Return real payment ID
    }

@app.post("/subscriptions/", response_model=schemas.SubscriptionResponse, tags=["Subscriptions"])
def create_subscription(subscription: schemas.SubscriptionCreate, db: Session = Depends(get_db), api_key: str = Depends(get_api_key)):
    return crud.create_subscription(db, subscription)

# Add staff endpoints
@app.get("/staff/pending-payments", tags=["Staff"])
def get_pending_payments(db: Session = Depends(get_db)):
    payments = db.query(models.Payment).filter(models.Payment.status == "pending_verification").all()
    return [
        {
            "id": payment.id,
            "amount": payment.amount,
            "subscription_id": payment.subscription_id,
        }
        for payment in payments
    ]

@app.post("/staff/tickets/{ticket_id}/reply", tags=["Staff"])
def create_ticket_reply(ticket_id: int, reply: schemas.TicketReplyCreate, db: Session = Depends(get_db)):
    db_ticket = crud.get_support_ticket(db, ticket_id)
    if not db_ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    db_reply = models.TicketReply(**reply.dict())
    db.add(db_reply)
    db.commit()
    db.refresh(db_reply)
    return db_reply

@app.get("/staff/check/{telegram_user_id}")
def check_staff(telegram_user_id: int, db: Session = Depends(get_db)):
    staff = db.query(models.CustomerCarePersonnel).filter(
        models.CustomerCarePersonnel.telegram_user_id == telegram_user_id
    ).first()
    return {"is_staff": staff is not None}  # Return a JSON object

@app.put("/payments/{payment_id}/verify")
def verify_payment(payment_id: int, db: Session = Depends(get_db)):
    payment = db.query(models.Payment).get(payment_id)
    if not payment:
        raise HTTPException(404, "Payment not found")

    payment.status = "verified"
    subscription = payment.subscription
    subscription.status = "active"

    user = subscription.user
    plan = subscription.plan

    db.commit()

    return {
        "status": "verified",
        "telegram_user_id": user.user_id,
        "telegram_channel_id": plan.telegram_channel_id if hasattr(plan, "telegram_channel_id") else None,
        "plan_name": plan.name
    }

@app.put("/payments/{payment_id}/reject")
def reject_payment(payment_id: int, db: Session = Depends(get_db)):
    payment = db.query(models.Payment).get(payment_id)
    payment.status = "invalid"
    subscription = payment.subscription
    subscription.status = "expired"
    db.commit()
    return {"status": "rejected"}

@app.get("/payments/{payment_id}")
def read_payment(payment_id: int, db: Session = Depends(get_db)):
    payment = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment

@app.put("/payments/{payment_id}")
def update_payment(
    payment_id: int,
    payment_update: schemas.PaymentCreate,
    db: Session = Depends(get_db)
):
    db_payment = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if not db_payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    # Update fields
    db_payment.receipt_url = payment_update.receipt_url
    db_payment.amount = payment_update.amount
    db_payment.status = "pending_verification"  # Set appropriate status

    db.commit()
    db.refresh(db_payment)
    return db_payment

@app.get("/users/{user_id}", response_model=schemas.UserResponse)
def read_user(user_id: int, db: Session = Depends(get_db)):
    db_user = crud.get_user(db, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000)
