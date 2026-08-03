"""Script to add handler methods to admin_ai_assistant.py"""
import re

# Read the current file
with open('app/services/admin_ai_assistant.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if handler methods are already defined (not just the routing)
if 'async def _handle_assign_room(' in content:
    print('Handler methods already exist!')
    exit(0)

# Find the insertion point - after _handle_assign_task ends, before _handle_send_email
search_pattern = r'(                error=result\.error\n            \)\n\n    async def _handle_send_email\()'

handler_code = '''                error=result.error
            )

    async def _handle_assign_room(
        self, session_id: str, intent: AdminIntent, confidence: float,
        entities: Dict, user_id: int
    ) -> AdminAIResponse:
        """Handle assign room to booking"""
        booking_id = entities.get("booking_id")
        room_id = entities.get("room_id") or entities.get("target_room_id")

        if not booking_id:
            return AdminAIResponse(
                message="Please specify a booking ID. For example: 'Assign room 501 to booking 123'",
                intent=intent, confidence=confidence, session_id=session_id,
                suggestions=["Assign room 501 to booking 1", "Show bookings today"]
            )

        if not room_id:
            return AdminAIResponse(
                message="Please specify a room number. For example: 'Assign room 501 to booking 123'",
                intent=intent, confidence=confidence, session_id=session_id,
                suggestions=["Show available rooms"]
            )

        room_query = await self.sql_executor.execute_raw(
            "SELECT id, number, status FROM rooms WHERE number = :room_num OR id = :room_id LIMIT 1",
            {"room_num": str(room_id), "room_id": room_id}
        )

        if not room_query.success or not room_query.data:
            return AdminAIResponse(
                message=f"Room {room_id} not found.", intent=intent, confidence=confidence,
                session_id=session_id, error="Room not found"
            )

        room = room_query.data[0]
        room_db_id = room.get("id")
        room_number = room.get("number")
        room_status = room.get("status", "unknown")

        if room_status not in ["available", "clean", "inspected"]:
            return AdminAIResponse(
                message=f"Room {room_number} is **{room_status}**. Only available/clean rooms can be assigned.",
                intent=intent, confidence=confidence, session_id=session_id,
                suggestions=["Show available rooms"]
            )

        booking_query = await self.sql_executor.execute_raw(
            """SELECT b.id, b.booking_number, b.status, b.room_id,
                      g.first_name, g.last_name, rt.name as room_type_name
               FROM bookings b
               LEFT JOIN guests g ON b.guest_id = g.id
               LEFT JOIN room_types rt ON b.room_type_id = rt.id
               WHERE b.id = :booking_id OR b.booking_number LIKE :booking_num
               LIMIT 1""",
            {"booking_id": booking_id, "booking_num": f"%{booking_id}%"}
        )

        if not booking_query.success or not booking_query.data:
            return AdminAIResponse(
                message=f"Booking {booking_id} not found.", intent=intent, confidence=confidence,
                session_id=session_id, error="Booking not found"
            )

        booking = booking_query.data[0]
        booking_db_id = booking.get("id")
        guest_name = f"{booking.get('first_name', '')} {booking.get('last_name', '')}".strip() or "Guest"

        if booking.get("room_id"):
            return AdminAIResponse(
                message=f"Booking already has a room. Use **transfer** to move to room {room_number}.",
                intent=intent, confidence=confidence, session_id=session_id,
                suggestions=[f"Transfer guest to room {room_number}"]
            )

        action = ActionRequest(
            action_type=ActionType.ASSIGN_ROOM,
            params={"booking_id": booking_db_id, "room_id": room_db_id, "room_number": room_number}
        )
        pending = self.action_executor.prepare_action(action, user_id)

        return AdminAIResponse(
            message=f"Assign room **{room_number}** to booking:\\n\\n"
                    f"- **Guest:** {guest_name}\\n"
                    f"- **Booking:** {booking.get('booking_number', booking_id)}\\n"
                    f"- **Room Type:** {booking.get('room_type_name', 'N/A')}\\n\\nConfirm?",
            intent=intent, confidence=confidence, session_id=session_id,
            pending_action={
                "action_id": pending.action_id, "action_type": pending.action_type.value,
                "description": pending.description, "params": pending.params
            }
        )

    async def _handle_transfer_room(
        self, session_id: str, intent: AdminIntent, confidence: float,
        entities: Dict, user_id: int
    ) -> AdminAIResponse:
        """Handle transfer guest to different room"""
        from_room = entities.get("from_room_id") or entities.get("room_id")
        to_room = entities.get("target_room_id")
        booking_id = entities.get("booking_id")

        if not to_room:
            return AdminAIResponse(
                message="Please specify the target room. Example: 'Transfer from room 501 to 502'",
                intent=intent, confidence=confidence, session_id=session_id,
                suggestions=["Show available rooms"]
            )

        target_room_query = await self.sql_executor.execute_raw(
            "SELECT id, number, status FROM rooms WHERE number = :room_num OR id = :room_id LIMIT 1",
            {"room_num": str(to_room), "room_id": to_room}
        )

        if not target_room_query.success or not target_room_query.data:
            return AdminAIResponse(
                message=f"Target room {to_room} not found.", intent=intent, confidence=confidence,
                session_id=session_id, error="Target room not found"
            )

        target_room = target_room_query.data[0]
        target_room_id = target_room.get("id")
        target_room_number = target_room.get("number")
        target_room_status = target_room.get("status", "unknown")

        if target_room_status not in ["available", "clean", "inspected"]:
            return AdminAIResponse(
                message=f"Room {target_room_number} is **{target_room_status}** and cannot receive a transfer.",
                intent=intent, confidence=confidence, session_id=session_id,
                suggestions=["Show available rooms"]
            )

        booking_query = None
        source_room_number = "Unknown"
        source_room_id = None
        if from_room:
            src_room_query = await self.sql_executor.execute_raw(
                "SELECT id, number FROM rooms WHERE number = :room_num OR id = :room_id LIMIT 1",
                {"room_num": str(from_room), "room_id": from_room}
            )
            if src_room_query.success and src_room_query.data:
                source_room_id = src_room_query.data[0].get("id")
                source_room_number = src_room_query.data[0].get("number")
                booking_query = await self.sql_executor.execute_raw(
                    """SELECT b.id, b.booking_number, b.room_id, g.first_name, g.last_name
                       FROM bookings b LEFT JOIN guests g ON b.guest_id = g.id
                       WHERE b.room_id = :room_id AND b.status = 'checked_in' LIMIT 1""",
                    {"room_id": source_room_id}
                )
        elif booking_id:
            booking_query = await self.sql_executor.execute_raw(
                """SELECT b.id, b.booking_number, b.room_id, g.first_name, g.last_name, r.number as source_room_number
                   FROM bookings b LEFT JOIN guests g ON b.guest_id = g.id LEFT JOIN rooms r ON b.room_id = r.id
                   WHERE b.id = :booking_id LIMIT 1""",
                {"booking_id": booking_id}
            )

        if not booking_query or not booking_query.success or not booking_query.data:
            return AdminAIResponse(
                message="Couldn't find an active booking to transfer.",
                intent=intent, confidence=confidence, session_id=session_id,
                suggestions=["Show checked-in guests"]
            )

        booking = booking_query.data[0]
        booking_db_id = booking.get("id")
        if booking.get("source_room_number"):
            source_room_number = booking.get("source_room_number")
        guest_name = f"{booking.get('first_name', '')} {booking.get('last_name', '')}".strip() or "Guest"

        action = ActionRequest(
            action_type=ActionType.TRANSFER_ROOM,
            params={
                "booking_id": booking_db_id, "from_room_id": booking.get("room_id"),
                "to_room_id": target_room_id, "from_room_number": source_room_number,
                "to_room_number": target_room_number
            }
        )
        pending = self.action_executor.prepare_action(action, user_id)

        return AdminAIResponse(
            message=f"Transfer guest:\\n\\n- **Guest:** {guest_name}\\n- **From:** {source_room_number}\\n- **To:** {target_room_number}\\n\\nConfirm?",
            intent=intent, confidence=confidence, session_id=session_id,
            pending_action={
                "action_id": pending.action_id, "action_type": pending.action_type.value,
                "description": pending.description, "params": pending.params
            }
        )

    async def _handle_create_guest_note(
        self, session_id: str, intent: AdminIntent, confidence: float,
        entities: Dict, user_id: int, message: str
    ) -> AdminAIResponse:
        """Handle adding note to guest profile"""
        guest_id = entities.get("guest_id")
        note_text = entities.get("note_text")

        if not note_text:
            import re as regex
            patterns = [r'note[:\\s]+["\\'']?(.+?)["\\']?$', r'["\\']([^"\\']+)["\\']']
            for pattern in patterns:
                match = regex.search(pattern, message, regex.IGNORECASE)
                if match:
                    note_text = match.group(1).strip()
                    break

        if not guest_id:
            return AdminAIResponse(
                message="Please specify a guest ID. Example: 'Add note to guest 15: VIP customer'",
                intent=intent, confidence=confidence, session_id=session_id,
                suggestions=["Show guests"]
            )

        if not note_text:
            return AdminAIResponse(
                message=f"What note should I add to guest {guest_id}?",
                intent=intent, confidence=confidence, session_id=session_id
            )

        guest_query = await self.sql_executor.execute_raw(
            "SELECT id, first_name, last_name FROM guests WHERE id = :guest_id LIMIT 1",
            {"guest_id": guest_id}
        )

        if not guest_query.success or not guest_query.data:
            return AdminAIResponse(
                message=f"Guest {guest_id} not found.", intent=intent, confidence=confidence,
                session_id=session_id, error="Guest not found"
            )

        guest = guest_query.data[0]
        guest_name = f"{guest.get('first_name', '')} {guest.get('last_name', '')}".strip() or "Guest"

        action = ActionRequest(
            action_type=ActionType.CREATE_GUEST_NOTE,
            params={"guest_id": guest_id, "note_text": note_text, "author_id": user_id}
        )
        pending = self.action_executor.prepare_action(action, user_id)

        return AdminAIResponse(
            message=f"Add note to guest:\\n\\n- **Guest:** {guest_name} (ID: {guest_id})\\n- **Note:** {note_text[:100]}{'...' if len(note_text) > 100 else ''}\\n\\nConfirm?",
            intent=intent, confidence=confidence, session_id=session_id,
            pending_action={
                "action_id": pending.action_id, "action_type": pending.action_type.value,
                "description": pending.description, "params": pending.params
            }
        )

    async def _handle_send_email('''

# Perform the replacement
new_content = re.sub(search_pattern, handler_code, content)

if new_content == content:
    print('ERROR: Pattern not found!')
    exit(1)

# Write the modified content
with open('app/services/admin_ai_assistant.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('SUCCESS: Handler methods added!')
