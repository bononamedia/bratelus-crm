from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError


def normalize_profile_photo(upload):
    if not upload or upload.size > 15 * 1024 * 1024:
        return None, 'Profile photo must be no larger than 15 MB.'
    try:
        image = Image.open(upload)
        image = ImageOps.exif_transpose(image)
        image.thumbnail((1600, 1600))
        if image.mode not in ('RGB', 'L'):
            background = Image.new('RGB', image.size, 'white')
            if 'A' in image.getbands():
                background.paste(image, mask=image.getchannel('A'))
            else:
                background.paste(image)
            image = background
        elif image.mode == 'L':
            image = image.convert('RGB')
        output = BytesIO()
        image.save(output, format='JPEG', quality=88, optimize=True)
        name = f'{Path(upload.name).stem[:80] or "profile"}.jpg'
        return ContentFile(output.getvalue(), name=name), ''
    except (UnidentifiedImageError, OSError, ValueError):
        return None, 'Use a JPG or PNG photo. Some HEIC files must be converted before upload.'
