# verification/tasks.py
import io
import base64
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


def _generate_qr_base64(url: str) -> str:
    """
    Returns a base64-encoded PNG of a QR code pointing to `url`.
    Suitable for embedding directly in an HTML <img src="data:..."> tag.
    """
    import qrcode
    from PIL import Image

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='#006D5B', back_color='white')

    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode('utf-8')


@shared_task(bind=True, name='verification.tasks.generate_certificate_pdf', max_retries=3, default_retry_delay=60)
def generate_certificate_pdf(self, certificate_id: str):
    """
    Renders the certificate PDF template and uploads to Cloudinary.
    Triggered after a certificate is activated.
    Stores the resulting Cloudinary public_id in certificate.pdf_file.
    """
    try:
        from django.template.loader import render_to_string
        from django.conf import settings
        from weasyprint import HTML
        from verification.models import VerificationCertificate
        from verification.services import upload_certificate_pdf

        certificate = VerificationCertificate.objects.select_related(
            'subject', 'holder'
        ).get(certificate_id=certificate_id)

        base_url = getattr(settings, 'SITE_BASE_URL', 'http://localhost:8000')
        verification_url = f"{base_url}/verification/certificate/{certificate_id}/"

        qr_base64 = _generate_qr_base64(verification_url)

        html_string = render_to_string(
            'verification/certificate_pdf.html',
            {
                'certificate': certificate,
                'base_url': base_url,
                'verification_url': verification_url,
                'qr_base64': qr_base64,
            }
        )

        pdf_bytes = HTML(
            string=html_string,
            base_url=base_url,
        ).write_pdf()

        pdf_file = io.BytesIO(pdf_bytes)
        pdf_file.name = f'certificate_{certificate_id}.pdf'

        upload_certificate_pdf(certificate, pdf_file)

        logger.info("Certificate PDF generated and uploaded: %s", certificate_id)
        return {'certificate_id': certificate_id, 'status': 'uploaded'}

    except VerificationCertificate.DoesNotExist:
        logger.error("generate_certificate_pdf: certificate %s not found", certificate_id)
        return {'certificate_id': certificate_id, 'status': 'not_found'}

    except Exception as exc:
        logger.error(
            "generate_certificate_pdf failed for %s: %s",
            certificate_id, str(exc), exc_info=True
        )
        raise self.retry(exc=exc)

