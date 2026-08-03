"""Script to fix intent classification in admin_ai_assistant.py"""

# Read the current file
with open('app/services/admin_ai_assistant.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if already fixed
if 'action_intents = {' in content:
    print('Already fixed!')
    exit(0)

old_text = '''            # Classify intent - first check raw message for follow-up patterns
            raw_intent, raw_confidence = self.intent_classifier.classify(message)

            # If raw message is a follow-up (like "yes", "show me more", etc.), use that
            if raw_intent == AdminIntent.FOLLOW_UP:
                intent, confidence = raw_intent, raw_confidence
            else:
                # Otherwise use context-enhanced message for better classification
                context_message = self._build_context_message(context, message)
                intent, confidence = self.intent_classifier.classify(context_message)'''

new_text = '''            # Classify intent - first check raw message
            raw_intent, raw_confidence = self.intent_classifier.classify(message)
            logger.debug(f"Raw classification: {raw_intent.value} with confidence {raw_confidence}")

            # Action intents that should NOT be overridden by context-enhanced classification
            action_intents = {
                AdminIntent.ASSIGN_ROOM, AdminIntent.TRANSFER_ROOM, AdminIntent.CREATE_GUEST_NOTE,
                AdminIntent.CREATE_BOOKING, AdminIntent.UPDATE_BOOKING, AdminIntent.CANCEL_BOOKING,
                AdminIntent.ASSIGN_TASK, AdminIntent.UPDATE_ROOM, AdminIntent.SEND_EMAIL,
                AdminIntent.SEND_NOTIFICATION, AdminIntent.FOLLOW_UP, AdminIntent.CONFIRM_ACTION,
                AdminIntent.CANCEL_ACTION, AdminIntent.CHECK_IN, AdminIntent.CHECK_OUT,
            }

            # Use raw classification directly for action intents with sufficient confidence
            if raw_intent in action_intents and raw_confidence >= 0.6:
                intent, confidence = raw_intent, raw_confidence
                logger.debug(f"Using raw action intent: {intent.value}")
            elif raw_intent == AdminIntent.FOLLOW_UP:
                intent, confidence = raw_intent, raw_confidence
            elif raw_confidence >= 0.8:
                # High confidence - use raw classification
                intent, confidence = raw_intent, raw_confidence
            else:
                # Low confidence - try context-enhanced classification for query intents
                context_message = self._build_context_message(context, message)
                intent, confidence = self.intent_classifier.classify(context_message)

                # If context made it worse, revert to raw
                if intent == AdminIntent.GENERAL and raw_intent != AdminIntent.GENERAL:
                    intent, confidence = raw_intent, raw_confidence
                    logger.debug(f"Reverted to raw classification after context made it worse")'''

if old_text not in content:
    print('ERROR: Pattern not found!')
    print('Searching for variations...')
    # Try to find the classify section
    import re
    match = re.search(r'# Classify intent.*?self\.intent_classifier\.classify\(context_message\)', content, re.DOTALL)
    if match:
        print(f'Found at position {match.start()}-{match.end()}')
        print(f'Content: {match.group()[:200]}...')
    exit(1)

new_content = content.replace(old_text, new_text)

with open('app/services/admin_ai_assistant.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('SUCCESS: Classification logic fixed!')
