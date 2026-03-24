from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import Trip, TripEvent, DailyLog
from .serializers import TripInputSerializer, TripSerializer, TripListSerializer
from .hos_calculator import HOSCalculator
from .route_service import RouteService
from datetime import datetime, timedelta
from django.db.models import Q
from django.core.paginator import Paginator
import traceback
import math


@api_view(['POST'])
def calculate_trip(request):
    serializer = TripInputSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    trip = None
    
    try:
        print(f"\n{'='*50}")
        print(f"CALCULATING TRIP")
        print(f"{'='*50}")
        
        # Create Trip
        trip = Trip.objects.create(
            user=request.user,
            current_location=data['current_location'],
            pickup_location=data['pickup_location'],
            dropoff_location=data['dropoff_location'],
            current_cycle_used=data['current_cycle_used']
        )
        
        # Geocode
        current_coords = RouteService.geocode(data['current_location'])
        pickup_coords = RouteService.geocode(data['pickup_location'])
        dropoff_coords = RouteService.geocode(data['dropoff_location'])
        
        # Routes
        leg1 = RouteService.get_route(current_coords, pickup_coords)
        leg2 = RouteService.get_route(pickup_coords, dropoff_coords)
        
        total_miles = leg1['distance_miles'] + leg2['distance_miles']
        total_duration = leg1['duration_hours'] + leg2['duration_hours']
        print(f"{total_miles:.1f} miles, {total_duration:.2f} hours")
        
        # HOS Calculation
        hos = HOSCalculator(data['current_cycle_used'])
        result = hos.calculate_trip(
            leg1['distance_miles'], leg1['duration_hours'],
            leg2['distance_miles'], leg2['duration_hours'],
            data['current_location'], data['pickup_location'], data['dropoff_location']
        )
        
        events = result['events']
        print(f"{len(events)} events")
        
        # Daily Logs
        start_date = datetime.now()
        daily_logs = generate_daily_logs(events, start_date)
        print(f"{len(daily_logs)} daily logs")
        
        # Route data
        route_data = {
            'total_miles': round(total_miles, 2),
            'total_duration_hours': round(total_duration, 2),
            'legs': [
                {
                    'from': data['current_location'],
                    'to': data['pickup_location'],
                    'distance_miles': round(leg1['distance_miles'], 2),
                    'coordinates': leg1.get('coordinates', [])
                },
                {
                    'from': data['pickup_location'],
                    'to': data['dropoff_location'],
                    'distance_miles': round(leg2['distance_miles'], 2),
                    'coordinates': leg2.get('coordinates', [])
                }
            ]
        }
        
        # Summary
        total_driving = sum(e['duration'] for e in events if e['status'] == 'driving')
        total_on_duty = sum(e['duration'] for e in events 
                          if e['status'] in ['driving', 'on_duty_not_driving'])
        total_rest = sum(e['duration'] for e in events if e['status'] == 'sleeper_berth')
        
        summary = {
            'total_days': len(daily_logs),
            'total_driving_hours': round(total_driving, 2),
            'total_duty_hours': round(total_on_duty, 2),
            'total_rest_hours': round(total_rest, 2),
            'cycle_hours_at_end': result['final_cycle_hours'],
        }
        
        # Save to DB
        trip.save_calculation_results(route_data, events, daily_logs, summary)
        
        # Save individual events
        TripEvent.objects.filter(trip=trip).delete()
        for event in events:
            TripEvent.objects.create(
                trip=trip,
                event_type=event['status'],
                start_time=event['clock'],
                duration=event['duration'],
                description=event['description'],
                location=event.get('location', ''),
                distance_at_event=event.get('distance', 0)
            )
        
        # Save daily logs
        DailyLog.objects.filter(trip=trip).delete()
        for log in daily_logs:
            DailyLog.objects.create(
                trip=trip,
                day_number=log['day'],
                date=datetime.strptime(log['date'], '%Y-%m-%d').date(),
                total_miles=log.get('total_miles', 0),
                off_duty_hours=log['totals']['off_duty'],
                sleeper_berth_hours=log['totals']['sleeper_berth'],
                driving_hours=log['totals']['driving'],
                on_duty_hours=log['totals']['on_duty_not_driving'],
                activities=log['activities'],
                remarks=log.get('remarks', [])
            )
        
        print(f"Trip #{trip.id} saved!\n")
        
        return Response({
            'trip_id': trip.id,
            'route': route_data,
            'events': events,
            'daily_logs': daily_logs,
            'summary': summary
        })
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        traceback.print_exc()
        if trip:
            trip.delete()
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def generate_daily_logs(events, start_date):
    """
    Generate proper daily ELD logs.
    
    Each day:
    - Covers exactly 24 hours (midnight to midnight)
    - Has 4 status rows: off_duty, sleeper_berth, driving, on_duty_not_driving
    - All gaps filled with off_duty
    - Totals = 24 hours
    - Includes remarks for each status change
    """
    if not events:
        return []
    
    # Find total time span
    last_event = events[-1]
    total_hours = last_event['clock'] + last_event['duration']
    num_days = max(1, math.ceil(total_hours / 24))
    
    daily_logs = []
    
    for day_idx in range(num_days):
        day_start = day_idx * 24
        day_end = (day_idx + 1) * 24
        date_str = (start_date + timedelta(days=day_idx)).strftime('%Y-%m-%d')
        
        day_activities = []
        day_miles = 0.0
        day_remarks = []
        
        for event in events:
            ev_start = event['clock']
            ev_end = event['clock'] + event['duration']
            
            # Skip events outside this day
            if ev_end <= day_start or ev_start >= day_end:
                continue
            
            # Clip to day boundaries
            clipped_start = max(ev_start, day_start) - day_start
            clipped_end = min(ev_end, day_end) - day_start
            clipped_duration = clipped_end - clipped_start
            
            if clipped_duration < 0.01:
                continue
            
            day_activities.append({
                'status': event['status'],
                'start_hour': round(clipped_start, 2),
                'end_hour': round(clipped_end, 2),
                'duration': round(clipped_duration, 2),
                'description': event['description'],
                'location': event.get('location', '')
            })
            
            # Miles driven this day
            if event.get('miles') and ev_start >= day_start:
                day_miles += event['miles']
            
            # Remarks
            hour = int(clipped_start)
            minute = int((clipped_start % 1) * 60)
            day_remarks.append({
                'time': f"{hour:02d}:{minute:02d}",
                'status': event['status'],
                'text': event['description'],
                'location': event.get('location', '')
            })
        
        # Fill gaps with off_duty
        filled = _fill_gaps(day_activities)
        
        # Calculate totals (must = 24)
        totals = _calc_totals(filled)
        
        daily_logs.append({
            'day': day_idx + 1,
            'date': date_str,
            'total_miles': round(day_miles, 1),
            'activities': filled,
            'remarks': day_remarks,
            'totals': totals
        })
    
    return daily_logs


def _fill_gaps(activities):
    """Fill time gaps with off_duty so total = 24 hours"""
    if not activities:
        return [{
            'status': 'off_duty',
            'start_hour': 0, 'end_hour': 24,
            'duration': 24, 'description': 'Off Duty', 'location': ''
        }]
    
    activities.sort(key=lambda x: x['start_hour'])
    filled = []
    current = 0.0
    
    for act in activities:
        if act['start_hour'] > current + 0.01:
            gap = round(act['start_hour'] - current, 2)
            filled.append({
                'status': 'off_duty',
                'start_hour': round(current, 2),
                'end_hour': round(act['start_hour'], 2),
                'duration': gap,
                'description': 'Off Duty',
                'location': ''
            })
        filled.append(act)
        current = act['end_hour']
    
    if current < 23.99:
        gap = round(24 - current, 2)
        filled.append({
            'status': 'off_duty',
            'start_hour': round(current, 2),
            'end_hour': 24.0,
            'duration': gap,
            'description': 'Off Duty',
            'location': ''
        })
    
    return filled


def _calc_totals(activities):
    """Calculate totals per status. Must equal 24."""
    totals = {
        'off_duty': 0.0,
        'sleeper_berth': 0.0,
        'driving': 0.0,
        'on_duty_not_driving': 0.0
    }
    
    for act in activities:
        s = act.get('status', 'off_duty')
        d = act.get('duration', 0)
        if s in totals:
            totals[s] += d
    
    for key in totals:
        totals[key] = round(totals[key], 2)
    
    # Fix rounding to ensure exactly 24
    total = sum(totals.values())
    if abs(total - 24) > 0.01:
        totals['off_duty'] = round(totals['off_duty'] + (24 - total), 2)
    
    return totals
@api_view(['GET'])
def list_trips(request):
    search_query = request.GET.get('q', '')
    page_number = request.GET.get('page', 1)
    page_size = request.GET.get('page_size', 10)

    trips = Trip.objects.filter(user=request.user)

    if search_query:
        trips = trips.filter(
            Q(pickup_location__icontains=search_query) |
            Q(dropoff_location__icontains=search_query) |
            Q(current_location__icontains=search_query)
        )

    paginator = Paginator(trips, page_size)
    page_obj = paginator.get_page(page_number)

    serializer = TripListSerializer(page_obj, many=True)
    return Response({
        'trips': serializer.data,
        'total_count': paginator.count,
        'total_pages': paginator.num_pages,
        'current_page': page_obj.number,
        'has_next': page_obj.has_next(),
        'has_previous': page_obj.has_previous(),
    })


@api_view(['GET'])
def get_trip(request, trip_id):
    try:
        trip = Trip.objects.get(id=trip_id, user=request.user)
        print(trip,"trip")
        return Response({
            'id': trip.id,
            'formData': {
                'current_location': trip.current_location,
                'pickup_location': trip.pickup_location,
                'dropoff_location': trip.dropoff_location,
                'current_cycle_used': trip.current_cycle_used,
            },
            'result': {
                'route': trip.route_data,
                'events': trip.events_data,
                'daily_logs': trip.daily_logs_data,
                'summary': {
                    'total_miles': trip.total_miles,
                    'total_days': trip.number_of_days,
                    'total_driving_hours': trip.total_driving_hours,
                    'total_duty_hours': trip.total_duty_hours,
                    'total_rest_hours': trip.total_rest_hours,
                    'cycle_hours_at_end': trip.cycle_hours_at_end,
                }
            },
            'timestamp': trip.created_at.timestamp() * 1000
        })
    except Trip.DoesNotExist:
        return Response({'error': 'Trip not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['DELETE'])
def delete_trip(request, trip_id):
    try:
        trip = Trip.objects.get(id=trip_id, user=request.user)
        trip.delete()
        return Response({'message': 'Trip deleted successfully'}, status=status.HTTP_204_NO_CONTENT)
    except Trip.DoesNotExist:
        return Response({'error': 'Trip not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def export_trip_csv(request, trip_id):
    try:
        import csv
        from django.http import HttpResponse
        
        trip = Trip.objects.get(id=trip_id)
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="trip_{trip_id}_logs.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Day', 'Date', 'Status', 'Start Hour', 'End Hour', 'Duration', 'Description', 'Location'])
        
        if trip.daily_logs_data:
            for log in trip.daily_logs_data:
                for activity in log.get('activities', []):
                    writer.writerow([
                        log.get('day'),
                        log.get('date'),
                        activity.get('status'),
                        activity.get('start_hour'),
                        activity.get('end_hour'),
                        activity.get('duration'),
                        activity.get('description'),
                        activity.get('location')
                    ])
        
        return response
    except Trip.DoesNotExist:
        return Response({'error': 'Trip not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
