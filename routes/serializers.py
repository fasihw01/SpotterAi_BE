from rest_framework import serializers
from .models import Trip

class TripListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        fields = [
            'id', 'current_location', 'pickup_location', 'dropoff_location',
            'current_cycle_used', 'total_miles', 'number_of_days',
            'total_driving_hours', 'total_duty_hours', 'created_at'
        ]

class TripSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        fields = '__all__'

class TripInputSerializer(serializers.Serializer):
    current_location = serializers.CharField(max_length=255)
    pickup_location = serializers.CharField(max_length=255)
    dropoff_location = serializers.CharField(max_length=255)
    current_cycle_used = serializers.FloatField(min_value=0, max_value=70)

    def validate_current_cycle_used(self, value):
        if value > 70:
            raise serializers.ValidationError(
                "Cannot exceed 70 hours. The 70-hour/8-day rule limits total on-duty time to 70 hours."
            )
        if value < 0:
            raise serializers.ValidationError("Cannot be negative.")
        return value