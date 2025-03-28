from api_modules import models, schemas
from api_modules.database import SessionLocal
from datetime import timedelta, datetime
from sqlalchemy.orm import Session
import pytz

IST = pytz.timezone('Asia/Kolkata')

def create_subscription(db: Session, subscription: schemas.SubscriptionCreate):
    # Fetch the user by telegram_user_id
    db_user = db.query(models.User).filter(models.User.user_id == subscription.telegram_user_id).first()
    if not db_user:
        raise ValueError("User not found")

    # Fetch the plan by name
    db_plan = db.query(models.Plan).filter(models.Plan.name == subscription.plan).first()
    if not db_plan:
        raise ValueError("Invalid plan")

    ist_time = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(IST)

    # Create the subscription
    db_subscription = models.Subscription(
        plan_id=db_plan.id,  # Set plan_id instead of plan
        expires_at=ist_time + timedelta(days=db_plan.duration_days),
        user_id=db_user.id,
        status="pending_payment"
    )
    db.add(db_subscription)
    db.commit()
    db.refresh(db_subscription)

    # Return a response that matches SubscriptionResponse
    return {
        "id": db_subscription.id,
        "telegram_user_id": subscription.telegram_user_id,
        "plan": db_plan.name,  # Return the plan name as a string
        "status": db_subscription.status,
        "created_at": db_subscription.created_at,
        "expires_at": db_subscription.expires_at,
    }

# Add payment creation logic
def create_payment(db: Session, payment: schemas.PaymentCreate):
    db_payment = models.Payment(
        receipt_url=payment.receipt_url,  # Store the local URL
        amount=payment.amount,
        status="pending",
        subscription_id=payment.subscription_id
    )
    db.add(db_payment)
    db.commit()
    db.refresh(db_payment)
    return db_payment

# CRUD operations for subscriptions
def get_subscriptions(db: SessionLocal):
    return db.query(models.Subscription).all()

def get_subscription(db: SessionLocal, subscription_id: int):
    return db.query(models.Subscription).filter(models.Subscription.id == subscription_id).first()

def update_subscription(db: SessionLocal, subscription_id: int, subscription: schemas.SubscriptionUpdate):
    db_subscription = get_subscription(db, subscription_id)
    if db_subscription:
        db_subscription.plan = subscription.plan
        db_subscription.status = subscription.status
        db.commit()
        db.refresh(db_subscription)
        return db_subscription

def delete_subscription(db: SessionLocal, subscription_id: int):
    db_subscription = get_subscription(db, subscription_id)
    if db_subscription:
        db.delete(db_subscription)
        db.commit()
        return True
    return False

# CRUD operations for support tickets
def create_support_ticket(db: Session, ticket: schemas.SupportTicketCreate):
    db_user = get_user_by_telegram_id(db, ticket.telegram_user_id)
    if not db_user:
        raise ValueError("User not found")

    # Convert each Attachment to a dictionary
    attachments_data = [attachment.dict() for attachment in ticket.attachments] if ticket.attachments else []

    db_ticket = models.SupportTicket(
        user_id=db_user.id,
        issue=ticket.issue,
        attachments=attachments_data  # Now a JSON-serializable list
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    return db_ticket  # Matches SupportTicketResponse schema

def get_support_tickets(db: SessionLocal):
    return db.query(models.SupportTicket).all()

def get_support_ticket(db: SessionLocal, ticket_id: int):
    return db.query(models.SupportTicket).filter(models.SupportTicket.id == ticket_id).first()

def update_support_ticket(db: SessionLocal, ticket_id: int, ticket: schemas.SupportTicketUpdate):
    db_ticket = get_support_ticket(db, ticket_id)
    if db_ticket:
        if ticket.issue:
            db_ticket.issue = ticket.issue
        if ticket.resolved is not None:  # Missing resolution handling
            db_ticket.resolved = ticket.resolved
        db.commit()
        db.refresh(db_ticket)
        return db_ticket

def delete_support_ticket(db: SessionLocal, ticket_id: int):
    db_ticket = get_support_ticket(db, ticket_id)
    if db_ticket:
        db.delete(db_ticket)
        db.commit()
        return True
    return False

# User CRUD
def create_user(db: Session, user: schemas.UserCreate):
    db_user = models.User(**user.dict())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_user_by_telegram_id(db: Session, telegram_user_id: int):
    return db.query(models.User).filter(models.User.user_id == telegram_user_id).first()


def create_plan(db: Session, plan: schemas.PlanCreate):
    db_plan = models.Plan(**plan.dict())
    db.add(db_plan)
    db.commit()
    db.refresh(db_plan)
    return db_plan

def get_payment_by_subscription(db: Session, subscription_id: int):
    return db.query(models.Payment).filter(
        models.Payment.subscription_id == subscription_id
    ).first()

def create_staff_member(db: Session, staff: schemas.CustomerCarePersonnelCreate):
    db_staff = models.CustomerCarePersonnel(**staff.dict())
    db.add(db_staff)
    db.commit()
    db.refresh(db_staff)
    return db_staff

def create_support_ticket(db: Session, ticket: schemas.SupportTicketCreate):
    db_user = get_user_by_telegram_id(db, ticket.telegram_user_id)
    if not db_user:
        raise ValueError("User not found")

    # Convert Pydantic Attachment objects to dictionaries
    attachments_data = [attachment.dict() for attachment in ticket.attachments] if ticket.attachments else []

    # Create the support ticket with attachments
    db_ticket = models.SupportTicket(
        user_id=db_user.id,
        issue=ticket.issue,
        attachments=attachments_data  # Store as list of dicts
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    return db_ticket

def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()
