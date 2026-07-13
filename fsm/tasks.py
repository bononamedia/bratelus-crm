import math
from celery import shared_task
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from .models import JobEvidence
import json
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import WorkerLocation

# --- Helper Functions for Coordinate Math ---
def get_decimal_from_dms(dms, ref):
    """Converts Degrees/Minutes/Seconds EXIF data into Decimal coordinates."""
    degrees = dms[0]
    minutes = dms[1]
    seconds = dms[2]
    decimal = float(degrees) + float(minutes)/60 + float(seconds)/3600
    if ref in ['S', 'W']:
        decimal = -decimal
    return decimal

def calculate_distance(lat1, lon1, lat2, lon2):
    """Haversine formula to calculate distance in meters between two GPS points."""
    R = 6371000 # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi/2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

# --- The Main Celery Task ---
@shared_task
def verify_photo_evidence(evidence_id):
    """
    Runs in the background. Opens the uploaded photo, extracts GPS data,
    and flags the database if the photo was taken > 100 meters from the property.
    """
    try:
        evidence = JobEvidence.objects.select_related('job__property').get(id=evidence_id)
        
        # Open the image using Pillow (works seamlessly with S3 via Django Storage)
        image = Image.open(evidence.photo.open('rb'))
        exif_info = image.getexif()
        
        if not exif_info:
            evidence.qc_notes = "FAILED: No EXIF data found. Photo may be a screenshot or edited."
            evidence.is_verified = False
            evidence.save()
            return
            
        # Extract GPS Info
        gps_info = {}
        for key, value in exif_info.get_ifd(0x8825).items():
            decode = GPSTAGS.get(key, key)
            gps_info[decode] = value
            
        if 'GPSLatitude' not in gps_info or 'GPSLongitude' not in gps_info:
            evidence.qc_notes = "FAILED: Location services were disabled on the camera."
            evidence.is_verified = False
            evidence.save()
            return

        # Convert to Decimals
        photo_lat = get_decimal_from_dms(gps_info['GPSLatitude'], gps_info['GPSLatitudeRef'])
        photo_lng = get_decimal_from_dms(gps_info['GPSLongitude'], gps_info['GPSLongitudeRef'])
        
        # Save exact photo coordinates to the DB
        evidence.lat = photo_lat
        evidence.lng = photo_lng
        
        # Compare to Property Location
        expected_lat = evidence.job.property.location_lat
        expected_lng = evidence.job.property.location_lng
        
        if expected_lat and expected_lng:
            distance = calculate_distance(photo_lat, photo_lng, float(expected_lat), float(expected_lng))
            
            if distance <= 100: # 100 meters tolerance
                evidence.is_verified = True
                evidence.qc_notes = f"PASSED: Photo taken {int(distance)}m from target property."
            else:
                evidence.is_verified = False
                evidence.qc_notes = f"FLAGGED: Photo taken {int(distance)}m away from property!"
        else:
            evidence.is_verified = False
            evidence.qc_notes = "PENDING: Property has no coordinates set to verify against."

        evidence.save()

    except JobEvidence.DoesNotExist:
        pass

# ----------------------------------------------------------------------------
# Creat the Bulk Writer
# ============================================================================

@shared_task
def flush_gps_pings_buffer_to_db():
    """
    Periodic task that safely flushes cached GPS points from the 
    Redis queue into PostgreSQL using a high-performance bulk operation.
    """
    # 1. Connect directly to the underlying Redis instance behind Django's cache wrapper
    redis_client = cache.client.get_client()
    
    # 2. Extract all currently queued items in the list atomically
    # We rename the key temporarily or read all items up to the current length to prevent race conditions
    buffer_length = redis_client.llen("raw_gps_pings_buffer")
    if buffer_length == 0:
        return "Buffer is empty. No tracking points to write."

    # Pop 'buffer_length' number of items from the left side of the list
    pings_to_process = []
    for _ in range(buffer_length):
        ping_raw = redis_client.lpop("raw_gps_pings_buffer")
        if ping_raw:
            pings_to_process.append(json.loads(ping_raw.decode('utf-8')))

    if not pings_to_process:
        return "No clear data found in buffer."

    # 3. Parse data structures into memory-efficient Django Model instances
    location_instances = []
    for ping in pings_to_process:
        try:
            recorded_at = parse_datetime(ping.get('timestamp', '')) or timezone.now()
            if timezone.is_naive(recorded_at):
                recorded_at = timezone.make_aware(recorded_at)

            location_instances.append(
                WorkerLocation(
                    worker_id=ping['worker_id'],
                    lat=ping['latitude'],
                    lng=ping['longitude'],
                    timestamp=recorded_at,
                )
            )
        except KeyError:
            # Skip malformed data entries gracefully
            continue

    # 4. Perform a high-efficiency SQL Bulk Insert operation
    if location_instances:
        # bulk_create combines hundreds of individual inserts into a single database hit
        WorkerLocation.objects.bulk_create(location_instances, batch_size=500)
        
    return f"Successfully flushed {len(location_instances)} tracking points to PostgreSQL."
