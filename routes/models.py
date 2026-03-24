from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import User

class Trip(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='trips', null=True, blank=True)
    # Input fields
    current_location = models.CharField(max_length=255, help_text="Driver's current location")
    pickup_location = models.CharField(max_length=255, help_text="Pickup location")
    dropoff_location = models.CharField(max_length=255, help_text="Drop-off location")
    current_cycle_used = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(70)],
        help_text="Hours already used in current 8-day cycle (0-70)",
        default=0
    )
    
    # Calculated fields
    total_miles = models.FloatField(null=True, blank=True)
    total_duration_hours = models.FloatField(null=True, blank=True)
    total_driving_hours = models.FloatField(null=True, blank=True)
    total_duty_hours = models.FloatField(null=True, blank=True)
    total_rest_hours = models.FloatField(null=True, blank=True)
    cycle_hours_at_end = models.FloatField(null=True, blank=True)
    number_of_days = models.IntegerField(null=True, blank=True)
    
    # Store full calculation results as JSON
    route_data = models.JSONField(null=True, blank=True)
    events_data = models.JSONField(null=True, blank=True)
    daily_logs_data = models.JSONField(null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Trip'
        verbose_name_plural = 'Trips'
    
    def __str__(self):
        return f"Trip #{self.id}: {self.pickup_location} → {self.dropoff_location}"
    
    def save_calculation_results(self, route, events, daily_logs, summary):
        self.total_miles = route.get('total_miles')
        self.total_duration_hours = route.get('total_duration_hours')
        self.total_driving_hours = summary.get('total_driving_hours')
        self.total_duty_hours = summary.get('total_duty_hours')
        self.total_rest_hours = summary.get('total_rest_hours')
        self.cycle_hours_at_end = summary.get('cycle_hours_at_end')
        self.number_of_days = summary.get('total_days')
        self.route_data = route
        self.events_data = events
        self.daily_logs_data = daily_logs
        self.save()


class TripEvent(models.Model):
    EVENT_TYPES = (
        ('driving', 'Driving'),
        ('on_duty_not_driving', 'On Duty Not Driving'),
        ('off_duty', 'Off Duty'),
        ('sleeper_berth', 'Sleeper Berth'),
    )
    
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=30, choices=EVENT_TYPES)
    start_time = models.FloatField(help_text="Hours from trip start")
    duration = models.FloatField(help_text="Duration in hours")
    description = models.TextField()
    location = models.CharField(max_length=255, blank=True, default='')
    distance_at_event = models.FloatField(null=True, blank=True)
    
    class Meta:
        ordering = ['start_time']
    
    def __str__(self):
        return f"{self.event_type} at {self.start_time}h"


class DailyLog(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='daily_logs')
    day_number = models.IntegerField()
    date = models.DateField()
    total_miles = models.FloatField(default=0)
    
    # Totals (must add up to 24)
    off_duty_hours = models.FloatField(default=0)
    sleeper_berth_hours = models.FloatField(default=0)
    driving_hours = models.FloatField(default=0)
    on_duty_hours = models.FloatField(default=0)
    
    # Activities and remarks as JSON
    activities = models.JSONField(default=list)
    remarks = models.JSONField(default=list)
    
    class Meta:
        ordering = ['day_number']
        unique_together = ['trip', 'day_number']
    
    def __str__(self):
        return f"Day {self.day_number} - {self.date}"