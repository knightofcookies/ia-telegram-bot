The application will consist of a Telegram bot to serve customers, a backend application to manage the business logic and a frontend application (a web application or an Android application) to provide an interface to the staff.

# Telegram Bot
The Telegram bot will be responsible for handling customer interactions and providing a seamless experience.

The user should have the following options when interacting with the bot:

1. Purchase a subscription
2. View existing subscriptions
3. Raise a support ticket

Each of these options will be implemented using the following steps:

1. Purchase a subscription:
   - The user will be prompted to select a subscription plan (the plan names and their details should be listed).
   - The user will be asked to confirm their selection.
   - The user will be provided with a QR code and a VPA address to pay for the subscription.
   - The user will be prompted to provide the screenshot of the payment receipt.
   - The subscription will be processed after manual verification by the staff and the user will receive a confirmation message.
   - The user will be informed about the status of their subscription and any pending actions.

2. View existing subscriptions:
   - The user will be shown a list of their active subscriptions.
   - The user will be able to view details about each subscription, including the purchase date and time, expiration date and time, and transaction details.

3. Raise a support ticket:
   - The user will be prompted to describe their issue.
   - The user will be asked to provide additional information if needed.
   - The support ticket will be created and the user will receive a confirmation message.

# Backend Application
The backend application will be responsible for managing the business logic.

# Frontend Application
The frontend application will be responsible for providing an interface to the staff to manage the business logic.

The staff should be able to view and manage the subscriptions, including creating, updating, and deleting subscriptions.

The staff should be able to view and manage the support tickets, including responding to tickets and closing them.

The staff should be able to view and manage the user data, including viewing user details, updating user information, and deleting user accounts.

The staff should be able to view and manage the payment transactions, including viewing transaction details, updating transaction status, and deleting transactions. The staff should be shown a list of transactions pending verification (and those completed).

The staff should be able to mark transactions as verified or invalid. These actions should be able to be undone. All such actions should be logged for auditing purposes.
