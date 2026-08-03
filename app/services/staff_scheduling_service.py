"""
Advanced Staff Scheduling Service
Implements intelligent staff assignment algorithms for hotel operations
Uses workload balancing, skill matching, and real-time availability tracking
"""

import logging
from datetime import datetime, timedelta, time as time_type, date as date_type
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio

from sqlmodel import select, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import func

from app.models.staff import Staff, StaffSchedule, StaffAttendance, StaffPerformanceMetrics, StaffLeave
from app.models.guest_chat import StaffTask, StaffNotification
from app.models.user import User
from app.models.inventory import Room
from app.models.reservations import Booking

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    """Task priority levels with time constraints"""
    URGENT = ("urgent", 15)      # Must be addressed within 15 minutes
    HIGH = ("high", 30)          # Within 30 minutes
    NORMAL = ("normal", 60)      # Within 1 hour
    LOW = ("low", 120)           # Within 2 hours


class TaskType(Enum):
    """Task types with default estimated durations (in minutes)"""
    HOUSEKEEPING = ("housekeeping", 30, ["housekeeping"])
    MAINTENANCE = ("maintenance", 45, ["maintenance", "operations"])
    ROOM_SERVICE = ("room_service", 20, ["room_service", "front_desk"])
    CONCIERGE = ("concierge", 15, ["front_desk", "concierge"])
    LAUNDRY = ("laundry", 25, ["housekeeping", "laundry"])
    MINIBAR = ("minibar", 15, ["housekeeping", "room_service"])
    TURNDOWN = ("turndown", 20, ["housekeeping"])
    DEEP_CLEAN = ("deep_clean", 90, ["housekeeping"])
    REPAIR = ("repair", 60, ["maintenance", "operations"])
    OTHER = ("other", 30, ["front_desk", "operations"])


@dataclass
class StaffScore:
    """Staff scoring for task assignment"""
    staff_id: int
    user_id: int
    staff_name: str
    email: str
    department: str
    specialty: Optional[str]
    total_score: float
    workload_score: float  # Lower is better (less work)
    skill_score: float     # Higher is better
    availability_score: float  # Higher is better
    performance_score: float   # Higher is better
    proximity_score: float     # Higher is better (floor assignment)
    current_task_count: int
    is_available: bool


class StaffSchedulingService:
    """
    Advanced staff scheduling service with intelligent task assignment

    Features:
    - Workload balancing across staff
    - Skill-based matching
    - Real-time availability tracking
    - Floor/area-based proximity scoring
    - Performance-based prioritization
    - Shift validation
    - Leave checking
    """

    # Weights for scoring algorithm
    WORKLOAD_WEIGHT = 0.30      # 30% - Balance workload
    SKILL_WEIGHT = 0.25         # 25% - Match skills
    AVAILABILITY_WEIGHT = 0.20  # 20% - Current availability
    PERFORMANCE_WEIGHT = 0.15   # 15% - Historical performance
    PROXIMITY_WEIGHT = 0.10     # 10% - Floor proximity

    # Maximum concurrent tasks per staff member
    MAX_CONCURRENT_TASKS = 3

    # Default shift hours
    SHIFTS = {
        "morning": (time_type(6, 0), time_type(14, 0)),
        "afternoon": (time_type(14, 0), time_type(22, 0)),
        "evening": (time_type(18, 0), time_type(2, 0)),
        "night": (time_type(22, 0), time_type(6, 0)),
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_best_staff_for_task(
        self,
        task_type: str,
        priority: str,
        room_number: Optional[str] = None,
        required_skills: Optional[List[str]] = None,
        exclude_staff_ids: Optional[List[int]] = None
    ) -> Optional[StaffScore]:
        """
        Find the best available staff member for a task using multi-factor scoring

        Args:
            task_type: Type of task (housekeeping, maintenance, etc.)
            priority: Priority level (urgent, high, normal, low)
            room_number: Optional room number for proximity scoring
            required_skills: Optional list of required skills
            exclude_staff_ids: Staff IDs to exclude from consideration

        Returns:
            StaffScore object for the best candidate, or None if no one available
        """
        exclude_staff_ids = exclude_staff_ids or []

        # Get task configuration
        task_config = self._get_task_config(task_type)
        allowed_departments = task_config[2]

        # Get all potentially available staff
        candidates = await self._get_available_staff(allowed_departments, exclude_staff_ids)

        if not candidates:
            logger.warning(f"No available staff found for task type: {task_type}")
            return None

        # Score each candidate
        scored_candidates: List[StaffScore] = []

        for staff, user in candidates:
            score = await self._calculate_staff_score(
                staff=staff,
                user=user,
                task_type=task_type,
                priority=priority,
                room_number=room_number,
                required_skills=required_skills
            )
            if score.is_available:
                scored_candidates.append(score)

        if not scored_candidates:
            logger.warning(f"No available staff after scoring for task type: {task_type}")
            return None

        # Sort by total score (highest first)
        scored_candidates.sort(key=lambda x: x.total_score, reverse=True)

        best_candidate = scored_candidates[0]
        logger.info(
            f"Best staff for {task_type} task: {best_candidate.staff_name} "
            f"(score: {best_candidate.total_score:.2f})"
        )

        return best_candidate

    async def _get_available_staff(
        self,
        departments: List[str],
        exclude_staff_ids: List[int]
    ) -> List[Tuple[Staff, User]]:
        """Get staff members who could potentially handle the task"""
        now = datetime.utcnow()
        today = now.date()

        # Get active staff in relevant departments
        staff_query = select(Staff, User).join(
            User, Staff.user_id == User.id
        ).where(
            and_(
                Staff.status == "active",
                Staff.department.in_(departments),
                User.is_active == True,
                Staff.id.notin_(exclude_staff_ids) if exclude_staff_ids else True
            )
        )

        result = await self.db.exec(staff_query)
        staff_users = result.all()

        # Filter out staff on leave
        available_staff = []
        for staff, user in staff_users:
            # Check if on leave today
            leave_query = select(StaffLeave).where(
                and_(
                    StaffLeave.staff_id == staff.id,
                    StaffLeave.status == "approved",
                    StaffLeave.start_date <= today,
                    StaffLeave.end_date >= today
                )
            )
            leave_result = await self.db.exec(leave_query)
            on_leave = leave_result.first()

            if not on_leave:
                available_staff.append((staff, user))

        return available_staff

    async def _calculate_staff_score(
        self,
        staff: Staff,
        user: User,
        task_type: str,
        priority: str,
        room_number: Optional[str],
        required_skills: Optional[List[str]]
    ) -> StaffScore:
        """Calculate comprehensive score for a staff member"""
        now = datetime.utcnow()

        # 1. Workload Score (inverse - lower workload = higher score)
        workload_score = await self._calculate_workload_score(staff.id, user.id)

        # 2. Skill Score
        skill_score = self._calculate_skill_score(
            staff_specialty=staff.specialty,
            staff_skills=staff.skills,
            task_type=task_type,
            required_skills=required_skills
        )

        # 3. Availability Score (is currently working shift)
        availability_score, is_available = await self._calculate_availability_score(
            staff=staff,
            user_id=user.id,
            now=now
        )

        # 4. Performance Score
        performance_score = await self._calculate_performance_score(staff.id)

        # 5. Proximity Score (floor assignment match)
        proximity_score = self._calculate_proximity_score(
            floor_assignment=staff.floor_assignment,
            room_number=room_number
        )

        # Get current task count
        current_task_count = await self._get_current_task_count(user.id)

        # Check if staff can take more tasks
        if current_task_count >= self.MAX_CONCURRENT_TASKS:
            is_available = False

        # Calculate weighted total score
        total_score = (
            workload_score * self.WORKLOAD_WEIGHT +
            skill_score * self.SKILL_WEIGHT +
            availability_score * self.AVAILABILITY_WEIGHT +
            performance_score * self.PERFORMANCE_WEIGHT +
            proximity_score * self.PROXIMITY_WEIGHT
        )

        # Priority boost for urgent tasks - prefer less loaded staff
        if priority == "urgent" and workload_score > 0.7:
            total_score *= 1.2  # 20% boost for available staff on urgent tasks

        return StaffScore(
            staff_id=staff.id,
            user_id=user.id,
            staff_name=staff.name,
            email=staff.email,
            department=staff.department,
            specialty=staff.specialty,
            total_score=total_score,
            workload_score=workload_score,
            skill_score=skill_score,
            availability_score=availability_score,
            performance_score=performance_score,
            proximity_score=proximity_score,
            current_task_count=current_task_count,
            is_available=is_available
        )

    async def _calculate_workload_score(self, staff_id: int, user_id: int) -> float:
        """
        Calculate workload score (0-1, higher = less workload = better)
        Based on current active tasks
        """
        # Count active tasks
        active_tasks_query = select(func.count(StaffTask.id)).where(
            and_(
                StaffTask.assigned_to == user_id,
                StaffTask.status.in_(["assigned", "in_progress"])
            )
        )
        result = await self.db.exec(active_tasks_query)
        active_count = result.one() or 0

        # Score based on task count
        # 0 tasks = 1.0, 1 task = 0.8, 2 tasks = 0.5, 3+ tasks = 0.1
        if active_count == 0:
            return 1.0
        elif active_count == 1:
            return 0.8
        elif active_count == 2:
            return 0.5
        else:
            return 0.1

    def _calculate_skill_score(
        self,
        staff_specialty: Optional[str],
        staff_skills: Optional[str],
        task_type: str,
        required_skills: Optional[List[str]]
    ) -> float:
        """Calculate skill match score (0-1, higher = better match)"""
        score = 0.5  # Base score

        # Parse skills JSON if exists
        import json
        skills_list = []
        if staff_skills:
            try:
                skills_list = json.loads(staff_skills) if isinstance(staff_skills, str) else staff_skills
            except:
                skills_list = []

        # Task type to skill mapping
        skill_mapping = {
            "housekeeping": ["cleaning", "housekeeping", "sanitization", "laundry"],
            "maintenance": ["electrical", "plumbing", "hvac", "carpentry", "repair"],
            "room_service": ["food_service", "customer_service"],
            "concierge": ["customer_service", "hospitality", "languages"],
            "turndown": ["housekeeping", "turndown"],
            "deep_clean": ["deep_cleaning", "housekeeping", "sanitization"],
        }

        # Check specialty match
        if staff_specialty:
            if task_type in staff_specialty.lower():
                score += 0.25

        # Check required skills
        if required_skills and skills_list:
            matching_skills = set(skills_list) & set(required_skills)
            if matching_skills:
                score += 0.25 * (len(matching_skills) / len(required_skills))

        # Check task type skill match
        relevant_skills = skill_mapping.get(task_type, [])
        if skills_list and relevant_skills:
            matching = set(skills_list) & set(relevant_skills)
            if matching:
                score += 0.25 * (len(matching) / len(relevant_skills))

        return min(score, 1.0)  # Cap at 1.0

    async def _calculate_availability_score(
        self,
        staff: Staff,
        user_id: int,
        now: datetime
    ) -> Tuple[float, bool]:
        """
        Calculate availability score and check if currently on shift
        Returns: (score, is_available)
        """
        current_time = now.time()
        today = now.date()

        # Check if clocked in
        if staff.clocked_in:
            return (1.0, True)

        # Check scheduled shift for today
        schedule_query = select(StaffSchedule).where(
            and_(
                StaffSchedule.staff_id == staff.id,
                StaffSchedule.schedule_date == today,
                StaffSchedule.status.in_(["scheduled", "confirmed"])
            )
        )
        result = await self.db.exec(schedule_query)
        today_schedule = result.first()

        if today_schedule:
            # Check if current time is within shift
            shift_start = today_schedule.start_time
            shift_end = today_schedule.end_time

            # Handle overnight shifts
            if shift_end < shift_start:
                is_during_shift = current_time >= shift_start or current_time <= shift_end
            else:
                is_during_shift = shift_start <= current_time <= shift_end

            if is_during_shift:
                return (0.9, True)  # Scheduled but not clocked in
            else:
                return (0.2, False)  # Not on shift

        # Check default shift times from staff record
        if staff.shift_start and staff.shift_end:
            shift_start = staff.shift_start
            shift_end = staff.shift_end

            if shift_end < shift_start:
                is_during_shift = current_time >= shift_start or current_time <= shift_end
            else:
                is_during_shift = shift_start <= current_time <= shift_end

            if is_during_shift:
                return (0.7, True)
            else:
                return (0.2, False)

        # Default: assume available during standard hours (6 AM - 10 PM)
        if time_type(6, 0) <= current_time <= time_type(22, 0):
            return (0.5, True)

        return (0.1, False)

    async def _calculate_performance_score(self, staff_id: int) -> float:
        """Calculate performance score based on historical metrics (0-1)"""
        # Get last 30 days of performance metrics
        thirty_days_ago = datetime.utcnow().date() - timedelta(days=30)

        metrics_query = select(StaffPerformanceMetrics).where(
            and_(
                StaffPerformanceMetrics.staff_id == staff_id,
                StaffPerformanceMetrics.date >= thirty_days_ago
            )
        )
        result = await self.db.exec(metrics_query)
        metrics = result.all()

        if not metrics:
            return 0.5  # Default score for new staff

        # Calculate average scores
        total_efficiency = 0.0
        total_quality = 0.0
        total_on_time_rate = 0.0
        valid_metrics = 0

        for m in metrics:
            if m.efficiency_score:
                total_efficiency += m.efficiency_score
            if m.quality_score:
                total_quality += m.quality_score / 5.0  # Normalize to 0-1
            if m.tasks_completed and m.tasks_completed > 0:
                on_time_rate = m.tasks_completed_on_time / m.tasks_completed
                total_on_time_rate += on_time_rate
            valid_metrics += 1

        if valid_metrics == 0:
            return 0.5

        # Weighted average of performance factors
        avg_efficiency = total_efficiency / valid_metrics if total_efficiency else 0.5
        avg_quality = total_quality / valid_metrics if total_quality else 0.5
        avg_on_time = total_on_time_rate / valid_metrics if total_on_time_rate else 0.5

        # Combined score (equal weights)
        performance_score = (avg_efficiency + avg_quality + avg_on_time) / 3

        return min(max(performance_score, 0.0), 1.0)

    def _calculate_proximity_score(
        self,
        floor_assignment: Optional[str],
        room_number: Optional[str]
    ) -> float:
        """Calculate proximity score based on floor assignment (0-1)"""
        if not room_number or not floor_assignment:
            return 0.5  # Default score

        # Extract floor from room number (first digit for 3-digit rooms)
        try:
            room_floor = int(room_number[0]) if len(room_number) >= 3 else 1
        except ValueError:
            return 0.5

        # Parse floor assignment JSON
        import json
        try:
            floors = json.loads(floor_assignment) if isinstance(floor_assignment, str) else floor_assignment
            if isinstance(floors, list):
                if room_floor in floors:
                    return 1.0  # Exact floor match
                # Check for adjacent floors
                for f in floors:
                    if abs(f - room_floor) == 1:
                        return 0.7  # Adjacent floor
                return 0.3  # Different floor
        except:
            pass

        return 0.5

    async def _get_current_task_count(self, user_id: int) -> int:
        """Get count of currently active tasks for a staff member"""
        query = select(func.count(StaffTask.id)).where(
            and_(
                StaffTask.assigned_to == user_id,
                StaffTask.status.in_(["assigned", "in_progress"])
            )
        )
        result = await self.db.exec(query)
        return result.one() or 0

    def _get_task_config(self, task_type: str) -> Tuple[str, int, List[str]]:
        """Get task configuration (name, default_duration, allowed_departments)"""
        task_configs = {
            "housekeeping": ("housekeeping", 30, ["housekeeping"]),
            "maintenance": ("maintenance", 45, ["maintenance", "operations"]),
            "room_service": ("room_service", 20, ["room_service", "front_desk"]),
            "concierge": ("concierge", 15, ["front_desk", "concierge"]),
            "laundry": ("laundry", 25, ["housekeeping", "laundry"]),
            "minibar": ("minibar", 15, ["housekeeping", "room_service"]),
            "turndown": ("turndown", 20, ["housekeeping"]),
            "deep_clean": ("deep_clean", 90, ["housekeeping"]),
            "repair": ("repair", 60, ["maintenance", "operations"]),
            "other": ("other", 30, ["front_desk", "operations", "housekeeping"]),
        }
        return task_configs.get(task_type, task_configs["other"])

    async def create_and_assign_task(
        self,
        task_type: str,
        title: str,
        description: str,
        priority: str = "normal",
        room_number: Optional[str] = None,
        room_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        guest_id: Optional[int] = None,
        conversation_id: Optional[str] = None,
        required_skills: Optional[List[str]] = None
    ) -> Tuple[Optional[StaffTask], Optional[StaffScore]]:
        """
        Create a staff task and intelligently assign it to the best available staff

        Returns:
            Tuple of (StaffTask, StaffScore) or (None, None) if creation fails
        """
        # Find best staff for the task
        best_staff = await self.find_best_staff_for_task(
            task_type=task_type,
            priority=priority,
            room_number=room_number,
            required_skills=required_skills
        )

        # Get task duration estimate
        task_config = self._get_task_config(task_type)
        estimated_duration = task_config[1]

        # Adjust scheduling based on priority
        priority_delays = {
            "urgent": timedelta(minutes=0),
            "high": timedelta(minutes=5),
            "normal": timedelta(minutes=15),
            "low": timedelta(minutes=30)
        }
        scheduled_for = datetime.utcnow() + priority_delays.get(priority, timedelta(minutes=15))

        # Create the task
        task = StaffTask(
            task_type=task_type,
            title=title,
            description=description,
            room_number=room_number,
            room_id=room_id,
            booking_id=booking_id,
            guest_id=guest_id,
            conversation_id=conversation_id,
            priority=priority,
            status="assigned" if best_staff else "pending",
            assigned_to=best_staff.user_id if best_staff else None,
            scheduled_for=scheduled_for,
            estimated_duration=estimated_duration
        )

        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)

        # Store task_id before any further commits (to avoid lazy load issues)
        task_id = task.id

        # Create notification if assigned
        if best_staff:
            notification = StaffNotification(
                staff_id=best_staff.user_id,
                task_id=task_id,
                notification_type="task_assigned",
                title=f"New {task_type.replace('_', ' ').title()} Task",
                message=f"{title} - Priority: {priority.upper()}" + (f" - Room {room_number}" if room_number else "")
            )
            self.db.add(notification)
            await self.db.commit()
            await self.db.refresh(task)  # Refresh task after all commits

            logger.info(
                f"Task {task_id} created and assigned to {best_staff.staff_name} "
                f"(user_id: {best_staff.user_id})"
            )
        else:
            logger.warning(f"Task {task_id} created but no staff available for assignment")

        return task, best_staff

    async def reassign_task(
        self,
        task_id: int,
        exclude_current: bool = True
    ) -> Tuple[bool, Optional[StaffScore]]:
        """
        Reassign a task to a different staff member

        Args:
            task_id: ID of the task to reassign
            exclude_current: Whether to exclude the currently assigned staff

        Returns:
            Tuple of (success, new_staff_score)
        """
        # Get the task
        result = await self.db.exec(
            select(StaffTask).where(StaffTask.id == task_id)
        )
        task = result.first()

        if not task:
            logger.error(f"Task {task_id} not found for reassignment")
            return False, None

        # Build exclusion list
        exclude_ids = []
        if exclude_current and task.assigned_to:
            exclude_ids.append(task.assigned_to)

        # Find new staff
        new_staff = await self.find_best_staff_for_task(
            task_type=task.task_type,
            priority=task.priority,
            room_number=task.room_number,
            exclude_staff_ids=exclude_ids
        )

        if not new_staff:
            return False, None

        # Update task assignment
        old_assigned_to = task.assigned_to
        task.assigned_to = new_staff.user_id
        task.status = "assigned"
        task.updated_at = datetime.utcnow()

        # Create notification for new staff
        notification = StaffNotification(
            staff_id=new_staff.user_id,
            task_id=task.id,
            notification_type="task_assigned",
            title=f"Task Reassigned: {task.task_type.replace('_', ' ').title()}",
            message=f"{task.title} - Priority: {task.priority.upper()}"
        )
        self.db.add(notification)

        await self.db.commit()

        logger.info(
            f"Task {task_id} reassigned from user {old_assigned_to} "
            f"to {new_staff.staff_name} (user_id: {new_staff.user_id})"
        )

        return True, new_staff

    async def get_staff_workload_summary(self, department: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get workload summary for all active staff"""
        # Query active staff
        staff_query = select(Staff, User).join(
            User, Staff.user_id == User.id
        ).where(
            and_(
                Staff.status == "active",
                User.is_active == True
            )
        )

        if department:
            staff_query = staff_query.where(Staff.department == department)

        result = await self.db.exec(staff_query)
        staff_list = result.all()

        summaries = []
        for staff, user in staff_list:
            task_count = await self._get_current_task_count(user.id)

            # Get today's completed tasks
            today = datetime.utcnow().date()
            completed_query = select(func.count(StaffTask.id)).where(
                and_(
                    StaffTask.assigned_to == user.id,
                    StaffTask.status == "completed",
                    func.date(StaffTask.completed_at) == today
                )
            )
            completed_result = await self.db.exec(completed_query)
            completed_today = completed_result.one() or 0

            summaries.append({
                "staff_id": staff.id,
                "user_id": user.id,
                "name": staff.name,
                "department": staff.department,
                "specialty": staff.specialty,
                "clocked_in": staff.clocked_in,
                "active_tasks": task_count,
                "completed_today": completed_today,
                "availability": "available" if task_count < self.MAX_CONCURRENT_TASKS else "busy"
            })

        return summaries



    async def get_available_staff(
        self,
        department: Optional[str] = None,
        shift_type: Optional[str] = None
    ) -> List[Staff]:
        """Public method to get available staff with optional filters"""
        # Determine departments to filter
        if department:
            departments = [department]
        else:
            departments = ["housekeeping", "maintenance", "runner", "front_desk", "general"]

        # Get available staff using private method
        available_tuples = await self._get_available_staff(
            departments=departments,
            exclude_staff_ids=[]
        )

        # Extract just the Staff objects and add task count
        available_staff = []
        for staff, user in available_tuples:
            # Get current task count
            task_count = await self._get_current_task_count(user.id)
            staff.current_task_count = task_count

            # Filter by max concurrent tasks
            if task_count < self.MAX_CONCURRENT_TASKS:
                available_staff.append(staff)

        return available_staff

# Helper function to get the service
def get_scheduling_service(db: AsyncSession) -> StaffSchedulingService:
    """Factory function to create scheduling service instance"""
    return StaffSchedulingService(db)
