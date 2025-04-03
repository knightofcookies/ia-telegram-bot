import asyncio
import logging
import os
import time
from io import BytesIO
from functools import wraps
from typing import Callable, Dict, Any, Awaitable

import aiohttp
import dotenv
import qrcode
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.token import TokenValidationError
from aiogram.enums.parse_mode import ParseMode

# Load environment variables
dotenv.load_dotenv()

# Constants
TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
REDIS_URL = os.getenv("REDIS_URL")
STAFF_CHAT_ID = os.getenv("STAFF_CHAT_ID")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")  # Added env fallback
PLANS_DISCLAIMER = os.getenv("PLANS_DISCLAIMER")
MAX_FILE_SIZE_MB = 5  # 5MB maximum file size for receipts
STAFF_USERNAME = os.getenv("STAFF_USERNAME")
REMITLY_FIRST_NAME = os.getenv("REMITLY_FIRST_NAME")
REMITLY_LAST_NAME = os.getenv("REMITLY_LAST_NAME")
REMITLY_REASON = os.getenv("REMITLY_REASON", "Service payment")
REMITLY_BANK = os.getenv("REMITLY_BANK", "Bank account")
INTL_VPA = os.getenv("INTL_VPA")
DOM_VPA = os.getenv("DOM_VPA")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Rate limiting configuration
RATE_LIMITS = {
    "default": {"requests": 10, "seconds": 60},
    "payment_receipt": {"requests": 5, "seconds": 300},
    "support_ticket": {"requests": 2, "seconds": 3600},
}

# State definitions
class PaymentState(StatesGroup):
    WAITING_FOR_RECEIPT = State()

class SupportTicketState(StatesGroup):
    WAITING_FOR_ISSUE = State()
    COLLECTING_ADDITIONAL_INFO = State()

class TicketReplyState(StatesGroup):
    AWAITING_REPLY_TEXT = State()

# API client with retry logic
class APIClient:
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {"X-API-Key": api_key}
        self.retries = 3
        self.retry_delay = 1

    async def request(self, method, endpoint, data=None):
        url = f"{self.base_url}{endpoint}"
        for attempt in range(self.retries):
            async with aiohttp.ClientSession(headers=self.headers) as session:
                try:
                    async with session.request(method, url, json=data) as response:
                        if response.status == 404:
                            return None
                        response.raise_for_status()
                        return await response.json()
                except aiohttp.ClientError as e:
                    if attempt < self.retries - 1:
                        logger.warning(f"API request failed (attempt {attempt+1}): {str(e)}")
                        await asyncio.sleep(self.retry_delay * (attempt + 1))
                        continue
                    logger.error(f"API request failed after {self.retries} attempts: {str(e)}")
                    return {"error": str(e)}
                except Exception as e:
                    logger.error(f"Unexpected error during API request: {str(e)}")
                    return {"error": "Internal server error"}

# Rate limiting middleware
class RateLimitingMiddleware:
    def __init__(self, storage, staff_service):
        self.storage = storage
        self.staff_service = staff_service  # Add staff service to check if user is staff

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # Check if the user is staff
        if await self.staff_service.is_staff(user.id):
            # Skip rate limiting for staff members
            return await handler(event, data)

        # Get rate limit config based on handler
        handler_name = handler.__name__
        rate_config = RATE_LIMITS.get(handler_name, RATE_LIMITS["default"])
        key = f"rate_limit:{user.id}:{handler_name}"

        redis = self.storage.redis
        current = await redis.get(key)
        if current and int(current) >= rate_config["requests"]:
            logger.warning(f"Rate limit exceeded for user {user.id} on {handler_name}")
            if isinstance(event, Message):
                await event.answer("🚫 Too many requests. Please slow down.")
            return
        await redis.incr(key)
        await redis.expire(key, rate_config["seconds"])

        return await handler(event, data)

# Utility functions with enhanced validation
class Utils:
    @staticmethod
    def generate_qr_code(data: str):
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color=(255, 105, 180), back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    @staticmethod
    async def save_file_locally(file_data, file_name):
        safe_file_name = os.path.basename(file_name)
        if not safe_file_name.lower().endswith(('.png', '.jpg', '.jpeg')):
            raise ValueError("Invalid file format")

        os.makedirs("receipts", exist_ok=True)
        file_path = os.path.join("receipts", safe_file_name)
        with open(file_path, "wb") as f:
            f.write(file_data)
        return f"{API_BASE_URL}/receipts/{safe_file_name}"

# Enhanced menu handlers with cache
class MenuHandlers:
    def __init__(self, api_client):
        self.api_client = api_client
        self.plans_cache = {"data": None, "expires": 0}

    async def get_plans(self):
        if time.time() < self.plans_cache["expires"]:
            return self.plans_cache["data"]

        plans = await self.api_client.request("GET", "/plans/")
        if plans and "error" not in plans:
            self.plans_cache = {"data": plans, "expires": time.time() + 300}  # Cache for 5 minutes
        return plans

    async def show_main_menu(self, message: Message):
        main_menu = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="💰 Purchase Subscription", callback_data="purchase_subscription"),
                    InlineKeyboardButton(text="📋 My Subscriptions", callback_data="view_subscriptions"),
                ],
                [
                    InlineKeyboardButton(text="🆘 Contact Support", callback_data="raise_support_ticket"),
                    InlineKeyboardButton(text="🔄 Refresh Menu", callback_data="main_menu"),
                ],
            ]
        )
        await message.answer("Main Menu:", reply_markup=main_menu)

    async def show_staff_dashboard(self, message: Message):
        staff_menu = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="💸 Pending Payments", callback_data="staff_payments"),
                    InlineKeyboardButton(text="🎫 Pending Tickets", callback_data="staff_tickets"),
                ],
                [
                    InlineKeyboardButton(text="📜 Subscriptions List", callback_data="staff_subscriptions"),
                    InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"),
                ],
            ]
        )
        await message.answer("Staff Dashboard:", reply_markup=staff_menu)

    async def show_staff_payments(self, message: Message):
        payments = await self.api_client.request("GET", "/staff/pending-payments")
        if not payments:
            await message.answer("No pending payments")
            return

        payment_buttons = [
            [InlineKeyboardButton(text=f"Payment ID: {p['id']} | ₹{p['amount']}", callback_data=f"payment_{p['id']}")]
            for p in payments
        ]
        payment_buttons.append([InlineKeyboardButton(text="🔄 Refresh", callback_data="staff_payments")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=payment_buttons)
        await message.answer("📋 Pending Payments:", reply_markup=keyboard)

    async def show_staff_tickets(self, message: Message):
        tickets = await self.api_client.request("GET", "/support/tickets/")
        if not tickets:
            await message.answer("No open support tickets.")
            return

        ticket_buttons = [
            [InlineKeyboardButton(text=f"Ticket #{t['id']} ({'Resolved' if t['resolved'] else 'Open'})", callback_data=f"ticket_{t['id']}")]
            for t in tickets if not t['resolved']
        ]
        ticket_buttons.append([InlineKeyboardButton(text="🔄 Refresh", callback_data="staff_tickets")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=ticket_buttons)
        await message.answer("📋 Open Support Tickets:", reply_markup=keyboard)

# Staff service
class StaffService:
    def __init__(self, api_client):
        self.api_client = api_client

    async def is_staff(self, telegram_user_id: int):
        response = await self.api_client.request("GET", f"/staff/check/{telegram_user_id}")
        if response and "error" not in response:
            return response.get("is_staff", False)
        return False

# Command handlers
class CommandHandlers:
    def __init__(self, api_client, menu_handlers, staff_service):
        self.api_client = api_client
        self.menu_handlers = menu_handlers
        self.staff_service = staff_service

    async def start_command(self, message: Message):
        telegram_user_id = message.from_user.id
        user_data = {
            "user_id": telegram_user_id,
            "name": message.from_user.full_name,
            "username": message.from_user.username,
            "email": None,
        }

        existing_user = await self.api_client.request("GET", f"/users/telegram/{telegram_user_id}")
        if existing_user is None:
            await self.api_client.request("POST", "/users/", user_data)
            await message.answer("Welcome! You have been registered.")
        else:
            await message.answer("Welcome back!")

        await self.menu_handlers.show_main_menu(message)

    async def staff_command(self, message: Message):
        if await self.staff_service.is_staff(message.from_user.id):
            await self.menu_handlers.show_staff_dashboard(message)
        else:
            await message.answer("Staff access denied")

# Callback handlers
class CallbackHandlers:
    def __init__(self, api_client, menu_handlers, utils):
        self.api_client = api_client
        self.menu_handlers = menu_handlers
        self.utils = utils

    async def handle_callback(self, query: CallbackQuery, state: FSMContext, bot: Bot):
        callback_data = query.data

        # First, answer the callback query to stop the loading state
        await query.answer()

        # Main menu
        if callback_data == "main_menu":
            await self.menu_handlers.show_main_menu(query.message)
            return

        # Subscription handling
        elif callback_data == "purchase_subscription":
            await self._handle_purchase_subscription(query)

        elif callback_data.startswith("plan_"):
            await self._handle_plan_selection(query, state)

        elif callback_data == "view_subscriptions":
            await self._handle_view_subscriptions(query)

        # Support ticket handling
        elif callback_data == "raise_support_ticket":
            await query.message.answer("Please describe your issue:")
            await state.set_state(SupportTicketState.WAITING_FOR_ISSUE)

        # Staff payment handling
        elif callback_data == "staff_payments":
            await self.menu_handlers.show_staff_payments(query.message)

        elif callback_data.startswith("payment_"):
            await self._handle_payment_details(query)

        elif callback_data.startswith("pay_method_local_"):
            await self._handle_local_payment(query, state)

        elif callback_data.startswith("pay_method_intl_"):
            await self._handle_international_payment(query, state)

        elif callback_data.startswith("verify_"):
            await self._handle_verify_payment(query)

        elif callback_data.startswith("reject_"):
            await self._handle_reject_payment(query, bot)

        # Staff ticket handling
        elif callback_data == "staff_tickets":
            await self.menu_handlers.show_staff_tickets(query.message)

        elif callback_data.startswith("ticket_"):
            await self._handle_ticket_details(query)

        elif callback_data.startswith("reply_ticket_"):
            await self._handle_reply_ticket(query, state)

        elif callback_data.startswith("resolve_ticket_"):
            await self._handle_resolve_ticket(query)

        # Staff subscription handling
        elif callback_data == "staff_subscriptions":
            await self._handle_staff_subscriptions(query)

        else:
            await query.message.answer("Unknown command. Please use the menu buttons.")

    async def _handle_ticket_details(self, query: CallbackQuery):
        ticket_id = int(query.data.split("_")[1])
        ticket = await self.api_client.request("GET", f"/support/tickets/{ticket_id}")

        if not ticket:
            await query.message.answer("Ticket not found.")
            return

        # Format the ticket details
        ticket_details = (
            f"📋 Ticket Details\n\n"
            f"Ticket ID: #{ticket['id']}\n"
            f"Status: {'Resolved' if ticket['resolved'] else 'Open'}\n"
            f"Issue: {ticket['issue']}\n"
            f"Created At: {ticket['created_at']}\n"
        )

        # Add replies if available
        if ticket.get("replies"):
            ticket_details += "\nReplies:\n"
            for reply in ticket["replies"]:
                ticket_details += f"- {reply['reply']} (by {reply['replied_by']})\n"

        # Create action buttons
        action_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Reply", callback_data=f"reply_ticket_{ticket_id}"),
                InlineKeyboardButton(
                    text="Resolve" if not ticket["resolved"] else "Reopen",
                    callback_data=f"resolve_ticket_{ticket_id}"
                ),
            ],
            [InlineKeyboardButton(text="← Back", callback_data="staff_tickets")]
        ])

        await query.message.answer(ticket_details, reply_markup=action_keyboard)

    # Helper methods for subscription handling
    async def _handle_purchase_subscription(self, query: CallbackQuery):
        plans = await self.menu_handlers.get_plans()
        if not plans or "error" in plans:
            await query.answer("Failed to load plans")
            return

        plan_buttons = [
            [InlineKeyboardButton(text=f"{p['name']} - ₹{p['price']}", callback_data=f"plan_{idx+1}")]
            for idx, p in enumerate(plans)
        ]
        plan_keyboard = InlineKeyboardMarkup(inline_keyboard=plan_buttons)
        await query.message.answer("Available subscription plans:", reply_markup=plan_keyboard)
        description_str = "\n\n".join(["<b>" + plans[i]['name'] + "</b>:\n" + plans[i]['description'] for i in range(len(plans))]) + "\n\n" + PLANS_DISCLAIMER
        await query.message.answer(description_str, parse_mode=ParseMode.HTML)

    async def _handle_plan_selection(self, query: CallbackQuery, state: FSMContext):
        plan_index = int(query.data.split("_")[1]) - 1
        plans = await self.menu_handlers.get_plans()
        if not plans or "error" in plans:
            await query.answer("Failed to load plans")
            return

        try:
            selected_plan = plans[plan_index]
        except IndexError:
            await query.message.answer("Invalid plan selection")
            return

        user_id = query.from_user.id
        subscription_data = {
            "telegram_user_id": user_id,
            "plan": selected_plan["name"],
        }
        subscription = await self.api_client.request("POST", "/subscriptions/", subscription_data)

        if not subscription or "error" in subscription:
            await query.message.answer("Failed to create subscription. Please try again.")
            return

        payment_info = await self.api_client.request("POST", f"/payments/{subscription['id']}/initiate")

        await state.update_data(
            subscription_id=subscription["id"],
            payment_id=payment_info["payment_id"],
            plan_price=selected_plan["price"]
        )

        # Show payment method selection
        payment_method_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇮🇳 Indian UPI Payment", callback_data=f"pay_method_local_{subscription['id']}")],
            [InlineKeyboardButton(text="🌍 International Payment (Remitly)", callback_data=f"pay_method_intl_{subscription['id']}")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="main_menu")]
        ])

        await query.message.answer(
            f"💳 Please select your payment method for {selected_plan['name']} (₹{selected_plan['price']}):",
            reply_markup=payment_method_keyboard
        )

    async def _handle_international_payment(self, query: CallbackQuery, state: FSMContext):
        """Handle international payment through Remitly with a separate UPI VPA"""
        subscription_id = int(query.data.split("_")[3])
        data = await state.get_data()
        payment_id = data.get("payment_id")
        plan_price = data.get("plan_price")

        # Update payment with international flag
        await self.api_client.request("PUT", f"/payments/{payment_id}", {
            "subscription_id": subscription_id,
            "amount": plan_price,
            "receipt_url": "pending_upload",
            "is_international": True
        })

        # Create detailed instructions for Remitly payment with international VPA
        instructions = (
            f"💱 <b>International Payment Instructions (Remitly)</b>\n\n"
            f"1️⃣ Open or download the Remitly app\n"
            f"2️⃣ Choose India as the destination country\n"
            f"3️⃣ Select <b>UPI Transfer</b> as the delivery method\n"
            f"4️⃣ Enter the following details:\n"
            f"   • VPA: <code>{INTL_VPA}</code>\n"  # Using the international VPA
            f"   • First Name: <code>{REMITLY_FIRST_NAME}</code>\n"
            f"   • Last Name: <code>{REMITLY_LAST_NAME}</code>\n"
            f"   • Reason: <code>{REMITLY_REASON}</code>\n"
            f"   • Amount: <code>₹{plan_price}</code>\n"
            f"5️⃣ Complete the payment process\n"
            f"6️⃣ 📸 Send the screenshot of your payment confirmation here\n\n"
            f"ℹ️ Our team will verify your payment and activate your subscription."
        )

        await query.message.answer(instructions, parse_mode=ParseMode.HTML)
        await state.set_state(PaymentState.WAITING_FOR_RECEIPT)

    async def _handle_local_payment(self, query: CallbackQuery, state: FSMContext):
        """Handle local (Indian) UPI payment with different VPAs based on amount"""
        subscription_id = int(query.data.split("_")[3])
        data = await state.get_data()
        payment_id = data.get("payment_id")
        plan_price = data.get("plan_price")

        vpa = os.getenv("LOW_AMT_VPA") if plan_price <= 1000 else os.getenv("HIGH_AMT_VPA")
        if not vpa:
            await query.message.answer("Payment configuration error. Please contact support.")
            return

        await self.api_client.request("PUT", f"/payments/{payment_id}", {
            "subscription_id": subscription_id,
            "amount": plan_price,
            "receipt_url": "pending_upload",
            "is_international": False
        })

        qr_data = f"upi://pay?pa={vpa}"
        qr_buffer = self.utils.generate_qr_code(qr_data)
        qr_bytes = qr_buffer.getvalue()
        qr_image = BufferedInputFile(qr_bytes, filename="qr_code.png")

        if plan_price == 5000:
            await query.message.answer_photo(
                photo=qr_image,
                caption=f"💳 Please send ₹{plan_price} to VPA <code>{vpa}</code> by paying it in three parts (₹2000, ₹2000 and ₹1000)\n"
                "📸 After payment, send the receipt screenshot here.\n",
                parse_mode=ParseMode.HTML
            )
        else:
            await query.message.answer_photo(
                photo=qr_image,
                caption=f"💳 Please send ₹{plan_price} to VPA: <code>{vpa}</code>\n"
                        "📸 After payment, send the receipt screenshot here.",
                parse_mode=ParseMode.HTML
            )

        await state.set_state(PaymentState.WAITING_FOR_RECEIPT)

    # Handle One Off Special Plan differently
    async def _handle_special_plan_payment(self, query: CallbackQuery, user_id: int, plan_name: str):
        try:
            # Send a message to the user with instructions to contact staff
            staff_contact_link = f"@{STAFF_USERNAME}"  # Replace with actual staff contact handle

            user_instructions = (
                f"✅ Your payment for {plan_name} has been verified!\n\n"
                f"For this special offer, please contact our staff directly at {staff_contact_link} "
                f"to receive your benefits. Mention that you've purchased the '{plan_name}' plan."
            )

            await query.bot.send_message(chat_id=user_id, text=user_instructions)

            # Notify staff about this special plan purchase
            if STAFF_CHAT_ID:
                staff_notification = (
                    f"🔔 SPECIAL PLAN PURCHASE ALERT 🔔\n\n"
                    f"User @{query.from_user.username or user_id} has purchased the '{plan_name}' plan.\n"
                    f"Please expect them to contact you for further assistance.\n\n"
                    f"User ID: {user_id}"
                )

                await query.bot.send_message(chat_id=STAFF_CHAT_ID, text=staff_notification)

            logger.info(f"Special plan '{plan_name}' purchase handled for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to handle special plan for user {user_id}: {e}")
            return False

    async def _handle_view_subscriptions(self, query: CallbackQuery):
        user_id = query.from_user.id
        subscriptions = await self.api_client.request("GET", f"/subscriptions/telegram/{user_id}")
        if subscriptions:
            response = "\n".join([f"{sub['plan']} ({sub['status']})" for sub in subscriptions])
            await query.message.answer(f"Your subscriptions:\n{response}")
        else:
            await query.message.answer("You have no active subscriptions.")

    # Helper methods for payment handling
    async def _handle_payment_details(self, query: CallbackQuery):
        payment_id = int(query.data.split("_")[1])
        payment = await self.api_client.request("GET", f"/payments/{payment_id}")

        if not payment:
            await query.message.answer("Payment not found")
            return

        receipt_url = payment.get("receipt_url")
        if receipt_url and receipt_url.startswith(f"{API_BASE_URL}/receipts/"):
            file_name = receipt_url.split("/")[-1]
            file_path = os.path.join("receipts", file_name)

            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    receipt_bytes = f.read()

                payment_type = "🌍 International" if payment.get("is_international") else "🇮🇳 Local"

                await query.message.answer_photo(
                    photo=BufferedInputFile(receipt_bytes, filename=file_name),
                    caption=f"Payment Details:\nAmount: ₹{payment['amount']}\nType: {payment_type}\nSubscription ID: {payment['subscription_id']}"
                )
            else:
                await query.message.answer("Receipt image not found on the server.")
        else:
            await query.message.answer("Invalid receipt URL.")

        action_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Verify", callback_data=f"verify_{payment_id}")],
            [InlineKeyboardButton(text="Reject", callback_data=f"reject_{payment_id}")],
            [InlineKeyboardButton(text="← Back", callback_data="staff_payments")]
        ])

        payment_type = "🌍 International" if payment.get("is_international") else "🇮🇳 Local"
        await query.message.answer(
            f"Payment ID: {payment['id']}\nStatus: {payment['status']}\nType: {payment_type}",
            reply_markup=action_keyboard
        )

    async def _handle_verify_payment(self, query: CallbackQuery):
        payment_id = int(query.data.split("_")[1])
        payment = await self.api_client.request("GET", f"/payments/{payment_id}")

        # Check if the payment is already verified or rejected
        if payment and payment.get("status") not in ["pending", "pending_verification"]:
            await query.message.answer("⚠️ This payment has already been processed and cannot be verified again.")
            return

        # Verify the payment
        await self.api_client.request("PUT", f"/payments/{payment_id}/verify")
        await query.message.answer("✅ Payment verified!")

        # Notify user about verified payment
        user_to_notify = None
        subscription_plan = None
        telegram_channel_id = None
        if payment and "subscription_id" in payment:
            subscription = await self.api_client.request("GET", f"/subscriptions/{payment['subscription_id']}")
            if subscription:
                # Check for user_id instead of telegram_user_id
                if "user_id" in subscription:
                    # Get the telegram_user_id from the user record
                    user = await self.api_client.request("GET", f"/users/{subscription['user_id']}")
                    if user and "user_id" in user:
                        user_to_notify = user.get("user_id")

                # Get the plan details to retrieve the Telegram channel ID
                plans = await self.menu_handlers.get_plans()
                subscription_plan_index = subscription.get("plan_id") - 1
                subscription_plan = plans[subscription_plan_index]["name"]
                telegram_channel_id = plans[subscription_plan_index].get("telegram_channel_id")

                # Check if this is a special plan that needs special handling
                is_special_plan = plans[subscription_plan_index].get("name").startswith("Special")

                # If this is a special plan, handle it differently
                if is_special_plan and user_to_notify:
                    success = await self._handle_special_plan_payment(
                        query,
                        user_to_notify,
                        subscription_plan
                    )
                    if success:
                        # If special plan was handled successfully, we can skip the regular notification flow
                        await self.menu_handlers.show_staff_payments(query.message)
                        return
                    # If special plan handling failed, continue with normal flow as fallback

                logger.info(f"Will notify user {user_to_notify} about payment verification")
            else:
                logger.error(f"Subscription {payment['subscription_id']} not found")

        # Regular notification flow for normal plans
        if user_to_notify:
            try:
                verification_message = (
                    f"✅ Your payment for {subscription_plan} subscription has been verified! "
                    "Your subscription is now active."
                )
                await query.bot.send_message(chat_id=user_to_notify, text=verification_message)
                logger.info(f"Successfully sent verification notification to user {user_to_notify}")

                # Add user to the Telegram channel for the subscription plan
                if telegram_channel_id:
                    success, message = await self.add_to_channel(query.bot, user_to_notify, telegram_channel_id)
                    if not success:
                        logger.error(f"Failed to invite user {user_to_notify} to channel {telegram_channel_id}: {message}")
                else:
                    logger.warning(f"No Telegram channel ID found for plan: {subscription_plan}")
            except Exception as e:
                logger.error(f"Failed to notify user about verified payment: {e}")
        else:
            logger.warning(f"No user to notify for verified payment {payment_id}")

        await self.menu_handlers.show_staff_payments(query.message)

    async def _handle_reject_payment(self, query: CallbackQuery, bot: Bot):
        payment_id = int(query.data.split("_")[1])
        payment = await self.api_client.request("GET", f"/payments/{payment_id}")

        # Check if the payment is already verified or rejected
        if payment and payment.get("status") not in ["pending", "pending_verification"]:
            await query.message.answer("⚠️ This payment has already been processed and cannot be rejected again.")
            return

        # Get user info before rejecting the payment
        user_to_notify = None
        subscription_plan = None
        if payment and "subscription_id" in payment:
            subscription = await self.api_client.request("GET", f"/subscriptions/{payment['subscription_id']}")
            if subscription:
                # Check for user_id instead of telegram_user_id
                if "user_id" in subscription:
                    # Get the telegram_user_id from the user record
                    user = await self.api_client.request("GET", f"/users/{subscription['user_id']}")
                    if user and "user_id" in user:
                        user_to_notify = user.get("user_id")

                plans = await self.menu_handlers.get_plans()
                subscription_plan_index = subscription.get("plan_id") - 1
                subscription_plan = plans[subscription_plan_index]["name"]
                logger.info(f"Will notify user {user_to_notify} about payment rejection")
            else:
                logger.error(f"Subscription {payment['subscription_id']} not found")

        # Reject the payment
        await self.api_client.request("PUT", f"/payments/{payment_id}/reject")
        await query.message.answer("❌ Payment rejected!")

        # Notify user about rejected payment
        if user_to_notify:
            try:
                rejection_message = (
                    f"❌ Your payment for {subscription_plan} subscription has been rejected. "
                    "Please contact support or try making the payment again."
                )
                await bot.send_message(chat_id=user_to_notify, text=rejection_message)
                logger.info(f"Successfully sent rejection notification to user {user_to_notify}")
            except Exception as e:
                logger.error(f"Failed to notify user about rejected payment: {e}")
        else:
            logger.warning(f"No user to notify for rejected payment {payment_id}")

        await self.menu_handlers.show_staff_payments(query.message)

    async def add_to_channel(self, bot: Bot, user_id: int, channel_id: str):
        """Invite a user to a Telegram channel with error handling"""
        try:
            # Format the channel ID correctly if needed
            formatted_channel_id = channel_id
            if not channel_id.startswith("-100") and channel_id.isdigit():
                formatted_channel_id = f"-100{channel_id}"

            # Try to get chat info first to validate the channel
            try:
                chat = await bot.get_chat(chat_id=formatted_channel_id)
                logger.info(f"Successfully found channel: {chat.title}")
            except Exception as e:
                logger.error(f"Channel validation failed: {str(e)}")
                # Try alternative format if the first one fails
                if formatted_channel_id.startswith("-100"):
                    formatted_channel_id = channel_id
                else:
                    formatted_channel_id = f"-100{channel_id}"
                chat = await bot.get_chat(chat_id=formatted_channel_id)

            # Generate an invite link for the channel
            invite_link = await bot.create_chat_invite_link(
                chat_id=formatted_channel_id,
                member_limit=1,
                expire_date=int(time.time() + 86400)  # Valid for 24 hours
            )

            # Send the invite link to the user
            await bot.send_message(
                chat_id=user_id,
                text=f"You've been invited to our channel. This invite link will remain valid only for 24 hours. Only one person will be able to join using this link. Join here: {invite_link.invite_link}"
            )
            return True, "Invite sent successfully"
        except Exception as e:
            logger.error(f"Failed to invite user {user_id} to channel {channel_id}: {e}")
            return False, str(e)

    # Helper methods for ticket handling
    async def _handle_reply_ticket(self, query: CallbackQuery, state: FSMContext):
        ticket_id = int(query.data.split("_")[2])
        await state.update_data(current_ticket_id=ticket_id)
        await query.message.answer("Please enter your reply:")
        await state.set_state(TicketReplyState.AWAITING_REPLY_TEXT)

    async def _handle_resolve_ticket(self, query: CallbackQuery):
        ticket_id = int(query.data.split("_")[2])
        ticket = await self.api_client.request("GET", f"/support/tickets/{ticket_id}")
        update_data = {"resolved": not ticket['resolved']}
        await self.api_client.request("PUT", f"/support/tickets/{ticket_id}", update_data)
        await query.message.answer(f"Ticket {'resolved' if update_data['resolved'] else 'reopened'}!")

        # Notify user about ticket status change
        if ticket and "telegram_user_id" in ticket:
            try:
                bot = query.bot
                status_message = (
                    f"Your support ticket #{ticket_id} has been "
                    f"{'resolved' if update_data['resolved'] else 'reopened'}."
                )
                await bot.send_message(chat_id=ticket["telegram_user_id"], text=status_message)
            except Exception as e:
                logger.error(f"Failed to notify user about ticket status change: {e}")

        await self.menu_handlers.show_staff_tickets(query.message)

    # Helper methods for staff subscription handling
    async def _handle_staff_subscriptions(self, query: CallbackQuery):
        subscriptions = await self.api_client.request("GET", "/subscriptions/")
        if not subscriptions:
            await query.message.answer("No active subscriptions.")
            return

        subscription_list = "\n".join(
            [f"ID: {s['id']} | User ID: {s['telegram_user_id']} | Plan: {s['plan']} | Status: {s['status']}"
            for s in subscriptions]
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔄 Refresh", callback_data="staff_subscriptions"),
            InlineKeyboardButton(text="← Back", callback_data="staff_menu")
        ]])

        await query.message.answer(f"📋 Active Subscriptions:\n{subscription_list}", reply_markup=keyboard)

# State handlers
class StateHandlers:
    def __init__(self, api_client, utils, storage, bot):
        self.api_client = api_client
        self.utils = utils
        self.storage = storage  # Add storage attribute
        self.bot = bot  # Store the bot instance

    async def handle_payment_receipt(self, message: Message, state: FSMContext, bot: Bot):
        if not message.photo:
            await message.answer("Please send the payment receipt screenshot.")
            return

        # Check file size
        file_id = message.photo[-1].file_id
        try:
            file = await bot.get_file(file_id)
            if file.file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                await message.answer(f"File too large. Maximum size is {MAX_FILE_SIZE_MB}MB.")
                return

            # Construct the file URL
            file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"

            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as response:
                    if response.status == 200:
                        file_data = await response.read()
                        file_name = f"receipt_{message.from_user.id}_{int(time.time())}.png"
                        receipt_url = await self.utils.save_file_locally(file_data, file_name)

                        user_data = await state.get_data()
                        payment = await self.api_client.request("GET", f"/payments/{user_data['payment_id']}")
                        payment_data = {
                            "subscription_id": user_data["subscription_id"],
                            "amount": user_data["plan_price"],
                            "receipt_url": receipt_url,
                            "is_international": payment["is_international"]
                        }

                        await self.api_client.request("PUT", f"/payments/{user_data['payment_id']}", payment_data)
                        await message.answer(
                            "✅ Payment receipt received! Our team will verify your payment shortly.\n"
                            "You'll be notified once your subscription is activated."
                        )
                        await state.clear()

                        if STAFF_CHAT_ID:
                            try:
                                with open(os.path.join("receipts", file_name), "rb") as f:
                                    receipt_bytes = f.read()

                                await bot.send_photo(
                                    chat_id=STAFF_CHAT_ID,
                                    photo=BufferedInputFile(receipt_bytes, filename=file_name),
                                    caption=f"Payment receipt for subscription {user_data['subscription_id']}"
                                )
                            except Exception as e:
                                logger.error(f"Failed to notify staff: {e}")
                    else:
                        await message.answer("Failed to download the receipt. Please try again.")
        except Exception as e:
            logger.error(f"File size check failed: {e}")
            await message.answer("Error processing file. Please try again.")
            return

    async def handle_support_ticket_issue(self, message: Message, state: FSMContext):
        if message.photo:
            await message.answer("Please describe your issue before uploading images.")
            return
        await state.update_data(issue_description=message.text, attachments=[])
        await message.answer("Thank you for describing your issue. You can now send additional messages or images if needed. When you're done, type /done.")
        await state.set_state(SupportTicketState.COLLECTING_ADDITIONAL_INFO)

    async def handle_additional_info(self, message: Message, state: FSMContext, bot: Bot):
        current_state = await state.get_state()
        if not current_state:
            await message.answer("Your ticket has already been submitted. Use /start to create a new ticket.")
            return

        data = await state.get_data()
        attachments = data.get("attachments", [])

        if message.text:
            if message.text.lower() == "/done":
                user_id = message.from_user.id

                # First check if user is staff
                is_staff = await self.api_client.request("GET", f"/staff/check/{user_id}")
                if is_staff and is_staff.get("is_staff", False):
                    # Skip rate limiting for staff members
                    proceed_with_ticket = True
                else:
                    # Apply rate limiting only for non-staff users
                    rate_limit_key = f"ticket_rate_limit:{user_id}"
                    redis = self.storage.redis
                    ticket_count = await redis.get(rate_limit_key)

                    if ticket_count:
                        ticket_count = int(ticket_count)
                        proceed_with_ticket = ticket_count < 3  # Max 3 tickets per hour for non-staff
                    else:
                        proceed_with_ticket = True
                        ticket_count = 0

                    if proceed_with_ticket:
                        await redis.set(rate_limit_key, ticket_count + 1, ex=3600)  # 1 hour expiration

                if not proceed_with_ticket:
                    await message.answer("🚫 You have raised too many support tickets recently. Please wait before raising another one.")
                    return

                # Proceed with ticket creation
                issue_description = data.get("issue_description", "")
                ticket_data = {
                    "telegram_user_id": user_id,
                    "issue": issue_description,
                    "attachments": attachments
                }

                response = await self.api_client.request("POST", "/support/tickets/", ticket_data)

                if response and "error" not in response:
                    await message.answer("📨 Your support ticket has been created. We'll get back to you soon! ⏳")
                    await state.clear()

                    # Staff notification logic
                    if STAFF_CHAT_ID:
                        try:
                            ticket_id = response.get("id")
                            ticket_message = (
                                f"🚨 New Support Ticket 🚨\n\n"
                                f"Ticket ID: #{ticket_id}\n"
                                f"User ID: {user_id}\n"
                                f"Issue: {issue_description}\n\n"
                                f"Please respond promptly."
                            )
                            await message.bot.send_message(chat_id=STAFF_CHAT_ID, text=ticket_message)

                            # Handle attachments
                            for attachment in attachments:
                                if attachment["type"] == "photo":
                                    await self._send_attachment_to_staff(
                                        bot,
                                        attachment["file_id"],
                                        ticket_id,
                                        STAFF_CHAT_ID
                                    )
                        except Exception as e:
                            logger.error(f"Failed to notify staff about new ticket: {e}")
                else:
                    await message.answer("Failed to create the support ticket. Please try again later.")

            else:
                # Handle additional text messages
                issue_description = data.get("issue_description", "") + "\n" + message.text
                await state.update_data(issue_description=issue_description)
                await message.answer("Additional message received. You can send more or type /done when finished.")

        elif message.photo:
            # Handle photo attachments
            photo_file_id = message.photo[-1].file_id
            try:
                file = await bot.get_file(photo_file_id)
                if file.file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                    await message.answer(f"File too large. Maximum size is {MAX_FILE_SIZE_MB}MB.")
                    return

                attachments.append({"type": "photo", "file_id": photo_file_id})
                await state.update_data(attachments=attachments)
                await message.answer("Image received. You can send more or type /done when finished.")
            except Exception as e:
                logger.error(f"Error checking file: {e}")
                await message.answer("Error processing image. Please try again.")

        else:
            await message.answer("Unsupported file type. Please send text or images.")

    async def _send_attachment_to_staff(self, bot, file_id, ticket_id, staff_chat_id):
        """Helper method to send attachments to staff chat"""
        try:
            file = await bot.get_file(file_id)
            file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"

            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as response:
                    if response.status == 200:
                        file_data = await response.read()
                        await bot.send_photo(
                            chat_id=staff_chat_id,
                            photo=BufferedInputFile(file_data, filename=f"ticket_attachment_{ticket_id}.jpg"),
                            caption=f"Image attachment for Ticket ID: #{ticket_id}"
                        )
        except Exception as e:
            logger.error(f"Failed to send ticket image to staff: {e}")

    async def handle_ticket_reply(self, message: Message, state: FSMContext):
        data = await state.get_data()
        ticket_id = data['current_ticket_id']

        # Get ticket information
        ticket = await self.api_client.request("GET", f"/support/tickets/{ticket_id}")

        reply_data = {
            "ticket_id": ticket_id,
            "reply": message.text,
            "replied_by": message.from_user.id
        }

        await self.api_client.request("POST", f"/staff/tickets/{ticket_id}/reply", reply_data)
        await message.answer("Reply added successfully!")

        # Notify user about the reply
        if ticket and "user_id" in ticket:
            user = await self.api_client.request("GET", f"/users/{ticket['user_id']}")
            if user and "user_id" in user:
                user_to_notify = user.get("user_id")
            try:
                notification_message = (
                    f"🔔 You have received a reply to your support ticket #{ticket_id}:\n\n"
                    f"{message.text}\n\n"
                    f"You can continue the conversation through the support system."
                )
                await self.bot.send_message(chat_id=user_to_notify, text=notification_message)
            except Exception as e:
                logger.error(f"Failed to notify user about ticket reply: {e}")

        await state.clear()

# Enhanced TelegramBot class with middleware
class TelegramBot:
    def __init__(self):
        self._validate_env_vars()
        self.storage = RedisStorage.from_url(REDIS_URL)
        self.dp = Dispatcher(storage=self.storage)

        # Setup API client and utilities
        self.api_client = APIClient(API_KEY, API_BASE_URL)
        self.utils = Utils()

        # Setup handlers
        self.menu_handlers = MenuHandlers(self.api_client)
        self.staff_service = StaffService(self.api_client)
        self.command_handlers = CommandHandlers(self.api_client, self.menu_handlers, self.staff_service)
        self.callback_handlers = CallbackHandlers(self.api_client, self.menu_handlers, self.utils)

        # Initialize the bot
        self.bot = Bot(token=TOKEN)

        # Pass the bot instance to StateHandlers
        self.state_handlers = StateHandlers(self.api_client, self.utils, self.storage, self.bot)

        # Add middleware with staff_service
        self.dp.update.middleware(RateLimitingMiddleware(self.storage, self.staff_service))

        # Register handlers
        self._register_handlers()

    def _validate_env_vars(self):
        required_env_vars = ["BOT_TOKEN", "API_KEY", "REDIS_URL"]
        missing_vars = [var for var in required_env_vars if os.getenv(var) is None]
        if missing_vars:
            logger.critical(f"Missing required environment variables: {', '.join(missing_vars)}")
            raise ValueError("Missing required environment variables")

        if not STAFF_CHAT_ID:
            logger.warning("STAFF_CHAT_ID not set - staff notifications will be disabled")

    def _register_handlers(self):
        # Command handlers
        self.dp.message.register(self.command_handlers.start_command, Command("start"))
        self.dp.message.register(self.command_handlers.staff_command, Command("staff"))

        # Callback query handler
        self.dp.callback_query.register(self.callback_handlers.handle_callback)

        # State handlers
        self.dp.message.register(
            self.state_handlers.handle_payment_receipt,
            PaymentState.WAITING_FOR_RECEIPT
        )
        self.dp.message.register(
            self.state_handlers.handle_support_ticket_issue,
            SupportTicketState.WAITING_FOR_ISSUE
        )
        self.dp.message.register(
            self.state_handlers.handle_additional_info,
            SupportTicketState.COLLECTING_ADDITIONAL_INFO
        )

        # Use the correct handler for ticket replies
        self.dp.message.register(
            self.state_handlers.handle_ticket_reply,
            TicketReplyState.AWAITING_REPLY_TEXT
        )

    async def set_bot_commands(self, bot: Bot):
        commands = [
            BotCommand(command="start", description="Main Menu"),
            BotCommand(command="staff", description="Staff Dashboard (Staff Only)"),
        ]
        await bot.set_my_commands(commands)

    async def start(self):
        bot = Bot(token=TOKEN)
        await self.set_bot_commands(bot)
        await self.dp.start_polling(bot)

# Enhanced main function with error handling
async def main():
    try:
        bot = TelegramBot()
        await bot.start()
    except TokenValidationError:
        logger.critical("Invalid Telegram bot token")
    except ConnectionError as e:
        logger.critical(f"Redis connection failed: {e}")
    except Exception as e:
        logger.critical(f"Fatal initialization error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
