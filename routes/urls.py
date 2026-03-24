from django.urls import path
from . import views

urlpatterns = [
    path('calculate-trip/', views.calculate_trip, name='calculate_trip'),
    path('trips/', views.list_trips, name='list_trips'),
    path('trips/<int:trip_id>/', views.get_trip, name='get_trip'),
    path('trips/<int:trip_id>/delete/', views.delete_trip, name='delete_trip'),
    path('trips/<int:trip_id>/csv/', views.export_trip_csv, name='export_trip_csv'),
]