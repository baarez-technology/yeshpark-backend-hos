"""Script to add LLM-based intent classification to admin_ai_assistant.py"""

# Read the current file
with open('app/services/admin_ai_assistant.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if already added
if 'async def _classify_with_llm' in content:
    print('LLM classifier already exists!')
    exit(0)

# Find the insertion point - after _generate_natural_response method
old_marker = '''        except Exception as e:
            logger.error(f"Error generating natural response: {e}")
            return default_message

    def _build_context_message(self, context: Optional[Dict], message: str) -> str:'''

new_code = '''        except Exception as e:
            logger.error(f"Error generating natural response: {e}")
            return default_message

    async def _classify_with_llm(
        self,
        message: str,
        entities: Dict,
        context: Optional[Dict] = None
    ) -> Tuple[AdminIntent, float]:
        """
        Use LLM for advanced intent classification when regex patterns have low confidence.
        Returns (intent, confidence) tuple.
        """
        if not self.llm:
            return AdminIntent.GENERAL, 0.3

        try:
            # Build intent descriptions
            intent_descriptions = """
Available intents:
- query_bookings: Questions about bookings, reservations, occupancy, arrivals, departures
- query_guests: Questions about guests, guest counts, guest information
- query_rooms: Questions about rooms, room status, availability, housekeeping status
- query_revenue: Questions about revenue, income, financial metrics
- query_staff: Questions about staff, employees, schedules
- create_booking: Creating a new reservation/booking
- update_booking: Modifying an existing booking
- cancel_booking: Cancelling a reservation
- check_in: Checking in a guest
- check_out: Checking out a guest
- assign_room: Assigning a specific room to a booking (e.g., "assign room 501 to booking 1")
- transfer_room: Moving a guest from one room to another (e.g., "transfer guest from 501 to 502")
- create_guest_note: Adding a note to a guest profile (e.g., "add note to guest 15: VIP")
- assign_task: Assigning housekeeping or maintenance tasks
- update_room: Changing room status (clean, dirty, maintenance, etc.)
- send_email: Sending emails to guests
- send_notification: Sending notifications
- report: Generating reports or analytics
- hotel_info: Questions about hotel facilities, policies, general information
- greeting: Hello, hi, good morning type messages
- confirm_action: Confirming a pending action (yes, confirm, proceed)
- cancel_action: Cancelling a pending action (no, cancel, nevermind)
- follow_up: Follow-up questions referencing previous context (show more, what about, etc.)
- general: General questions or unclear intent
"""

            # Build context summary
            context_info = ""
            if context and "previousMessages" in context:
                prev = context.get("previousMessages", [])[-3:]
                if prev:
                    context_info = "Recent conversation:\\n"
                    for msg in prev:
                        context_info += f"- {msg.get('role', 'user')}: {msg.get('content', '')[:100]}\\n"

            entity_info = ""
            if entities:
                entity_info = f"Extracted entities: {json.dumps(entities, default=str)}"

            prompt = f"""Classify the following hotel admin message into one intent.

{intent_descriptions}

{context_info}
{entity_info}

Message: "{message}"

Reply with ONLY a JSON object in this format:
{{"intent": "<intent_name>", "confidence": <0.0-1.0>}}

Example: {{"intent": "assign_room", "confidence": 0.95}}"""

            messages = [
                SystemMessage(content="You are an intent classifier for a hotel admin AI. Return ONLY valid JSON."),
                HumanMessage(content=prompt)
            ]

            response = self.llm.invoke(messages)
            result_text = response.content.strip()

            # Parse JSON response
            import re as regex
            json_match = regex.search(r'\\{[^}]+\\}', result_text)
            if json_match:
                result = json.loads(json_match.group())
                intent_str = result.get("intent", "general")
                confidence = float(result.get("confidence", 0.5))

                # Map string to AdminIntent enum
                intent_map = {v.value: v for v in AdminIntent}
                intent = intent_map.get(intent_str, AdminIntent.GENERAL)

                logger.info(f"LLM classified '{message[:50]}...' as {intent.value} ({confidence:.2f})")
                return intent, confidence
            else:
                logger.warning(f"Could not parse LLM response: {result_text[:100]}")
                return AdminIntent.GENERAL, 0.3

        except Exception as e:
            logger.error(f"LLM classification error: {e}")
            return AdminIntent.GENERAL, 0.3

    def _build_context_message(self, context: Optional[Dict], message: str) -> str:'''

if old_marker not in content:
    print('ERROR: Marker pattern not found!')
    exit(1)

new_content = content.replace(old_marker, new_code)

with open('app/services/admin_ai_assistant.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('SUCCESS: LLM classifier method added!')
