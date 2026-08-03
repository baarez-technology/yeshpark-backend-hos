"""
Room Service Tools for AGI Guest Assistant
Handles all room service/food ordering operations
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("agi.room_service_tools")


class RoomServiceTools:
    """Tools for room service and food ordering"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._menu = self._load_menu()

    def _load_menu(self) -> Dict[str, Any]:
        """Load room service menu"""
        return {
            "breakfast": {
                "available_hours": "6:30 AM - 11:00 AM",
                "items": [
                    {"id": "b1", "name": "Continental Breakfast", "price": 18.00, "description": "Fresh pastries, fruit, yogurt, juice, and coffee/tea"},
                    {"id": "b2", "name": "American Breakfast", "price": 24.00, "description": "Two eggs any style, bacon or sausage, toast, hash browns"},
                    {"id": "b3", "name": "Eggs Benedict", "price": 22.00, "description": "Poached eggs, Canadian bacon, hollandaise on English muffin"},
                    {"id": "b4", "name": "Avocado Toast", "price": 16.00, "description": "Smashed avocado, poached egg, cherry tomatoes on sourdough"},
                    {"id": "b5", "name": "Pancake Stack", "price": 15.00, "description": "Three fluffy pancakes with maple syrup and butter"},
                    {"id": "b6", "name": "Fresh Fruit Platter", "price": 14.00, "description": "Seasonal fresh fruits with honey yogurt"},
                    {"id": "b7", "name": "Omelette", "price": 18.00, "description": "Three-egg omelette with choice of fillings"},
                ]
            },
            "lunch": {
                "available_hours": "11:00 AM - 5:00 PM",
                "items": [
                    {"id": "l1", "name": "Club Sandwich", "price": 19.00, "description": "Triple-decker with turkey, bacon, lettuce, tomato"},
                    {"id": "l2", "name": "Caesar Salad", "price": 16.00, "description": "Romaine, parmesan, croutons, Caesar dressing. Add chicken +$6"},
                    {"id": "l3", "name": "Gourmet Burger", "price": 22.00, "description": "8oz Angus beef, cheddar, lettuce, tomato, special sauce, fries"},
                    {"id": "l4", "name": "Fish & Chips", "price": 24.00, "description": "Beer-battered cod, thick-cut fries, tartar sauce, coleslaw"},
                    {"id": "l5", "name": "Grilled Chicken Wrap", "price": 17.00, "description": "Grilled chicken, avocado, mixed greens, chipotle mayo"},
                    {"id": "l6", "name": "Soup of the Day", "price": 10.00, "description": "Chef's daily selection with artisan bread"},
                ]
            },
            "dinner": {
                "available_hours": "5:00 PM - 11:00 PM",
                "items": [
                    {"id": "d1", "name": "Filet Mignon", "price": 48.00, "description": "8oz center-cut, red wine reduction, mashed potatoes, asparagus"},
                    {"id": "d2", "name": "Grilled Salmon", "price": 36.00, "description": "Atlantic salmon, lemon herb butter, rice pilaf, vegetables"},
                    {"id": "d3", "name": "Chicken Parmesan", "price": 28.00, "description": "Breaded chicken, marinara, mozzarella, spaghetti"},
                    {"id": "d4", "name": "Vegetable Risotto", "price": 24.00, "description": "Arborio rice, seasonal vegetables, parmesan (V)"},
                    {"id": "d5", "name": "Lobster Tail", "price": 58.00, "description": "Broiled Maine lobster, drawn butter, twice-baked potato"},
                    {"id": "d6", "name": "Pasta Primavera", "price": 22.00, "description": "Penne, seasonal vegetables, light cream sauce (V)"},
                ]
            },
            "all_day": {
                "available_hours": "24 hours",
                "items": [
                    {"id": "a1", "name": "French Fries", "price": 8.00, "description": "Crispy golden fries with ketchup and aioli"},
                    {"id": "a2", "name": "Chicken Wings", "price": 16.00, "description": "10 pieces, choice of buffalo, BBQ, or garlic parmesan"},
                    {"id": "a3", "name": "Cheese Pizza", "price": 18.00, "description": "12\" personal pizza, mozzarella, marinara"},
                    {"id": "a4", "name": "Nachos Grande", "price": 15.00, "description": "Tortilla chips, cheese, jalapeños, sour cream, guacamole"},
                    {"id": "a5", "name": "Ice Cream Sundae", "price": 10.00, "description": "Three scoops, chocolate sauce, whipped cream, cherry"},
                    {"id": "a6", "name": "Chocolate Cake", "price": 12.00, "description": "Rich chocolate layer cake with ganache"},
                    {"id": "a7", "name": "Fresh Fruit Bowl", "price": 12.00, "description": "Seasonal fresh cut fruits"},
                ]
            },
            "beverages": {
                "available_hours": "24 hours",
                "items": [
                    {"id": "bv1", "name": "Coffee", "price": 5.00, "description": "Fresh brewed, regular or decaf"},
                    {"id": "bv2", "name": "Tea Selection", "price": 5.00, "description": "English Breakfast, Earl Grey, Green, Chamomile"},
                    {"id": "bv3", "name": "Fresh Juice", "price": 7.00, "description": "Orange, Apple, Grapefruit, or Tomato"},
                    {"id": "bv4", "name": "Soft Drinks", "price": 4.00, "description": "Coke, Diet Coke, Sprite, Ginger Ale"},
                    {"id": "bv5", "name": "Bottled Water", "price": 4.00, "description": "Still or sparkling"},
                    {"id": "bv6", "name": "Hot Chocolate", "price": 6.00, "description": "Rich cocoa with whipped cream"},
                    {"id": "bv7", "name": "Smoothie", "price": 9.00, "description": "Tropical, Berry, or Green"},
                ]
            },
            "special_dietary": {
                "available_hours": "All day (request may take longer)",
                "items": [
                    {"id": "sd1", "name": "Gluten-Free Pasta", "price": 20.00, "description": "GF penne with choice of marinara or olive oil (GF)"},
                    {"id": "sd2", "name": "Vegan Buddha Bowl", "price": 18.00, "description": "Quinoa, roasted vegetables, tahini dressing (V, VG, GF)"},
                    {"id": "sd3", "name": "Keto Plate", "price": 26.00, "description": "Grilled chicken, avocado, mixed greens, olive oil (K, GF)"},
                    {"id": "sd4", "name": "Kids Meal", "price": 12.00, "description": "Choice of nuggets, mac & cheese, or grilled cheese with fries"},
                ]
            }
        }

    async def get_menu(
        self,
        category: Optional[str] = None,
        dietary_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get room service menu.

        Args:
            category: Specific category (breakfast, lunch, dinner, all_day, beverages, special_dietary)
            dietary_filter: Filter by dietary need (vegetarian, vegan, gluten_free, keto)

        Returns:
            Menu information
        """
        current_hour = datetime.now().hour

        # Determine what's currently available
        available_now = ["all_day", "beverages"]
        if 6 <= current_hour < 11:
            available_now.append("breakfast")
        if 11 <= current_hour < 17:
            available_now.append("lunch")
        if 17 <= current_hour < 23:
            available_now.append("dinner")

        if category:
            if category in self._menu:
                return {
                    "success": True,
                    "category": category,
                    "available_hours": self._menu[category]["available_hours"],
                    "items": self._menu[category]["items"],
                    "is_available_now": category in available_now,
                    "delivery_time": "30-45 minutes"
                }
            return {
                "success": False,
                "message": f"Category '{category}' not found. Available categories: {list(self._menu.keys())}"
            }

        # Return full menu with availability info
        menu_with_availability = {}
        for cat, data in self._menu.items():
            menu_with_availability[cat] = {
                **data,
                "is_available_now": cat in available_now
            }

        return {
            "success": True,
            "menu": menu_with_availability,
            "currently_available": available_now,
            "delivery_time": "30-45 minutes",
            "service_charge": "18% gratuity added automatically"
        }

    async def place_order(
        self,
        room_number: str,
        items: List[Dict[str, Any]],
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        special_instructions: Optional[str] = None,
        delivery_time: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Place a room service order.

        Args:
            room_number: Guest's room number
            items: List of items to order [{"item_id": "b1", "quantity": 1, "modifications": "no onions"}]
            guest_id: Guest ID
            booking_id: Booking ID
            special_instructions: Special instructions for the order
            delivery_time: Preferred delivery time (optional, defaults to ASAP)

        Returns:
            Order confirmation
        """
        from app.services.staff_scheduling_service import get_scheduling_service
        from app.models.inventory import Room

        try:
            # Validate and calculate order
            order_items = []
            total = 0.0
            all_items_flat = []
            for cat_data in self._menu.values():
                all_items_flat.extend(cat_data["items"])

            for item in items:
                item_id = item.get("item_id")
                quantity = item.get("quantity", 1)

                # Find item in menu
                menu_item = next((i for i in all_items_flat if i["id"] == item_id), None)

                if not menu_item:
                    return {
                        "success": False,
                        "message": f"Item '{item_id}' not found in menu."
                    }

                item_total = menu_item["price"] * quantity
                total += item_total

                order_items.append({
                    "item_id": item_id,
                    "name": menu_item["name"],
                    "quantity": quantity,
                    "unit_price": menu_item["price"],
                    "total": item_total,
                    "modifications": item.get("modifications")
                })

            # Add service charge (18%)
            service_charge = round(total * 0.18, 2)
            grand_total = round(total + service_charge, 2)

            # Get room ID
            result = await self.db.execute(select(Room).where(Room.number == room_number))
            room = result.scalars().first()
            room_id = room.id if room else None

            # Create order task
            scheduling_service = get_scheduling_service(self.db)

            order_description = "Room Service Order:\n"
            for oi in order_items:
                order_description += f"- {oi['quantity']}x {oi['name']}"
                if oi.get("modifications"):
                    order_description += f" ({oi['modifications']})"
                order_description += f" - ${oi['total']:.2f}\n"
            order_description += f"\nSubtotal: ${total:.2f}\nService Charge (18%): ${service_charge:.2f}\nTotal: ${grand_total:.2f}"

            if special_instructions:
                order_description += f"\n\nSpecial Instructions: {special_instructions}"

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="room_service",
                title=f"Room Service Order - Room {room_number}",
                description=order_description,
                priority="high",
                room_number=room_number,
                room_id=room_id,
                booking_id=booking_id,
                guest_id=guest_id
            )

            order_id = f"RS-{task.id}" if task else f"RS-{datetime.now().strftime('%Y%m%d%H%M%S')}"

            return {
                "success": True,
                "order_id": order_id,
                "task_id": task.id if task else None,
                "room_number": room_number,
                "items": order_items,
                "subtotal": total,
                "service_charge": service_charge,
                "grand_total": grand_total,
                "estimated_delivery": delivery_time or "30-45 minutes",
                "status": "confirmed",
                "message": f"Your order has been placed! Order #{order_id}. Estimated delivery: {delivery_time or '30-45 minutes'}. Total: ${grand_total:.2f} (includes 18% gratuity)."
            }

        except Exception as e:
            logger.error(f"Error placing room service order: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to place your order. Please try again or call room service at extension 33."
            }

    async def get_order_status(
        self,
        room_number: str,
        order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get status of room service order(s).

        Args:
            room_number: Guest's room number
            order_id: Specific order ID (optional)

        Returns:
            Order status information
        """
        from app.models.guest_chat import StaffTask

        try:
            query = select(StaffTask).where(
                and_(
                    StaffTask.room_number == room_number,
                    StaffTask.task_type == "room_service"
                )
            ).order_by(StaffTask.created_at.desc()).limit(5)

            result = await self.db.execute(query)
            tasks = result.scalars().all()

            orders = []
            for task in tasks:
                status_messages = {
                    "pending": "Order received - preparing your food",
                    "assigned": "Order being prepared in kitchen",
                    "in_progress": "Your order is on its way!",
                    "completed": "Order delivered"
                }

                orders.append({
                    "order_id": f"RS-{task.id}",
                    "status": task.status,
                    "status_message": status_messages.get(task.status, task.status),
                    "created_at": task.created_at.isoformat(),
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None
                })

            return {
                "success": True,
                "room_number": room_number,
                "orders": orders,
                "message": f"Found {len(orders)} recent order(s)." if orders else "No recent orders found."
            }

        except Exception as e:
            logger.error(f"Error getting order status: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to retrieve order status."
            }

    async def cancel_order(
        self,
        order_id: str,
        room_number: str,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Cancel a room service order (if not yet in preparation).

        Args:
            order_id: Order ID (format: RS-XXX)
            room_number: Guest's room number for verification
            reason: Cancellation reason

        Returns:
            Cancellation result
        """
        from app.models.guest_chat import StaffTask

        try:
            # Extract task ID from order ID
            task_id = int(order_id.replace("RS-", ""))

            result = await self.db.execute(
                select(StaffTask).where(
                    and_(
                        StaffTask.id == task_id,
                        StaffTask.room_number == room_number,
                        StaffTask.task_type == "room_service"
                    )
                )
            )
            task = result.scalars().first()

            if not task:
                return {
                    "success": False,
                    "message": "Order not found."
                }

            if task.status in ["in_progress", "completed"]:
                return {
                    "success": False,
                    "message": f"Order cannot be cancelled - it is already {task.status.replace('_', ' ')}. Please call room service at extension 33."
                }

            # Cancel the order
            task.status = "cancelled"
            task.notes = (task.notes or "") + f"\n[{datetime.utcnow().isoformat()}] Cancelled by guest. Reason: {reason or 'Not specified'}"
            task.updated_at = datetime.utcnow()

            await self.db.commit()

            return {
                "success": True,
                "order_id": order_id,
                "status": "cancelled",
                "message": "Your order has been cancelled. No charges will be applied."
            }

        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to cancel order. Please call room service at extension 33."
            }

    async def get_recommendations(
        self,
        meal_type: Optional[str] = None,
        dietary_preferences: Optional[List[str]] = None,
        budget: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get personalized food recommendations.

        Args:
            meal_type: Type of meal (breakfast, lunch, dinner, snack)
            dietary_preferences: Dietary preferences (vegetarian, vegan, gluten_free)
            budget: Budget level (budget, moderate, premium)

        Returns:
            Personalized recommendations
        """
        current_hour = datetime.now().hour

        # Auto-detect meal type if not specified
        if not meal_type:
            if 6 <= current_hour < 11:
                meal_type = "breakfast"
            elif 11 <= current_hour < 17:
                meal_type = "lunch"
            elif 17 <= current_hour < 22:
                meal_type = "dinner"
            else:
                meal_type = "late_night"

        recommendations = []

        if meal_type == "breakfast":
            recommendations = [
                {"item": "American Breakfast", "reason": "Our most popular breakfast choice", "price": 24.00},
                {"item": "Avocado Toast", "reason": "Light and healthy option", "price": 16.00},
                {"item": "Fresh Fruit Platter", "reason": "Perfect for a refreshing start", "price": 14.00}
            ]
        elif meal_type == "lunch":
            recommendations = [
                {"item": "Gourmet Burger", "reason": "Guest favorite", "price": 22.00},
                {"item": "Caesar Salad", "reason": "Light and satisfying", "price": 16.00},
                {"item": "Club Sandwich", "reason": "Classic and filling", "price": 19.00}
            ]
        elif meal_type == "dinner":
            recommendations = [
                {"item": "Filet Mignon", "reason": "Premium dining experience", "price": 48.00},
                {"item": "Grilled Salmon", "reason": "Healthy and delicious", "price": 36.00},
                {"item": "Chicken Parmesan", "reason": "Comfort food favorite", "price": 28.00}
            ]
        else:
            recommendations = [
                {"item": "Cheese Pizza", "reason": "Perfect late-night snack", "price": 18.00},
                {"item": "Chicken Wings", "reason": "Great for sharing or snacking", "price": 16.00},
                {"item": "Ice Cream Sundae", "reason": "Sweet treat", "price": 10.00}
            ]

        # Filter by budget if specified
        if budget == "budget":
            recommendations = [r for r in recommendations if r["price"] <= 20]
        elif budget == "premium":
            recommendations = [r for r in recommendations if r["price"] >= 30]

        return {
            "success": True,
            "meal_type": meal_type,
            "recommendations": recommendations,
            "dietary_options_available": True,
            "message": f"Here are our top {meal_type} recommendations for you:",
            "order_prompt": "Would you like to order any of these items?"
        }


def get_room_service_tools(db: AsyncSession) -> RoomServiceTools:
    """Factory function to create RoomServiceTools instance"""
    return RoomServiceTools(db)
