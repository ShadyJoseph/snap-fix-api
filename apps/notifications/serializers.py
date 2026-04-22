import re

from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "title",
            "body",
            "data",
            "is_read",
            "created_at",
        ]
        read_only_fields = fields


class RegisterDeviceSerializer(serializers.Serializer):
    registration_id = serializers.CharField(
        min_length=50,
        max_length=512,
        help_text="FCM device token obtained from the mobile SDK.",
    )
    type = serializers.ChoiceField(
        choices=["android", "ios", "web"],
        help_text="Platform type.",
    )

    def validate_registration_id(self, value):
        if not re.match(r"^[A-Za-z0-9\-_:]+$", value):
            raise serializers.ValidationError(
                "Invalid FCM token format. Tokens may only contain letters, digits, hyphens, underscores, and colons."
            )
        return value
