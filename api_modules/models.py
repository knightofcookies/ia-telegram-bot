from sqlalchemy import Text, Boolean, Column, Integer, String, Float, ForeignKey, DateTime, BigInteger, JSON
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()  # Create the Base class

# Update Subscription model
class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("plans.id"))  # Foreign key to Plan
    plan = relationship("Plan")  # Relationship to Plan
    status = Column(String(255))
    user_id = Column(Integer, ForeignKey("Users.id"))
    user = relationship("User", back_populates="subscriptions")
    payments = relationship("Payment", back_populates="subscription")
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)

class User(Base):
    __tablename__ = "Users"
    id = Column(Integer, primary_key=True, index=True, nullable=False)
    user_id = Column(BigInteger, unique=True, nullable=False)  # Prevent duplicate Telegram IDs
    name = Column(String(255))
    username = Column(String(255))
    subscriptions = relationship("Subscription", back_populates="user")

class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255))
    price = Column(Float)
    duration_days = Column(Integer)
    telegram_channel_id = Column(String(255), nullable=True)  # Changed from group_id to channel_id
    description = Column(String(8191))

class Payment(Base):
    __tablename__ = "payments"
    subscription = relationship("Subscription", back_populates="payments")
    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Float)
    status = Column(String(50))  # pending/verified/invalid/pending_verification
    receipt_url = Column(String(512))  # Store the local URL
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"))
    is_international = Column(Boolean, default=False)  # Flag for international payments

class TicketReply(Base):
    __tablename__ = "TicketReplies"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("SupportTickets.id"))
    reply = Column(Text)
    replied_by = Column(Integer, ForeignKey("Users.id"))
    timestamp = Column(DateTime)
    ticket = relationship("SupportTicket", back_populates="replies")
    replier = relationship("User")

class CustomerCarePersonnel(Base):
    __tablename__ = "CustomerCarePersonnel"  # Match exact case
    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    email = Column(String(255))
    telegram_user_id = Column(BigInteger, unique=True, nullable=True)  # New field

class SupportTicket(Base):
    __tablename__ = "SupportTickets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("Users.id"))
    issue = Column(Text)
    resolved = Column(Boolean, default=False)
    attachments = Column(JSON)  # Store attachments as JSON
    replies = relationship("TicketReply", back_populates="ticket")
    created_at = Column(DateTime, default=datetime.utcnow)  # Add this line
