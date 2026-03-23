"""
room_search.py — FM Residences
Availability search using the new RoomAvailability model.

Replaces the old booking_engine-based version entirely.
Preserves the room_option dict structure that offer_rooms.html expects.
"""

from datetime import date
from src.models import Room, RoomAvailability


def search_available_rooms(
    checkin:         date,
    checkout:        date,
    rooms_requested: int,
    adults:          int,
    total_children:  int,
    first_child:     str,
    second_child:    str,
    total_days:      int,
    total_guests:    int,
) -> list[dict]:
    """
    Find all room types that:
      1. Are active
      2. Can fit the requested guests (capacity check)
      3. Have >= rooms_requested available on EVERY night of the stay

    Returns a list of room_option dicts ready for offer_rooms.html.
    """
    results = []

    active_rooms = Room.query.filter_by(is_active=True).all()

    for room in active_rooms:

        # ── Capacity check ────────────────────────────────────────────────────
        # Total guests must not exceed max_guests per room × rooms_requested
        if total_guests > room.max_guests * rooms_requested:
            continue
        if adults > room.max_adults * rooms_requested:
            continue
        if total_children > room.max_children * rooms_requested:
            continue

        # ── Date-range availability check ─────────────────────────────────────
        # Every night from checkin up to (but not including) checkout must
        # have left_to_sell >= rooms_requested
        nights_needed = total_days
        avail_rows = (
            RoomAvailability.query
            .filter(
                RoomAvailability.room_id    == room.id,
                RoomAvailability.date       >= checkin,
                RoomAvailability.date       <  checkout,
                RoomAvailability.left_to_sell >= rooms_requested,
            )
            .all()
        )

        if len(avail_rows) < nights_needed:
            # At least one night doesn't have enough rooms
            continue

        # ── Pricing ───────────────────────────────────────────────────────────
        price_per_night = _calculate_nightly_price(
            room           = room,
            adults         = adults,
            total_children = total_children,
            first_child    = first_child,
            second_child   = second_child,
            rooms_requested= rooms_requested,
        )

        price_all_rooms_per_night = price_per_night * rooms_requested
        total_price               = price_all_rooms_per_night * total_days

        results.append({
            "room_id":        room.id,
            "room_type":      room.room_type,
            "room_quantity":  rooms_requested,
            "from_date":      checkin,
            "to_date":        checkout,
            "max_guests":     room.max_guests,
            "total_days":     total_days,
            "total_guests":   total_guests,
            "total_adults":   adults,
            "total_children": total_children,
            "children_age":   (first_child, second_child) if total_children == 2 else first_child,
            "price_per_day":  round(price_per_night, 2),
            "price_room_stay": round(price_all_rooms_per_night, 2),
            "total_price":    round(total_price, 2),
            "room_image":     room.room_image,
            "room_info":      room.description,
        })

    return results


def _calculate_nightly_price(
    room:            Room,
    adults:          int,
    total_children:  int,
    first_child:     str,
    second_child:    str,
    rooms_requested: int,
) -> float:
    """
    Calculate per-room nightly price based on guest composition.

    Pricing logic (uses room.price_per_night as the base adult rate):
      - Adults:   price_per_night per person, but solo occupancy gets 80%
      - Children:
          0-2   →  free
          2-6   →  30% of adult rate
          7-12  →  50% of adult rate

    This is a straightforward calculation. Swap in RatePlan queries here
    if you re-add the RatePlan model later.
    """
    base     = room.price_per_night
    per_room = adults / max(rooms_requested, 1)

    # Single adult discount
    if adults == 1 and total_children == 0:
        adults_cost = base * 0.8
    elif per_room < room.min_guests:
        # Fewer adults than min occupancy — charge minimum rate
        adults_cost = base * room.min_guests
    else:
        adults_cost = base * per_room

    # Children surcharges (per extra bed)
    CHILD_RATES = {
        "0-2":  0.00,
        "2-6":  0.30,
        "7-12": 0.50,
    }

    children_cost = 0.0
    if total_children >= 1 and first_child:
        children_cost += base * CHILD_RATES.get(first_child, 0.0)
    if total_children == 2 and second_child:
        children_cost += base * CHILD_RATES.get(second_child, 0.0)

    return adults_cost + children_cost