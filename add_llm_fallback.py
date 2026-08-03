"""Script to add LLM fallback in classification flow"""

# Read the current file
with open('app/services/admin_ai_assistant.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if already added
if '# LLM fallback for low-confidence' in content:
    print('LLM fallback already exists!')
    exit(0)

old_text = '''            # If intent is GENERAL with low confidence, try to infer from context
            if intent == AdminIntent.GENERAL and confidence < 0.5:
                # Check if this looks like a follow-up (short message, has date/entities from context)
                if len(message.split()) <= 5 and context_entities:
                    # Check if there's a date reference - might be asking about bookings on that date
                    if "target_date" in entities or "date" in entities:
                        intent = AdminIntent.QUERY_BOOKINGS
                        confidence = 0.7
                        logger.info(f"Inferred intent QUERY_BOOKINGS from context with date {entities.get('target_date', entities.get('date'))}")

            # Process based on intent'''

new_text = '''            # If intent is GENERAL with low confidence, try to infer from context
            if intent == AdminIntent.GENERAL and confidence < 0.5:
                # Check if this looks like a follow-up (short message, has date/entities from context)
                if len(message.split()) <= 5 and context_entities:
                    # Check if there's a date reference - might be asking about bookings on that date
                    if "target_date" in entities or "date" in entities:
                        intent = AdminIntent.QUERY_BOOKINGS
                        confidence = 0.7
                        logger.info(f"Inferred intent QUERY_BOOKINGS from context with date {entities.get('target_date', entities.get('date'))}")

            # LLM fallback for low-confidence classifications
            if intent == AdminIntent.GENERAL and confidence < 0.6 and self.llm:
                try:
                    llm_intent, llm_confidence = await self._classify_with_llm(message, entities, context)
                    if llm_confidence > confidence:
                        logger.info(f"LLM improved classification: {intent.value}({confidence:.2f}) -> {llm_intent.value}({llm_confidence:.2f})")
                        intent, confidence = llm_intent, llm_confidence
                except Exception as e:
                    logger.warning(f"LLM classification failed, using regex result: {e}")

            # Process based on intent'''

if old_text not in content:
    print('ERROR: Pattern not found!')
    exit(1)

new_content = content.replace(old_text, new_text)

with open('app/services/admin_ai_assistant.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('SUCCESS: LLM fallback added!')
