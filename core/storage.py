import os
import logging
import cloudinary
import cloudinary.uploader
import cloudinary.utils
from django.conf import settings
from django.core.files.storage import Storage, FileSystemStorage
from django.utils.deconstruct import deconstructible

logger = logging.getLogger(__name__)


@deconstructible
class UniversalCloudinaryStorage(Storage):
    """
    Production-grade universal storage backend for all Django FileField and ImageField models.
    
    Behavior:
    1. If Cloudinary credentials (CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET)
       are present: uploads assets to Cloudinary (image vs raw based on file extension) and returns
       secure Cloudinary CDN URLs.
    2. If Cloudinary credentials are not configured or missing: seamlessly falls back to local
       FileSystemStorage (saving under MEDIA_ROOT and serving from MEDIA_URL).
    3. In development (DEBUG=True): if Cloudinary upload experiences a transient network outage,
       it gracefully falls back to local filesystem storage so development workflows never break.
    """

    ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.ico', '.svg'}
    ALLOWED_RAW_EXTENSIONS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.csv', '.zip'}

    def __init__(self, **kwargs):
        self._local_storage = FileSystemStorage()
        self.cloud_name = getattr(settings, 'CLOUDINARY_CLOUD_NAME', None) or os.getenv('CLOUDINARY_CLOUD_NAME', '')
        self.api_key = getattr(settings, 'CLOUDINARY_API_KEY', None) or os.getenv('CLOUDINARY_API_KEY', '')
        self.api_secret = getattr(settings, 'CLOUDINARY_API_SECRET', None) or os.getenv('CLOUDINARY_API_SECRET', '')
        self.is_configured = bool(self.cloud_name and self.api_key and self.api_secret)

        if self.is_configured:
            cloudinary.config(
                cloud_name=self.cloud_name,
                api_key=self.api_key,
                api_secret=self.api_secret,
                secure=True
            )

    def _determine_resource_type(self, name):
        ext = os.path.splitext(name)[1].lower()
        if ext in self.ALLOWED_IMAGE_EXTENSIONS:
            return 'image'
        return 'raw'

    def _clean_name(self, name):
        return name.lstrip('/\\').replace('\\', '/')

    def _save(self, name, content):
        import sys
        clean_name = self._clean_name(name)
        # If running unit tests or Cloudinary is not configured, write to local test storage
        if 'test' in sys.argv or getattr(settings, 'TESTING', False) or not self.is_configured:
            return self._local_storage._save(clean_name, content)

        resource_type = self._determine_resource_type(clean_name)
        base_name, _ = os.path.splitext(clean_name)
        # Cloudinary requires extension in public_id for 'raw' assets (.pdf, .docx)
        public_id = clean_name if resource_type == 'raw' else base_name

        try:
            try:
                content.seek(0)
            except Exception:
                pass

            cloudinary.uploader.upload(
                content,
                public_id=public_id,
                resource_type=resource_type,
                type='upload',
                use_filename=True,
                unique_filename=False,
                overwrite=True
            )
            logger.info("UniversalCloudinaryStorage: uploaded '%s' to Cloudinary (resource_type=%s)", clean_name, resource_type)
            return clean_name
        except Exception as e:
            logger.error("UniversalCloudinaryStorage upload error for '%s': %s", clean_name, type(e).__name__)
            if getattr(settings, 'DEBUG', False):
                logger.warning("DEBUG mode: Falling back to local storage for '%s'.", clean_name)
                try:
                    content.seek(0)
                except Exception:
                    pass
                return self._local_storage._save(clean_name, content)
            raise

    def _open(self, name, mode='rb'):
        clean_name = self._clean_name(name)
        if self._local_storage.exists(clean_name):
            return self._local_storage._open(clean_name, mode=mode)
        
        # Download from Cloudinary if needed for server-side processing
        import requests
        from django.core.files.base import ContentFile
        file_url = self.url(clean_name)
        resp = requests.get(file_url, stream=True, timeout=15)
        resp.raise_for_status()
        return ContentFile(resp.content, name=clean_name)

    def url(self, name):
        if not name:
            return ''
        clean_name = self._clean_name(name)
        if clean_name.startswith(('http://', 'https://')):
            return clean_name

        if not self.is_configured:
            return self._local_storage.url(clean_name)

        # If the file physically exists on the local filesystem (legacy upload or local fallback),
        # serve it from local media URL so existing local files are never broken
        if self._local_storage.exists(clean_name):
            return self._local_storage.url(clean_name)

        resource_type = self._determine_resource_type(clean_name)
        c_url, _ = cloudinary.utils.cloudinary_url(
            clean_name,
            resource_type=resource_type,
            secure=True,
            type='upload'
        )
        return c_url

    def exists(self, name):
        clean_name = self._clean_name(name)
        # Always report True if the file physically exists in local storage
        if self._local_storage.exists(clean_name):
            return True
        return False

    def delete(self, name):
        if not name:
            return
        clean_name = self._clean_name(name)
        if self._local_storage.exists(clean_name):
            try:
                self._local_storage.delete(clean_name)
            except Exception:
                pass

        if self.is_configured:
            resource_type = self._determine_resource_type(clean_name)
            base_name, _ = os.path.splitext(clean_name)
            public_id = clean_name if resource_type == 'raw' else base_name
            try:
                cloudinary.uploader.destroy(public_id, resource_type=resource_type, type='upload')
            except Exception as e:
                logger.warning("Cloudinary destroy failed for '%s': %s", clean_name, type(e).__name__)

    def size(self, name):
        clean_name = self._clean_name(name)
        if self._local_storage.exists(clean_name):
            return self._local_storage.size(clean_name)
        return 0

    def get_available_name(self, name, max_length=None):
        clean_name = self._clean_name(name)
        if not self.is_configured:
            return self._local_storage.get_available_name(clean_name, max_length=max_length)
        return clean_name
