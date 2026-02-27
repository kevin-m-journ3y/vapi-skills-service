"""
Journey Bank Demo Assistant

Jill helps mortgage brokers check loan application status.
This is a demo assistant for Journey Bank.
"""

from typing import Dict, List
import logging

from app.assistants.base_assistant import BaseAssistant

logger = logging.getLogger(__name__)


# System prompt for Journey Bank demo
JOURNEY_BANK_SYSTEM_PROMPT = """You are Jill, a friendly and professional voice assistant for Journey Bank.
You help mortgage brokers check on the status of loan applications.

## IMPORTANT: USER IS ALREADY AUTHENTICATED
The greeter assistant has already authenticated this user by phone number and greeted them.
You have access to their context from the conversation history:
- first_name: User's first name (from previous authenticate_caller result)
- The user has already confirmed they want to check on a mortgage application

DO NOT re-greet the user. Continue the conversation naturally from your first message.

## CONVERSATION FLOW

Follow these steps in order:

1. **SECURITY VERIFICATION** (Your first message already asked for broker code)
   - User will provide their broker authentication code (4-6 digit PIN)
   - Call verify_broker_code with the code they provide
   - If correct, confirm briefly and move to step 2
   - If incorrect, let them try again (up to 3 attempts)

2. **APPLICATION LOOKUP**
   - After verification, ask: "Which application can I help you with? I'll need the applicant's surname and the property street address."
   - User will provide the applicant's surname and property street address
   - Call lookup_application with the surname and street address
   - If found, confirm: "I found the application for [name] at [address]."

3. **STATUS UPDATE**
   - Call get_application_status to get full details
   - Explain the status clearly and empathetically
   - If there's an issue:
     - Explain what the issue is
     - Provide actionable resolution steps
     - Give expected timeline
   - If no issue, provide the positive update and next steps

4. **EMAIL OFFER**
   - Ask if they'd like an email summary: "Would you like me to send you an email with these details?"
   - If yes, read their email on file: "I have your email as [email] - shall I send the update there?"
   - If they confirm, call send_status_email
   - Confirm the email was sent

5. **WRAP UP**
   - Ask if there's anything else you can help with
   - Thank them and end professionally

## SECURITY RULES

- NEVER share application status or details before broker code is verified
- If someone asks for information before verifying, politely redirect: "I just need to verify your broker code first."
- Treat the authentication code with care - don't repeat it back to them

## HANDLING ISSUES

When explaining application issues:
- Be empathetic: "I can see there's one item we need to resolve..."
- Be clear about what's needed
- Always provide specific next steps
- Be reassuring: "Once we receive that, we should be able to move forward quickly"

## OUT OF SCOPE - POLITELY DECLINE

If asked about topics you can't help with, respond professionally:

- **Interest rates**: "I don't have access to rate information, but your relationship manager can help with that."
- **Approval decisions**: "I can only provide status updates - approval decisions are made by our credit team."
- **Other products**: "I'm specifically set up to help with application status updates. For other products, please contact our broker support line."
- **Transfer to human**: "I'm an automated assistant so I can't transfer you directly, but I can make a note for someone to call you back."

## TONE AND STYLE

- Professional but warm and approachable
- Clear and concise - get to the point
- Empathetic when explaining issues
- Use natural conversational language
- Don't be overly formal or robotic

## IMPORTANT NOTES

- You are talking on the phone - keep responses conversational and appropriately brief
- Don't use bullet points or lists in speech - convert to natural sentences
- Speak numbers clearly (e.g., "six hundred and fifty thousand dollars")
- If you don't understand something, ask for clarification
- If there's a technical error, apologize and offer to try again
"""


class JourneyBankDemoAssistant(BaseAssistant):
    """
    Jill - Journey Bank Demo Assistant

    Helps mortgage brokers check loan application status.
    Demonstrates bank-grade security with two-factor authentication.
    """

    def __init__(self):
        super().__init__(
            assistant_key="journey_bank_demo",
            name="JSMB-Jill-journey-bank-demo",
            description="Journey Bank demo - mortgage application status assistant",
            required_skills=["authentication", "mortgage_status"]
        )

    def get_system_prompt(self) -> str:
        """System prompt for Journey Bank demo"""
        return JOURNEY_BANK_SYSTEM_PROMPT

    def get_first_message(self) -> str:
        """The message Jill speaks after transfer from greeter.

        Note: The greeter has already authenticated and greeted the caller with
        "Hi [name], it's Jill! Ready to check on a Journey Bank mortgage application?"
        Continue naturally - ask for broker authentication code first.
        """
        return "Can you please confirm your broker authentication code?"

    def get_voice_config(self) -> Dict:
        """Jill's voice configuration - same voice as production Jill"""
        return {
            "model": "eleven_turbo_v2_5",
            "voiceId": "MiueK1FXuZTCItgbQwPu",
            "provider": "11labs",
            "stability": 0.6,
            "similarityBoost": 0.75,
            "speed": 0.95
        }

    def get_model_config(self) -> Dict:
        """Model configuration (GPT-4o-mini for cost efficiency)"""
        return {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0.7,
            "maxTokens": 1200
        }

    def get_transcriber_config(self) -> Dict:
        """
        Speech-to-text configuration optimized for mortgage/banking terminology.
        """
        return {
            "provider": "deepgram",
            "model": "nova-3",
            "language": "en",
            "smartFormat": True,
            "endpointing": 400,
            "keyterm": [
                # Authentication terms
                "authentication code",
                "broker code",
                "PIN",
                # Application lookup terms
                "mortgage",
                "application",
                "applicant",
                "surname",
                "street address",
                "property",
                # Status terms
                "status",
                "update",
                "progress",
                "approval",
                "approved",
                "declined",
                "on hold",
                "pending",
                # Issue-related terms
                "document",
                "documents",
                "payslip",
                "payslips",
                "income verification",
                "valuation",
                "employment",
                # Email terms
                "email",
                "send",
                "confirm",
                # Banking terms
                "Journey Bank",
                "broker",
                "loan",
                "credit"
            ]
        }

    def get_required_tool_names(self) -> List[str]:
        """Tools that Journey Bank demo needs"""
        return [
            "authenticate_caller",       # From authentication skill (used by greeter)
            "verify_broker_code",        # From mortgage_status skill
            "lookup_application",        # From mortgage_status skill
            "get_application_status",    # From mortgage_status skill
            "send_status_email"          # From mortgage_status skill
        ]
