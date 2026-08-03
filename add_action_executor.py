"""Script to add executor methods to action_executor.py"""
import re

# Read the current file
with open('app/services/admin_ai/action_executor.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if implementations already exist
if '_assign_room' in content:
    print('Executor methods already exist!')
    exit(0)

# Step 1: Add routing in execute method
routing_pattern = r'(elif action\.action_type == ActionType\.SEND_NOTIFICATION:\s+return await self\._send_notification\(action, user_id, action_id\)\s+)(else:)'

routing_replacement = r'''\1elif action.action_type == ActionType.ASSIGN_ROOM:
                return await self._assign_room(action, user_id, action_id)

            elif action.action_type == ActionType.TRANSFER_ROOM:
                return await self._transfer_room(action, user_id, action_id)

            elif action.action_type == ActionType.CREATE_GUEST_NOTE:
                return await self._create_guest_note(action, user_id, action_id)

            \2'''

content = re.sub(routing_pattern, routing_replacement, content)

# Step 2: Add implementation methods before EmailActionExecutor class
impl_methods = '''
    async def _assign_room(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Assign a room to a booking"""
        params = action.params
        booking_id = params.get("booking_id")
        room_id = params.get("room_id")
        room_number = params.get("room_number", room_id)

        # Update booking with room assignment
        query = text("""
            UPDATE bookings
            SET room_id = :room_id, updated_at = :updated_at
            WHERE id = :booking_id
        """)

        await self.session.execute(query, {
            "booking_id": booking_id,
            "room_id": room_id,
            "updated_at": datetime.utcnow().isoformat(),
        })

        # Update room status to occupied/assigned
        room_query = text("""
            UPDATE rooms
            SET status = 'occupied', updated_at = :updated_at
            WHERE id = :room_id
        """)

        await self.session.execute(room_query, {
            "room_id": room_id,
            "updated_at": datetime.utcnow().isoformat(),
        })

        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Room {room_number} assigned to booking {booking_id}",
            data={"booking_id": booking_id, "room_id": room_id, "room_number": room_number}
        )

    async def _transfer_room(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Transfer guest to a different room"""
        params = action.params
        booking_id = params.get("booking_id")
        from_room_id = params.get("from_room_id")
        to_room_id = params.get("to_room_id")
        from_room_number = params.get("from_room_number", from_room_id)
        to_room_number = params.get("to_room_number", to_room_id)

        # Update booking with new room
        booking_query = text("""
            UPDATE bookings
            SET room_id = :to_room_id, updated_at = :updated_at
            WHERE id = :booking_id
        """)

        await self.session.execute(booking_query, {
            "booking_id": booking_id,
            "to_room_id": to_room_id,
            "updated_at": datetime.utcnow().isoformat(),
        })

        # Set old room to dirty (needs cleaning)
        if from_room_id:
            old_room_query = text("""
                UPDATE rooms
                SET status = 'dirty', updated_at = :updated_at
                WHERE id = :room_id
            """)
            await self.session.execute(old_room_query, {
                "room_id": from_room_id,
                "updated_at": datetime.utcnow().isoformat(),
            })

        # Set new room to occupied
        new_room_query = text("""
            UPDATE rooms
            SET status = 'occupied', updated_at = :updated_at
            WHERE id = :room_id
        """)
        await self.session.execute(new_room_query, {
            "room_id": to_room_id,
            "updated_at": datetime.utcnow().isoformat(),
        })

        # Log the room change
        try:
            change_log_query = text("""
                INSERT INTO room_changes
                (booking_id, from_room_id, to_room_id, reason, changed_by, created_at)
                VALUES (:booking_id, :from_room_id, :to_room_id, :reason, :changed_by, :created_at)
            """)
            await self.session.execute(change_log_query, {
                "booking_id": booking_id,
                "from_room_id": from_room_id,
                "to_room_id": to_room_id,
                "reason": "Room transfer via Admin AI",
                "changed_by": user_id,
                "created_at": datetime.utcnow().isoformat(),
            })
        except Exception:
            # Table might not exist, that's ok
            pass

        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Guest transferred from room {from_room_number} to room {to_room_number}",
            data={
                "booking_id": booking_id,
                "from_room_id": from_room_id,
                "to_room_id": to_room_id,
                "from_room_number": from_room_number,
                "to_room_number": to_room_number
            }
        )

    async def _create_guest_note(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Add a note to a guest's profile"""
        params = action.params
        guest_id = params.get("guest_id")
        note_text = params.get("note_text")
        author_id = params.get("author_id", user_id)

        # Get current notes and add new one
        # Guest notes are stored as JSON array in the 'notes' field
        import json as json_lib

        # Get current notes
        get_query = text("SELECT notes FROM guests WHERE id = :guest_id")
        result = await self.session.execute(get_query, {"guest_id": guest_id})
        row = result.fetchone()

        current_notes = []
        if row and row[0]:
            try:
                current_notes = json_lib.loads(row[0]) if isinstance(row[0], str) else row[0]
            except:
                current_notes = []

        # Add new note
        new_note = {
            "id": str(uuid.uuid4())[:8],
            "text": note_text,
            "author_id": author_id,
            "created_at": datetime.utcnow().isoformat()
        }
        current_notes.append(new_note)

        # Update guest notes
        update_query = text("""
            UPDATE guests
            SET notes = :notes, updated_at = :updated_at
            WHERE id = :guest_id
        """)

        await self.session.execute(update_query, {
            "guest_id": guest_id,
            "notes": json_lib.dumps(current_notes),
            "updated_at": datetime.utcnow().isoformat(),
        })

        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Note added to guest {guest_id}",
            data={"guest_id": guest_id, "note": new_note}
        )


'''

# Find where EmailActionExecutor class starts and insert before it
class_pattern = r'(class EmailActionExecutor:)'
content = re.sub(class_pattern, impl_methods + r'\1', content)

# Write the modified content
with open('app/services/admin_ai/action_executor.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('SUCCESS: Executor methods added!')
