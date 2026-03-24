from django.contrib import admin
from django.contrib import messages
from .models import Trip, TripEvent, DailyLog
from .hos_calculator import HOSCalculator
from .route_service import RouteService
from datetime import datetime
from django.utils.safestring import mark_safe
import json


class TripEventInline(admin.TabularInline):
    model = TripEvent
    extra = 0
    readonly_fields = ['event_type', 'start_time', 'duration', 'description', 'location']
    can_delete = False
    def has_add_permission(self, request, obj=None):
        return False


class DailyLogInline(admin.TabularInline):
    model = DailyLog
    extra = 0
    readonly_fields = [
        'day_number', 'date', 'total_miles',
        'driving_hours', 'on_duty_hours',
        'sleeper_berth_hours', 'off_duty_hours'
    ]
    can_delete = False
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'trip_route', 'total_miles_display',
        'days_display', 'status_display', 'created_at'
    ]
    list_filter = ['created_at', 'number_of_days']
    search_fields = ['current_location', 'pickup_location', 'dropoff_location']
    ordering = ['-created_at']
    readonly_fields = [
        'created_at', 'updated_at', 'total_miles',
        'total_duration_hours', 'total_driving_hours',
        'total_duty_hours', 'number_of_days',
        'route_data_display', 'events_summary'
    ]
    actions = ['calculate_selected_trips']
    inlines = [TripEventInline, DailyLogInline]
    
    fieldsets = (
        ('Trip Input', {
            'fields': ('current_location', 'pickup_location',
                       'dropoff_location', 'current_cycle_used')
        }),
        ('Calculated Results', {
            'fields': ('total_miles', 'total_duration_hours',
                       'total_driving_hours', 'total_duty_hours', 'number_of_days'),
            'classes': ('collapse',)
        }),
        ('Detailed Data', {
            'fields': ('route_data_display', 'events_summary'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def trip_route(self, obj):
        return f"{obj.pickup_location} → {obj.dropoff_location}"
    trip_route.short_description = "Route"

    def total_miles_display(self, obj):
        return f"{obj.total_miles:.1f} mi" if obj.total_miles else "-"
    total_miles_display.short_description = "Distance"

    def days_display(self, obj):
        return f"{obj.number_of_days} days" if obj.number_of_days else "-"
    days_display.short_description = "Duration"

    def status_display(self, obj):
        if obj.total_miles:
            return mark_safe('<span style="color:green;font-weight:bold;">✓ Calculated</span>')
        return mark_safe('<span style="color:orange;">⚠ Pending</span>')
    status_display.short_description = "Status"

    def route_data_display(self, obj):
        if obj.route_data:
            # Show without coordinates (too long)
            display_data = {
                'total_miles': obj.route_data.get('total_miles'),
                'total_duration_hours': obj.route_data.get('total_duration_hours'),
                'legs': [
                    {'from': l.get('from'), 'to': l.get('to'), 
                     'distance_miles': l.get('distance_miles')}
                    for l in obj.route_data.get('legs', [])
                ]
            }
            formatted = json.dumps(display_data, indent=2)
            return mark_safe(f'<pre style="background:#f4f4f4;padding:10px;border-radius:5px;">{formatted}</pre>')
        return "-"
    route_data_display.short_description = "Route Data"

    def events_summary(self, obj):
        if obj.events_data:
            counts = {}
            hours = {}
            for e in obj.events_data:
                s = e.get('status', 'unknown')
                counts[s] = counts.get(s, 0) + 1
                hours[s] = hours.get(s, 0) + e.get('duration', 0)
            
            html = "<table style='border-collapse:collapse;'>"
            html += "<tr><th style='padding:4px 8px;border:1px solid #ccc;'>Status</th>"
            html += "<th style='padding:4px 8px;border:1px solid #ccc;'>Count</th>"
            html += "<th style='padding:4px 8px;border:1px solid #ccc;'>Hours</th></tr>"
            for s in counts:
                label = s.replace('_', ' ').title()
                html += f"<tr><td style='padding:4px 8px;border:1px solid #ccc;'>{label}</td>"
                html += f"<td style='padding:4px 8px;border:1px solid #ccc;text-align:center;'>{counts[s]}</td>"
                html += f"<td style='padding:4px 8px;border:1px solid #ccc;text-align:right;'>{hours[s]:.2f}</td></tr>"
            html += "</table>"
            return mark_safe(html)
        return "-"
    events_summary.short_description = "Events Summary"

    @admin.action(description='Calculate selected trips')
    def calculate_selected_trips(self, request, queryset):
        success = 0
        for trip in queryset:
            try:
                self._calc(trip)
                success += 1
            except Exception as e:
                self.message_user(request, f"Trip #{trip.id}: {e}", level=messages.ERROR)
        if success:
            self.message_user(request, f"Calculated {success} trip(s).", level=messages.SUCCESS)

    def _calc(self, trip):
        current_coords = RouteService.geocode(trip.current_location)
        pickup_coords = RouteService.geocode(trip.pickup_location)
        dropoff_coords = RouteService.geocode(trip.dropoff_location)
        
        leg1 = RouteService.get_route(current_coords, pickup_coords)
        leg2 = RouteService.get_route(pickup_coords, dropoff_coords)
        
        hos = HOSCalculator(trip.current_cycle_used)
        result = hos.calculate_trip(
            leg1['distance_miles'], leg1['duration_hours'],
            leg2['distance_miles'], leg2['duration_hours'],
            trip.current_location, trip.pickup_location, trip.dropoff_location
        )
        
        events = result['events']
        
        from .views import generate_daily_logs
        daily_logs = generate_daily_logs(events, datetime.now())
        
        total_miles = leg1['distance_miles'] + leg2['distance_miles']
        total_driving = sum(e['duration'] for e in events if e['status'] == 'driving')
        total_on_duty = sum(e['duration'] for e in events 
                          if e['status'] in ['driving', 'on_duty_not_driving'])
        
        route_data = {
            'total_miles': round(total_miles, 2),
            'total_duration_hours': round(leg1['duration_hours'] + leg2['duration_hours'], 2),
            'legs': [
                {'from': trip.current_location, 'to': trip.pickup_location,
                 'distance_miles': round(leg1['distance_miles'], 2),
                 'coordinates': leg1.get('coordinates', [])},
                {'from': trip.pickup_location, 'to': trip.dropoff_location,
                 'distance_miles': round(leg2['distance_miles'], 2),
                 'coordinates': leg2.get('coordinates', [])},
            ]
        }
        
        summary = {
            'total_days': len(daily_logs),
            'total_driving_hours': round(total_driving, 2),
            'total_duty_hours': round(total_on_duty, 2),
        }
        
        trip.save_calculation_results(route_data, events, daily_logs, summary)
        
        # Save events and logs
        TripEvent.objects.filter(trip=trip).delete()
        for event in events:
            TripEvent.objects.create(
                trip=trip, event_type=event['status'],
                start_time=event['clock'], duration=event['duration'],
                description=event['description'],
                location=event.get('location', ''),
                distance_at_event=event.get('distance', 0)
            )
        
        DailyLog.objects.filter(trip=trip).delete()
        for log in daily_logs:
            DailyLog.objects.create(
                trip=trip, day_number=log['day'],
                date=datetime.strptime(log['date'], '%Y-%m-%d').date(),
                total_miles=log.get('total_miles', 0),
                off_duty_hours=log['totals']['off_duty'],
                sleeper_berth_hours=log['totals']['sleeper_berth'],
                driving_hours=log['totals']['driving'],
                on_duty_hours=log['totals']['on_duty_not_driving'],
                activities=log['activities'],
                remarks=log.get('remarks', [])
            )


@admin.register(TripEvent)
class TripEventAdmin(admin.ModelAdmin):
    list_display = ['id', 'trip', 'event_type', 'start_time', 'duration', 'location']
    list_filter = ['event_type']

@admin.register(DailyLog)
class DailyLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'trip', 'day_number', 'date', 'driving_hours', 
                    'on_duty_hours', 'sleeper_berth_hours', 'off_duty_hours']

admin.site.site_header = "HOS Trip Planner Administration"
admin.site.site_title = "HOS Admin"
admin.site.index_title = "Dashboard"