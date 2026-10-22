import os
import uuid
import time
import logging
import cloudinary
import cloudinary.uploader
import cloudinary.utils
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Generic user-safe exception for storage failures."""
    pass


PROVIDER_MAP = {
    'cloudinary': 'reports.storage_services.CloudinaryEvidenceStorage',
}


class LocalEvidenceStorage:
    """
    Local filesystem storage provider for offline / local development.
    Stores evidence files in MEDIA_ROOT using Django's default_storage.
    """
    ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'}
    ALLOWED_RAW_EXTENSIONS = {'.pdf', '.doc', '.docx'}
    SUPPORTED_RESOURCE_TYPES = {'image', 'raw'}

    def _determine_resource_type_and_path(self, filename, folder_path):
        ext = os.path.splitext(filename)[1].lower()
        unique_id = uuid.uuid4().hex[:12]

        if ext in self.ALLOWED_IMAGE_EXTENSIONS:
            resource_type = 'image'
        elif ext in self.ALLOWED_RAW_EXTENSIONS:
            resource_type = 'raw'
        else:
            raise StorageError(f"Unsupported evidence file extension '{ext}'.")

        saved_path = f"{folder_path}/vng_ev_{unique_id}{ext}"
        return resource_type, saved_path, ext.lstrip('.')

    def upload_evidence(self, file_obj, folder_prefix="evidence"):
        """Saves file to local filesystem via default_storage."""
        now_str = time.strftime('%Y/%m')
        folder_path = f"{folder_prefix}/{now_str}"

        req_resource_type, saved_path, ext_format = self._determine_resource_type_and_path(
            file_obj.name, folder_path
        )

        try:
            actual_path = default_storage.save(saved_path, file_obj)
            file_size = default_storage.size(actual_path) if default_storage.exists(actual_path) else 0
        except Exception as e:
            logger.error("Local evidence upload failed: %s", type(e).__name__)
            raise StorageError("Local storage upload failed.") from e

        return {
            'provider': 'local',
            'public_id': actual_path,
            'resource_type': req_resource_type,
            'format': ext_format,
            'bytes': file_size,
            'asset_id': actual_path,
        }

    def generate_signed_url(self, public_id, format, resource_type="image", expires_in_seconds=300, attachment=False):
        """Returns direct media URL for local storage in development."""
        if not public_id:
            raise ValueError("public_id is required.")
        return f"{settings.MEDIA_URL}{public_id}"

    def delete_evidence(self, public_id, resource_type="image"):
        """Deletes file from local default_storage."""
        if not public_id:
            raise ValueError("public_id is required for deletion.")
        try:
            if default_storage.exists(public_id):
                default_storage.delete(public_id)
                return {'status': 'deleted', 'public_id': public_id}
            return {'status': 'not_found', 'public_id': public_id}
        except Exception as e:
            logger.error("Local evidence deletion failed: %s", type(e).__name__)
            raise StorageError("Local storage deletion failed.") from e


class CloudinaryEvidenceStorage:
    """
    Cloudinary storage provider implementation.
    Maps validated file extensions to deterministic resource types (image vs raw).
    Automatically falls back to LocalEvidenceStorage in DEBUG development mode.
    """

    ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'}
    ALLOWED_RAW_EXTENSIONS = {'.pdf', '.doc', '.docx'}
    SUPPORTED_RESOURCE_TYPES = {'image', 'raw'}

    def __init__(self):
        cloud_name = getattr(settings, 'CLOUDINARY_CLOUD_NAME', None) or os.getenv('CLOUDINARY_CLOUD_NAME')
        api_key = getattr(settings, 'CLOUDINARY_API_KEY', None) or os.getenv('CLOUDINARY_API_KEY')
        api_secret = getattr(settings, 'CLOUDINARY_API_SECRET', None) or os.getenv('CLOUDINARY_API_SECRET')

        if not all([cloud_name, api_key, api_secret]):
            raise ImproperlyConfigured(
                "Cloudinary credentials missing. Ensure CLOUDINARY_CLOUD_NAME, "
                "CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET are configured."
            )

        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True
        )

    def _determine_resource_type_and_public_id(self, filename, folder_path):
        """
        Deterministically maps validated file extension to Cloudinary resource_type.
        Appends extension to public_id for raw assets per Cloudinary requirements.
        """
        ext = os.path.splitext(filename)[1].lower()
        unique_id = uuid.uuid4().hex[:12]

        if ext in self.ALLOWED_IMAGE_EXTENSIONS:
            resource_type = 'image'
            public_id = f"{folder_path}/vng_ev_{unique_id}"
        elif ext in self.ALLOWED_RAW_EXTENSIONS:
            resource_type = 'raw'
            public_id = f"{folder_path}/vng_ev_{unique_id}{ext}"
        else:
            raise StorageError(f"Unsupported evidence file extension '{ext}'.")

        return resource_type, public_id, ext.lstrip('.')

    def upload_evidence(self, file_obj, folder_prefix="evidence"):
        """
        Uploads file to Cloudinary under private access control.
        Validates returned metadata against requested configuration.
        Falls back to LocalEvidenceStorage in development when Cloudinary fails.
        """
        now_str = time.strftime('%Y/%m')
        folder_path = f"{folder_prefix}/{now_str}"

        req_resource_type, public_id, ext_format = self._determine_resource_type_and_public_id(
            file_obj.name, folder_path
        )

        try:
            upload_result = cloudinary.uploader.upload(
                file_obj,
                public_id=public_id,
                resource_type=req_resource_type,
                type="private",
                tags=["verifyng_evidence"]
            )
        except Exception as e:
            logger.error("Cloudinary upload failed: %s", type(e).__name__)
            # In development (DEBUG=True), seamlessly fall back to LocalEvidenceStorage
            if getattr(settings, 'DEBUG', False):
                logger.warning(
                    "DEBUG mode: Falling back to LocalEvidenceStorage due to Cloudinary failure (%s: %s).",
                    type(e).__name__, str(e)
                )
                try:
                    file_obj.seek(0)
                except Exception:
                    pass
                local_storage = LocalEvidenceStorage()
                return local_storage.upload_evidence(file_obj, folder_prefix=folder_prefix)
            raise StorageError("Cloud storage upload failed.") from e

        returned_public_id = upload_result.get('public_id')
        returned_resource_type = upload_result.get('resource_type')
        returned_format = upload_result.get('format')

        if not returned_public_id:
            logger.error("Cloudinary upload returned missing public_id.")
            raise StorageError("Cloud storage returned invalid asset metadata.")

        if returned_public_id != public_id:
            logger.error(
                "Cloudinary returned a public_id that does not match the requested identifier."
            )
            raise StorageError("Cloud storage returned an unexpected asset identifier.")

        if returned_resource_type != req_resource_type:
            logger.error(
                "Cloudinary resource_type mismatch: expected '%s', received '%s'.",
                req_resource_type, returned_resource_type
            )
            raise StorageError("Cloud storage returned unexpected asset resource type.")

        if not returned_format:
            if req_resource_type == 'raw':
                returned_format = ext_format
            else:
                logger.error("Cloudinary returned missing format for image upload.")
                raise StorageError("Cloud storage returned incomplete asset metadata.")

        return {
            'provider': 'cloudinary',
            'public_id': returned_public_id,
            'resource_type': returned_resource_type,
            'format': returned_format,
            'bytes': upload_result.get('bytes', 0),
            'asset_id': upload_result.get('asset_id', '')
        }

    def generate_signed_url(self, public_id, format, resource_type="image", expires_in_seconds=300, attachment=False):
        """
        Generates a signed private URL.
        - attachment=False (default): signed delivery CDN URL that opens inline in a new tab.
        - attachment=True: signed download API URL that forces file download.
        """
        if not public_id:
            raise ValueError("public_id is required.")
        if not format:
            raise ValueError("format is required.")
        if resource_type not in self.SUPPORTED_RESOURCE_TYPES:
            raise ValueError(f"Unsupported resource_type '{resource_type}'.")
        if not isinstance(expires_in_seconds, int) or not (1 <= expires_in_seconds <= 3600):
            raise ValueError("expires_in_seconds must be an integer between 1 and 3600.")
        expires_at = int(time.time()) + expires_in_seconds
        try:
            if not attachment:
                # Delivers signed CDN URL that renders inline in browser
                signed_url, _ = cloudinary.utils.cloudinary_url(
                    public_id,
                    format=format,
                    resource_type=resource_type,
                    type="private",
                    sign_url=True,
                    secure=True
                )
                return signed_url
            else:
                # Hits Cloudinary download API with attachment header
                signed_url = cloudinary.utils.private_download_url(
                    public_id=public_id,
                    format=format,
                    resource_type=resource_type,
                    type="private",
                    attachment=True,
                    expires_at=expires_at
                )
                return signed_url
        except Exception as e:
            logger.error("Signed URL generation failed: %s", type(e).__name__)
            raise StorageError("Failed to generate secure URL.") from e

    def delete_evidence(self, public_id, resource_type="image"):
        """
        Deletes evidence asset from Cloudinary or local storage.
        """
        if not public_id:
            raise ValueError("public_id is required for deletion.")
        if resource_type not in self.SUPPORTED_RESOURCE_TYPES:
            raise ValueError(f"Unsupported resource_type '{resource_type}'.")

        # Clean up local file if stored via local fallback
        if default_storage.exists(public_id):
            default_storage.delete(public_id)
            return {'status': 'deleted', 'public_id': public_id}

        try:
            result = cloudinary.uploader.destroy(
                public_id=public_id,
                resource_type=resource_type,
                type="private",
                invalidate=True
            )
            cloudinary_result = result.get('result')

            if cloudinary_result == 'ok':
                return {'status': 'deleted', 'public_id': public_id}

            if cloudinary_result == 'not found':
                logger.warning(
                    "Cloudinary asset not found during deletion (possible inconsistency): "
                    "resource_type=%s", resource_type
                )
                return {'status': 'not_found', 'public_id': public_id}

            logger.error("Cloudinary deletion returned unexpected result: %s", cloudinary_result)
            raise StorageError("Cloud storage deletion rejected.")
        except Exception as e:
            logger.error("Cloudinary deletion exception: %s", type(e).__name__)
            raise StorageError("Cloud storage deletion failed.") from e


def get_storage_service():
    """Default factory using settings.EVIDENCE_STORAGE_PROVIDER."""
    provider_path = getattr(
        settings,
        'EVIDENCE_STORAGE_PROVIDER',
        'reports.storage_services.CloudinaryEvidenceStorage'
    )
    provider_class = import_string(provider_path)
    return provider_class()


def get_storage_service_for_provider(provider_name):
    """
    Returns storage service instance for the given provider name.
    Raises StorageError explicitly for unsupported or local providers.
    """
    if not provider_name or provider_name == 'local':
        raise StorageError(f"Provider '{provider_name}' is not a cloud storage provider.")
    provider_path = PROVIDER_MAP.get(provider_name)
    if not provider_path:
        raise StorageError(f"Unknown or unsupported storage provider: '{provider_name}'.")
    provider_class = import_string(provider_path)
    return provider_class()

