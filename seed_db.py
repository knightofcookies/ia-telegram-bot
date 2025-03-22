from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from api_modules.models import Plan, CustomerCarePersonnel
from api_modules.database import DATABASE_URL
from dotenv import load_dotenv
from os import getenv

load_dotenv()

# Initialize the database engine
engine = create_engine(DATABASE_URL)

# Create a session
session = Session(engine)

# Seed initial data
def seed_data():
    # Add subscription plans
    plans = [
        Plan(name="Basic", price=500, duration_days=60, telegram_channel_id=getenv('BASIC_CHANNEL_ID')),
        Plan(name="Premium", price=2000, duration_days=60, telegram_channel_id=getenv('PREMIUM_CHANNEL_ID')),
        Plan(name="Premium Plus", price=5000, duration_days=60, telegram_channel_id=getenv('PREMIUM_PLUS_CHANNEL_ID')),
    ]
    session.add_all(plans)

    # Add staff members
    staff_members = [
        CustomerCarePersonnel(name="John Doe", email="john@example.com", telegram_user_id=getenv('STAFF_CHAT_ID')),
    ]
    session.add_all(staff_members)

    # Commit the changes
    session.commit()
    print("Database seeded successfully!")

if __name__ == "__main__":
    seed_data()
