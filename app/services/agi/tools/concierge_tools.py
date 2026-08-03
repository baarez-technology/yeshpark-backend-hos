"""
Concierge Tools for AGI Guest Assistant
Handles all concierge-related operations
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("agi.concierge_tools")


class ConciergeTools:
    """Tools for concierge services"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._local_attractions = self._load_attractions()
        self._services = self._load_services()

    def _load_attractions(self) -> Dict[str, List[Dict]]:
        """Load local attractions database"""
        return {
            "restaurants": [
                {"name": "The Garden Bistro", "type": "Fine Dining", "cuisine": "French", "distance": "0.3 miles", "price": "$$$$", "rating": 4.8},
                {"name": "Sakura Sushi", "type": "Japanese", "cuisine": "Japanese", "distance": "0.5 miles", "price": "$$$", "rating": 4.6},
                {"name": "Trattoria Milano", "type": "Italian", "cuisine": "Italian", "distance": "0.4 miles", "price": "$$$", "rating": 4.7},
                {"name": "The Steakhouse", "type": "American", "cuisine": "Steakhouse", "distance": "0.6 miles", "price": "$$$$", "rating": 4.5},
                {"name": "Cafe Luna", "type": "Casual", "cuisine": "Cafe", "distance": "0.2 miles", "price": "$$", "rating": 4.4},
                {"name": "Thai Orchid", "type": "Thai", "cuisine": "Thai", "distance": "0.7 miles", "price": "$$", "rating": 4.5},
            ],
            "attractions": [
                {"name": "City Art Museum", "type": "Museum", "description": "World-class art collection", "distance": "1.2 miles", "hours": "10 AM - 6 PM"},
                {"name": "Central Park", "type": "Park", "description": "Beautiful gardens and walking paths", "distance": "0.8 miles", "hours": "6 AM - 10 PM"},
                {"name": "Historic District", "type": "Historic", "description": "Victorian architecture tour", "distance": "1.5 miles", "hours": "Self-guided"},
                {"name": "Waterfront Promenade", "type": "Scenic", "description": "Harbor views and dining", "distance": "0.5 miles", "hours": "Open 24h"},
                {"name": "Shopping Center", "type": "Shopping", "description": "Luxury brands and local boutiques", "distance": "0.3 miles", "hours": "10 AM - 9 PM"},
            ],
            "entertainment": [
                {"name": "Grand Theater", "type": "Theater", "description": "Broadway shows and concerts", "distance": "0.9 miles"},
                {"name": "Jazz Club 42", "type": "Nightlife", "description": "Live jazz performances nightly", "distance": "0.4 miles"},
                {"name": "Rooftop Lounge", "type": "Bar", "description": "Craft cocktails with city views", "distance": "0.2 miles"},
                {"name": "Cinema Palace", "type": "Movies", "description": "IMAX and luxury seating", "distance": "0.6 miles"},
            ]
        }

    def _load_services(self) -> Dict[str, Dict]:
        """Load available concierge services"""
        return {
            "transportation": {
                "taxi": {"description": "Traditional taxi service", "wait_time": "5-10 minutes", "booking_required": False},
                "uber": {"description": "Ride share service", "wait_time": "5-15 minutes", "booking_required": False},
                "limo": {"description": "Luxury limousine", "wait_time": "30-60 minutes", "booking_required": True, "price_range": "$100-300"},
                "airport_shuttle": {"description": "Airport transfer service", "wait_time": "Book 24h ahead", "booking_required": True, "price": "$45"},
                "rental_car": {"description": "Car rental coordination", "booking_required": True}
            },
            "spa": {
                "massage": {"types": ["Swedish", "Deep Tissue", "Hot Stone", "Couples"], "duration": "60-90 min", "price_range": "$120-250"},
                "facial": {"types": ["Classic", "Anti-Aging", "Hydrating"], "duration": "45-60 min", "price_range": "$80-150"},
                "body_treatment": {"types": ["Body Wrap", "Scrub", "Mud Treatment"], "duration": "60 min", "price_range": "$100-180"},
                "salon": {"types": ["Haircut", "Blowout", "Manicure", "Pedicure"], "price_range": "$40-150"}
            },
            "tours": {
                "city_tour": {"duration": "3 hours", "price": "$75/person", "description": "Highlights of the city"},
                "food_tour": {"duration": "4 hours", "price": "$95/person", "description": "Local culinary experience"},
                "private_tour": {"duration": "Customizable", "price": "From $200", "description": "Personalized guided tour"},
            },
            "special_services": {
                "flowers": {"description": "Fresh flower arrangements", "price_range": "$50-200"},
                "champagne": {"description": "In-room champagne service", "price_range": "$80-300"},
                "birthday_setup": {"description": "Room decoration and cake", "price_range": "$100-250"},
                "romantic_package": {"description": "Rose petals, champagne, chocolates", "price": "$150"}
            }
        }

    async def get_restaurant_recommendations(
        self,
        cuisine_type: Optional[str] = None,
        price_range: Optional[str] = None,
        distance_max: Optional[str] = None,
        occasion: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get restaurant recommendations.

        Args:
            cuisine_type: Type of cuisine (Italian, Japanese, French, etc.)
            price_range: Budget ($, $$, $$$, $$$$)
            distance_max: Maximum walking distance
            occasion: Special occasion (business, romantic, casual, family)

        Returns:
            Restaurant recommendations
        """
        restaurants = self._local_attractions["restaurants"].copy()

        # Filter by cuisine
        if cuisine_type:
            restaurants = [r for r in restaurants if cuisine_type.lower() in r["cuisine"].lower()]

        # Filter by price
        if price_range:
            price_count = price_range.count("$")
            restaurants = [r for r in restaurants if r["price"].count("$") <= price_count]

        # Sort by rating
        restaurants = sorted(restaurants, key=lambda x: x["rating"], reverse=True)

        # Add recommendation reason based on occasion
        for r in restaurants:
            if occasion == "romantic":
                r["recommendation_note"] = "Perfect for a romantic evening"
            elif occasion == "business":
                r["recommendation_note"] = "Professional atmosphere for business dining"
            elif occasion == "family":
                r["recommendation_note"] = "Family-friendly with excellent service"
            else:
                r["recommendation_note"] = f"Rated {r['rating']} stars by guests"

        return {
            "success": True,
            "restaurants": restaurants[:5],
            "total_found": len(restaurants),
            "can_make_reservation": True,
            "message": f"Here are our top {min(5, len(restaurants))} restaurant recommendations:" if restaurants else "No restaurants match your criteria. Would you like to broaden your search?",
            "reservation_prompt": "Would you like me to make a reservation at any of these restaurants?"
        }

    async def get_local_attractions(
        self,
        category: Optional[str] = None,
        interests: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get local attraction recommendations.

        Args:
            category: Category (museums, parks, shopping, entertainment)
            interests: Guest interests (art, nature, history, nightlife)

        Returns:
            Attraction recommendations
        """
        all_attractions = []
        for cat, items in self._local_attractions.items():
            for item in items:
                item["category"] = cat
                all_attractions.append(item)

        # Filter by category
        if category:
            category_map = {
                "museums": "attractions",
                "parks": "attractions",
                "shopping": "attractions",
                "entertainment": "entertainment",
                "dining": "restaurants"
            }
            mapped_cat = category_map.get(category.lower(), category.lower())
            all_attractions = [a for a in all_attractions if a["category"] == mapped_cat]

        # Sort by distance
        all_attractions = sorted(all_attractions, key=lambda x: float(x.get("distance", "0").split()[0]))

        return {
            "success": True,
            "attractions": all_attractions[:8],
            "total_found": len(all_attractions),
            "message": f"Here are {min(8, len(all_attractions))} great places to explore nearby:",
            "transport_options": "Walking distance for most. We can arrange transportation for farther locations."
        }

    async def book_transportation(
        self,
        room_number: str,
        transport_type: str,
        pickup_time: str,
        destination: str,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        passenger_count: int = 1,
        special_requests: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Book transportation service.

        Args:
            room_number: Guest's room number
            transport_type: Type (taxi, uber, limo, airport_shuttle, rental_car)
            pickup_time: Desired pickup time
            destination: Destination address/location
            guest_id: Guest ID
            booking_id: Booking ID
            passenger_count: Number of passengers
            special_requests: Any special requests

        Returns:
            Booking confirmation
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            service_info = self._services["transportation"].get(transport_type)
            if not service_info:
                return {
                    "success": False,
                    "message": f"Transport type '{transport_type}' not available. Options: taxi, uber, limo, airport_shuttle, rental_car"
                }

            scheduling_service = get_scheduling_service(self.db)

            description = f"""Transportation Request:
Type: {transport_type.replace('_', ' ').title()}
Pickup Time: {pickup_time}
Destination: {destination}
Passengers: {passenger_count}
Room: {room_number}
Special Requests: {special_requests or 'None'}"""

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="concierge",
                title=f"Transportation - {transport_type.replace('_', ' ').title()} - Room {room_number}",
                description=description,
                priority="high" if "airport" in transport_type else "normal",
                room_number=room_number,
                booking_id=booking_id,
                guest_id=guest_id
            )

            return {
                "success": True,
                "booking_id": f"TR-{task.id}" if task else None,
                "task_id": task.id if task else None,
                "transport_type": transport_type,
                "pickup_location": f"Hotel main entrance - Room {room_number}",
                "pickup_time": pickup_time,
                "destination": destination,
                "estimated_wait": service_info["wait_time"],
                "price_estimate": service_info.get("price") or service_info.get("price_range", "Varies"),
                "status": "confirmed",
                "message": f"Your {transport_type.replace('_', ' ')} has been booked for {pickup_time}. Please meet at the hotel main entrance. {'Our concierge will assist you.' if staff else ''}"
            }

        except Exception as e:
            logger.error(f"Error booking transportation: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to book transportation. Please contact the concierge desk."
            }

    async def book_spa_service(
        self,
        room_number: str,
        service_type: str,
        treatment: str,
        preferred_time: str,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        duration: Optional[str] = None,
        therapist_preference: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Book spa service.

        Args:
            room_number: Guest's room number
            service_type: Type (massage, facial, body_treatment, salon)
            treatment: Specific treatment
            preferred_time: Preferred appointment time
            guest_id: Guest ID
            booking_id: Booking ID
            duration: Preferred duration
            therapist_preference: Male/female therapist preference

        Returns:
            Booking confirmation
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            service_info = self._services["spa"].get(service_type)
            if not service_info:
                return {
                    "success": False,
                    "message": f"Spa service '{service_type}' not available. Options: massage, facial, body_treatment, salon"
                }

            scheduling_service = get_scheduling_service(self.db)

            description = f"""Spa Booking Request:
Service: {service_type.replace('_', ' ').title()}
Treatment: {treatment}
Preferred Time: {preferred_time}
Duration: {duration or service_info.get('duration', 'Standard')}
Therapist Preference: {therapist_preference or 'No preference'}
Room: {room_number}
Guest Discount: 15% hotel guest discount applies"""

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="concierge",
                title=f"Spa Booking - {treatment} - Room {room_number}",
                description=description,
                priority="normal",
                room_number=room_number,
                booking_id=booking_id,
                guest_id=guest_id
            )

            return {
                "success": True,
                "booking_id": f"SPA-{task.id}" if task else None,
                "task_id": task.id if task else None,
                "service": service_type,
                "treatment": treatment,
                "scheduled_time": preferred_time,
                "duration": duration or service_info.get("duration"),
                "price_range": service_info.get("price_range"),
                "guest_discount": "15%",
                "location": "Spa Level (Floor 3)",
                "status": "pending_confirmation",
                "message": f"Your {treatment} has been requested for {preferred_time}. Our spa will confirm availability shortly. As a hotel guest, you receive 15% off all spa services."
            }

        except Exception as e:
            logger.error(f"Error booking spa: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to book spa service. Please contact the spa directly at extension 33."
            }

    async def book_restaurant_reservation(
        self,
        restaurant_name: str,
        date: str,
        time: str,
        party_size: int,
        room_number: str,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        special_requests: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Make a restaurant reservation.

        Args:
            restaurant_name: Name of restaurant
            date: Reservation date
            time: Reservation time
            party_size: Number of guests
            room_number: Guest's room number
            guest_id: Guest ID
            booking_id: Booking ID
            special_requests: Special requests (dietary, celebration, etc.)

        Returns:
            Reservation confirmation
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            scheduling_service = get_scheduling_service(self.db)

            description = f"""Restaurant Reservation Request:
Restaurant: {restaurant_name}
Date: {date}
Time: {time}
Party Size: {party_size}
Room: {room_number}
Special Requests: {special_requests or 'None'}"""

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="concierge",
                title=f"Restaurant Reservation - {restaurant_name} - Room {room_number}",
                description=description,
                priority="normal",
                room_number=room_number,
                booking_id=booking_id,
                guest_id=guest_id
            )

            return {
                "success": True,
                "booking_id": f"RES-{task.id}" if task else None,
                "task_id": task.id if task else None,
                "restaurant": restaurant_name,
                "date": date,
                "time": time,
                "party_size": party_size,
                "status": "pending_confirmation",
                "message": f"Your reservation request for {party_size} at {restaurant_name} on {date} at {time} has been submitted. Our concierge will confirm with the restaurant and update you shortly."
            }

        except Exception as e:
            logger.error(f"Error booking restaurant: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to process reservation. Please contact the concierge desk."
            }

    async def request_special_service(
        self,
        room_number: str,
        service_type: str,
        details: str,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        preferred_time: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Request special concierge service (flowers, champagne, special setup).

        Args:
            room_number: Guest's room number
            service_type: Type (flowers, champagne, birthday_setup, romantic_package)
            details: Specific details/preferences
            guest_id: Guest ID
            booking_id: Booking ID
            preferred_time: When to deliver/setup

        Returns:
            Service request confirmation
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            service_info = self._services["special_services"].get(service_type)

            scheduling_service = get_scheduling_service(self.db)

            description = f"""Special Service Request:
Service: {service_type.replace('_', ' ').title()}
Details: {details}
Preferred Time: {preferred_time or 'At earliest convenience'}
Room: {room_number}
Price Range: {service_info['price_range'] if service_info else 'Varies'}"""

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="concierge",
                title=f"Special Service - {service_type.replace('_', ' ').title()} - Room {room_number}",
                description=description,
                priority="high",
                room_number=room_number,
                booking_id=booking_id,
                guest_id=guest_id
            )

            return {
                "success": True,
                "request_id": f"SS-{task.id}" if task else None,
                "task_id": task.id if task else None,
                "service": service_type,
                "details": details,
                "delivery_time": preferred_time or "Within 2 hours",
                "estimated_price": service_info["price_range"] if service_info else "To be confirmed",
                "status": "confirmed",
                "message": f"Your {service_type.replace('_', ' ')} request has been confirmed. {'It will be delivered ' + preferred_time if preferred_time else 'Our team will arrange this shortly'}."
            }

        except Exception as e:
            logger.error(f"Error requesting special service: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to process your request. Please contact the concierge desk."
            }

    async def get_directions(
        self,
        destination: str,
        from_hotel: bool = True,
        transport_mode: str = "walking"
    ) -> Dict[str, Any]:
        """
        Get directions to a destination.

        Args:
            destination: Destination name or address
            from_hotel: Whether starting from hotel
            transport_mode: Mode of transport (walking, driving, transit)

        Returns:
            Direction information
        """
        # Find destination in our database
        all_places = []
        for cat_items in self._local_attractions.values():
            all_places.extend(cat_items)

        found_place = next((p for p in all_places if destination.lower() in p["name"].lower()), None)

        if found_place:
            return {
                "success": True,
                "destination": found_place["name"],
                "distance": found_place.get("distance", "Unknown"),
                "estimated_time": {
                    "walking": f"{int(float(found_place.get('distance', '1').split()[0]) * 20)} minutes",
                    "driving": f"{int(float(found_place.get('distance', '1').split()[0]) * 5)} minutes",
                    "transit": f"{int(float(found_place.get('distance', '1').split()[0]) * 10)} minutes"
                }.get(transport_mode, "15 minutes"),
                "transport_mode": transport_mode,
                "directions": f"Exit hotel main entrance, head towards downtown. {found_place['name']} is {found_place.get('distance', 'nearby')} away.",
                "message": f"To get to {found_place['name']}: Exit hotel main entrance. The destination is {found_place.get('distance', 'nearby')} away by {transport_mode}.",
                "need_taxi": float(found_place.get("distance", "0").split()[0]) > 0.5
            }

        return {
            "success": True,
            "destination": destination,
            "message": f"For directions to {destination}, please visit the concierge desk or ask for a map. We can also arrange transportation if needed.",
            "concierge_available": True
        }

    async def get_weather_info(self) -> Dict[str, Any]:
        """Get current weather information for planning activities."""
        # In production, this would call a weather API
        return {
            "success": True,
            "current": {
                "temperature": "72°F",
                "condition": "Partly Cloudy",
                "humidity": "45%",
                "wind": "8 mph"
            },
            "forecast": [
                {"day": "Today", "high": "75°F", "low": "62°F", "condition": "Partly Cloudy"},
                {"day": "Tomorrow", "high": "78°F", "low": "64°F", "condition": "Sunny"},
                {"day": "Day After", "high": "73°F", "low": "60°F", "condition": "Light Rain"}
            ],
            "recommendation": "Great weather for outdoor activities today!",
            "message": "Current temperature is 72°F with partly cloudy skies. Perfect for exploring the area!"
        }


def get_concierge_tools(db: AsyncSession) -> ConciergeTools:
    """Factory function to create ConciergeTools instance"""
    return ConciergeTools(db)
