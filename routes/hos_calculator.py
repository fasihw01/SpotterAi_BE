import math
from typing import List, Dict, Tuple

class HOSCalculator:
    """
    Hours of Service Calculator for Property-Carrying CMV Drivers
    
    Rules (70hrs/8days, no adverse conditions):
    ─────────────────────────────────────────────
    ✅ 11-hour driving limit per shift
    ✅ 14-hour duty window per shift  
    ✅ 30-min break after 8 cumulative driving hours
    ✅ 10 consecutive hours off-duty between shifts
    ✅ 70-hour/8-day cycle limit
    ✅ 34-hour restart when cycle exhausted
    ✅ Fueling every 1,000 miles
    ✅ 1 hour pickup, 1 hour dropoff
    """
    
    MAX_DRIVING = 11
    MAX_DUTY_WINDOW = 14
    BREAK_AFTER_DRIVING = 8
    BREAK_DURATION = 0.5
    REQUIRED_REST = 10
    MAX_CYCLE = 70
    RESTART_HOURS = 34
    FUEL_INTERVAL = 1000
    FUEL_DURATION = 0.5
    PICKUP_DURATION = 1.0
    DROPOFF_DURATION = 1.0
    PRE_TRIP_DURATION = 0.25
    POST_TRIP_DURATION = 0.25
    START_HOUR = 8  # Trip starts at 8 AM

    def __init__(self, current_cycle_used: float):
        self.initial_cycle = min(current_cycle_used, self.MAX_CYCLE)

    def calculate_trip(
        self,
        leg1_miles: float, leg1_hours: float,
        leg2_miles: float, leg2_hours: float,
        current_loc: str, pickup_loc: str, dropoff_loc: str
    ) -> Dict:
        events = []
        
        # State
        clock = self.START_HOUR
        shift_start = clock
        shift_driving = 0.0
        driving_since_break = 0.0
        cycle_hours = self.initial_cycle
        total_distance = 0.0
        last_fuel_distance = 0.0

        # ── 34-HOUR RESTART IF NEEDED ──
        if cycle_hours >= self.MAX_CYCLE:
            events.append(self._evt(
                'sleeper_berth', clock, self.RESTART_HOURS,
                '34-hour restart (70-hour cycle limit reached)',
                current_loc, total_distance
            ))
            clock += self.RESTART_HOURS
            cycle_hours = 0
            shift_start = clock
        
        # ── PRE-TRIP INSPECTION ──
        events.append(self._evt(
            'on_duty_not_driving', clock, self.PRE_TRIP_DURATION,
            'Pre-trip inspection', current_loc, total_distance
        ))
        clock += self.PRE_TRIP_DURATION
        cycle_hours += self.PRE_TRIP_DURATION

        # ── DRIVE LEG 1: Current → Pickup ──
        if leg1_miles > 0.5:
            speed1 = leg1_miles / leg1_hours if leg1_hours > 0 else 55
            clock, shift_start, shift_driving, driving_since_break, \
                cycle_hours, total_distance, last_fuel_distance = \
                self._drive(events, clock, shift_start, shift_driving,
                           driving_since_break, cycle_hours, total_distance,
                           last_fuel_distance, leg1_miles, speed1,
                           current_loc, pickup_loc)

        # ── PICKUP ──
        clock, shift_start, shift_driving, driving_since_break, cycle_hours = \
            self._do_on_duty(events, clock, shift_start, shift_driving,
                            driving_since_break, cycle_hours, total_distance,
                            self.PICKUP_DURATION, 'Pickup / Loading', pickup_loc)

        # ── DRIVE LEG 2: Pickup → Dropoff ──
        if leg2_miles > 0.5:
            speed2 = leg2_miles / leg2_hours if leg2_hours > 0 else 55
            clock, shift_start, shift_driving, driving_since_break, \
                cycle_hours, total_distance, last_fuel_distance = \
                self._drive(events, clock, shift_start, shift_driving,
                           driving_since_break, cycle_hours, total_distance,
                           last_fuel_distance, leg2_miles, speed2,
                           pickup_loc, dropoff_loc)

        # ── DROPOFF ──
        clock, shift_start, shift_driving, driving_since_break, cycle_hours = \
            self._do_on_duty(events, clock, shift_start, shift_driving,
                            driving_since_break, cycle_hours, total_distance,
                            self.DROPOFF_DURATION, 'Dropoff / Unloading', dropoff_loc)

        # ── POST-TRIP INSPECTION ──
        events.append(self._evt(
            'on_duty_not_driving', clock, self.POST_TRIP_DURATION,
            'Post-trip inspection', dropoff_loc, total_distance
        ))
        clock += self.POST_TRIP_DURATION
        cycle_hours += self.POST_TRIP_DURATION

        return {
            'events': events,
            'total_distance': round(total_distance, 1),
            'final_cycle_hours': round(cycle_hours, 2)
        }

    def _do_on_duty(self, events, clock, shift_start, shift_driving,
                    driving_since_break, cycle_hours, distance,
                    duration, description, location):
        """Handle on-duty not driving activity with limit checks"""
        
        # Need rest if 14-hr window exceeded?
        if (clock - shift_start) + duration > self.MAX_DUTY_WINDOW:
            clock, shift_start, shift_driving, driving_since_break = \
                self._rest(events, clock, location, distance)
        
        # Need restart if cycle exceeded?
        if cycle_hours + duration > self.MAX_CYCLE:
            clock, cycle_hours, shift_start, shift_driving, driving_since_break = \
                self._restart(events, clock, location, distance)
        
        events.append(self._evt(
            'on_duty_not_driving', clock, duration,
            description, location, distance
        ))
        clock += duration
        cycle_hours += duration
        
        # On-duty not driving >= 30 min resets break counter
        if duration >= self.BREAK_DURATION:
            driving_since_break = 0
        
        return clock, shift_start, shift_driving, driving_since_break, cycle_hours

    def _drive(self, events, clock, shift_start, shift_driving,
               driving_since_break, cycle_hours, total_distance,
               last_fuel_distance, segment_miles, avg_speed,
               from_loc, to_loc):
        """Drive a segment with all HOS stops"""
        
        remaining = segment_miles
        
        while remaining > 0.5:
            # ── CHECK CYCLE ──
            if cycle_hours >= self.MAX_CYCLE:
                loc = self._loc(from_loc, to_loc, segment_miles, remaining)
                clock, cycle_hours, shift_start, shift_driving, driving_since_break = \
                    self._restart(events, clock, loc, total_distance)

            # ── CHECK 14-HR WINDOW / 11-HR DRIVING ──
            shift_elapsed = clock - shift_start
            if shift_elapsed >= self.MAX_DUTY_WINDOW or shift_driving >= self.MAX_DRIVING:
                loc = self._loc(from_loc, to_loc, segment_miles, remaining)
                clock, shift_start, shift_driving, driving_since_break = \
                    self._rest(events, clock, loc, total_distance)

            # ── CHECK 30-MIN BREAK ──
            if driving_since_break >= self.BREAK_AFTER_DRIVING:
                shift_elapsed = clock - shift_start
                loc = self._loc(from_loc, to_loc, segment_miles, remaining)
                
                if (shift_elapsed + self.BREAK_DURATION < self.MAX_DUTY_WINDOW
                    and shift_driving < self.MAX_DRIVING):
                    events.append(self._evt(
                        'off_duty', clock, self.BREAK_DURATION,
                        '30-minute break (8-hr driving limit)',
                        loc, total_distance
                    ))
                    clock += self.BREAK_DURATION
                    driving_since_break = 0
                else:
                    clock, shift_start, shift_driving, driving_since_break = \
                        self._rest(events, clock, loc, total_distance)

            # ── CHECK FUEL ──
            if total_distance - last_fuel_distance >= self.FUEL_INTERVAL:
                loc = self._loc(from_loc, to_loc, segment_miles, remaining)
                shift_elapsed = clock - shift_start
                
                if shift_elapsed + self.FUEL_DURATION > self.MAX_DUTY_WINDOW:
                    clock, shift_start, shift_driving, driving_since_break = \
                        self._rest(events, clock, loc, total_distance)
                
                events.append(self._evt(
                    'on_duty_not_driving', clock, self.FUEL_DURATION,
                    'Fueling stop', loc, total_distance
                ))
                clock += self.FUEL_DURATION
                cycle_hours += self.FUEL_DURATION
                last_fuel_distance = total_distance
                driving_since_break = 0

            # ── CALCULATE DRIVE TIME ──
            shift_elapsed = clock - shift_start
            
            t_break = max(0.01, self.BREAK_AFTER_DRIVING - driving_since_break)
            t_11 = max(0.01, self.MAX_DRIVING - shift_driving)
            t_14 = max(0.01, self.MAX_DUTY_WINDOW - shift_elapsed)
            t_cycle = max(0.01, self.MAX_CYCLE - cycle_hours)
            t_fuel = max(0.01, (self.FUEL_INTERVAL - (total_distance - last_fuel_distance)) / avg_speed) \
                     if avg_speed > 0 else 999
            t_finish = remaining / avg_speed if avg_speed > 0 else 0

            can_drive = min(t_break, t_11, t_14, t_cycle, t_fuel, t_finish)
            can_drive = max(0.01, can_drive)

            drive_miles = min(can_drive * avg_speed, remaining)
            drive_time = drive_miles / avg_speed if avg_speed > 0 else 0

            if drive_time < 0.01:
                break

            drive_time = round(drive_time, 2)
            drive_miles = round(drive_miles, 1)

            loc = self._loc(from_loc, to_loc, segment_miles, remaining)
            events.append(self._evt(
                'driving', clock, drive_time,
                f'Driving {drive_miles} miles', loc, total_distance, drive_miles
            ))

            clock += drive_time
            shift_driving += drive_time
            driving_since_break += drive_time
            cycle_hours += drive_time
            total_distance += drive_miles
            remaining -= drive_miles

            if remaining < 0.5:
                remaining = 0
                break

        return clock, shift_start, shift_driving, driving_since_break, \
               cycle_hours, total_distance, last_fuel_distance

    def _rest(self, events, clock, location, distance):
        """10-hour rest period"""
        events.append(self._evt(
            'sleeper_berth', clock, self.REQUIRED_REST,
            '10-hour rest period', location, distance
        ))
        clock += self.REQUIRED_REST
        return clock, clock, 0.0, 0.0  # clock, shift_start, shift_driving, driving_since_break

    def _restart(self, events, clock, location, distance):
        """34-hour restart"""
        events.append(self._evt(
            'sleeper_berth', clock, self.RESTART_HOURS,
            '34-hour restart (70-hour cycle limit)',
            location, distance
        ))
        clock += self.RESTART_HOURS
        return clock, 0.0, clock, 0.0, 0.0  # clock, cycle, shift_start, shift_driving, break

    def _loc(self, from_loc, to_loc, total, remaining):
        """Get approximate location"""
        if total <= 0:
            return from_loc
        progress = (total - remaining) / total
        if progress < 0.1:
            return f"Near {from_loc}"
        elif progress > 0.9:
            return f"Near {to_loc}"
        else:
            return f"En route ({int(progress*100)}% {from_loc} → {to_loc})"

    def _evt(self, status, clock, duration, desc, location, distance, miles=None):
        """Create event dict"""
        e = {
            'status': status,
            'clock': round(clock, 2),
            'duration': round(duration, 2),
            'description': desc,
            'location': location,
            'distance': round(distance, 1)
        }
        if miles is not None:
            e['miles'] = round(miles, 1)
        return e