import os
import zipfile
from django import forms
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

from identities.models import SubjectEntity
from identities.utils import normalize_identifier
from reports.models import ReportEvidence

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

ALLOWED_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.pdf', '.doc', '.docx']

ALLOWED_MIME_TYPES = [
    'image/png',
    'image/jpeg',
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]

NIGERIAN_STATES = [
    ('', '-- Select State (Optional) --'),
    ('Abia', 'Abia'), ('Adamawa', 'Adamawa'), ('Akwa Ibom', 'Akwa Ibom'),
    ('Anambra', 'Anambra'), ('Bauchi', 'Bauchi'), ('Bayelsa', 'Bayelsa'),
    ('Benue', 'Benue'), ('Borno', 'Borno'), ('Cross River', 'Cross River'),
    ('Delta', 'Delta'), ('Ebonyi', 'Ebonyi'), ('Edo', 'Edo'),
    ('Ekiti', 'Ekiti'), ('Enugu', 'Enugu'), ('FCT - Abuja', 'FCT - Abuja'),
    ('Gombe', 'Gombe'), ('Imo', 'Imo'), ('Jigawa', 'Jigawa'),
    ('Kaduna', 'Kaduna'), ('Kano', 'Kano'), ('Katsina', 'Katsina'),
    ('Kebbi', 'Kebbi'), ('Kogi', 'Kogi'), ('Kwara', 'Kwara'),
    ('Lagos', 'Lagos'), ('Nasarawa', 'Nasarawa'), ('Niger', 'Niger'),
    ('Ogun', 'Ogun'), ('Ondo', 'Ondo'), ('Osun', 'Osun'),
    ('Oyo', 'Oyo'), ('Plateau', 'Plateau'), ('Rivers', 'Rivers'),
    ('Sokoto', 'Sokoto'), ('Taraba', 'Taraba'), ('Yobe', 'Yobe'),
    ('Zamfara', 'Zamfara'),
]


def validate_file_upload(file):
    """
    Reusable validator enforcing the project-wide 10 MB size limit
    and magic-byte signature validation across images, PDFs, and Word documents.
    """
    if not file:
        return file

    if file.size > MAX_FILE_SIZE_BYTES:
        raise ValidationError("File size exceeds the 10 MB maximum limit.")

    ext = os.path.splitext(file.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    mime = getattr(file, 'content_type', None)
    if mime and mime not in ALLOWED_MIME_TYPES:
        raise ValidationError("The uploaded file's reported type is not supported.")

    file.seek(0)
    try:
        if ext in ['.png', '.jpg', '.jpeg']:
            try:
                img = Image.open(file)
                img.verify()
            except UnidentifiedImageError:
                raise ValidationError("The uploaded file is not a recognised image format.")
            except OSError:
                raise ValidationError("The uploaded image file appears to be incomplete or corrupted.")

        elif ext == '.pdf':
            header = file.read(4)
            if header != b'%PDF':
                raise ValidationError("The uploaded file does not appear to be a valid PDF.")

        elif ext == '.doc':
            header = file.read(4)
            if header != b'\xd0\xcf\x11\xe0':
                raise ValidationError("The uploaded file does not appear to be a valid DOC file.")

        elif ext == '.docx':
            header = file.read(4)
            if header != b'PK\x03\x04':
                raise ValidationError("The uploaded file does not appear to be a valid DOCX file.")
            file.seek(0)
            try:
                with zipfile.ZipFile(file, 'r') as zf:
                    names = zf.namelist()
                    if '[Content_Types].xml' not in names or 'word/document.xml' not in names:
                        raise ValidationError("The uploaded file does not contain the expected DOCX structure.")
            except zipfile.BadZipFile:
                raise ValidationError("The uploaded file is not a valid ZIP/DOCX archive.")
    finally:
        file.seek(0)

    return file


class FraudReportSubmissionForm(forms.Form):
    # Step 1: Subject Identity & Identifiers
    subject_name = forms.CharField(
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Full name of person or business name', 'class': 'form-control'})
    )
    subject_type = forms.ChoiceField(
        choices=[('', '-- Select Entity Type --')] + list(SubjectEntity.ENTITY_TYPES),
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'}),
        error_messages={
            'required': 'Please select an entity type.',
            'invalid_choice': 'Select a valid entity type from the list.',
        }
    )
    suspect_phone = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. 08012345678 or +2348012345678', 'class': 'form-control'}),
        help_text="Optional. Nigerian mobile or landline number."
    )
    suspect_bank_account = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': '10-digit NUBAN Account Number', 'class': 'form-control'}),
        help_text="Optional. 10 numeric digits."
    )
    suspect_bank_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. OPay, GTBank, Access Bank, Zenith, Kuda', 'class': 'form-control', 'list': 'nigerian_banks_list'}),
        help_text="Optional. Bank or Fintech institution."
    )
    suspect_cac_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. RC1234567 or BN987654', 'class': 'form-control'}),
        help_text="Optional. Corporate Affairs Commission registration."
    )
    suspect_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'placeholder': 'e.g. scammer@example.com', 'class': 'form-control'}),
        help_text="Optional. Email address used by the suspect."
    )

    # Step 2: Incident & Location
    title = forms.CharField(
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Summary title of allegation (e.g. Fake investment payout)', 'class': 'form-control'})
    )
    incident_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    suspect_location = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Shop 4B Alaba Int\'l Market or Street Address', 'class': 'form-control'}),
        help_text="Optional. Operating or physical address."
    )
    suspect_state = forms.ChoiceField(
        choices=NIGERIAN_STATES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    suspect_city = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Ikeja, Lekki, Wuse 2, Port Harcourt', 'class': 'form-control'}),
        help_text="Optional. City or LGA area."
    )
    allegation = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'Provide a detailed, chronological factual account of what transpired...',
            'rows': 5,
            'class': 'form-control'
        }),
        required=True
    )

    # Step 3: Supporting Evidence (Optional)
    evidence_file = forms.FileField(
        required=False,
        help_text="Optional document, receipt, or screenshot (PDF, PNG, JPG, DOCX — max 10 MB)."
    )
    evidence_type = forms.ChoiceField(
        choices=ReportEvidence.EVIDENCE_TYPES,
        required=False,
        initial='screenshot',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    evidence_description = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Brief description of file (e.g. Transfer receipt from bank app)', 'class': 'form-control'})
    )

    def clean_suspect_phone(self):
        val = self.cleaned_data.get('suspect_phone')
        if val and str(val).strip():
            try:
                return normalize_identifier('phone', val.strip())
            except ValueError:
                raise forms.ValidationError("Invalid Nigerian phone number. Must be 11 digits starting with 0 or 13 digits starting with 234.")
        return ''

    def clean_suspect_bank_account(self):
        val = self.cleaned_data.get('suspect_bank_account')
        if val and str(val).strip():
            try:
                return normalize_identifier('account', val.strip())
            except ValueError:
                raise forms.ValidationError("Invalid Nigerian bank account number. Must be exactly 10 numeric digits.")
        return ''

    def clean_suspect_cac_number(self):
        val = self.cleaned_data.get('suspect_cac_number')
        if val and str(val).strip():
            try:
                return normalize_identifier('cac', val.strip())
            except ValueError:
                raise forms.ValidationError("Invalid CAC registration number format (e.g., RC123456 or BN123456).")
        return ''

    def clean_suspect_email(self):
        val = self.cleaned_data.get('suspect_email')
        if val and str(val).strip():
            try:
                return normalize_identifier('email', val.strip())
            except ValueError:
                raise forms.ValidationError("Invalid email address format.")
        return ''

    def clean_evidence_file(self):
        file = self.cleaned_data.get('evidence_file')
        return validate_file_upload(file)

    def clean(self):
        cleaned_data = super().clean()
        # If subject is a person, ensure CAC registration is cleared
        if cleaned_data.get('subject_type') != 'business':
            cleaned_data['suspect_cac_number'] = ''
        return cleaned_data


class DisputeSubmissionForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'Explain why this allegation is inaccurate, resolved, or fabricated...',
            'rows': 5,
            'class': 'form-control'
        }),
        required=True,
        help_text="Provide specific factual details, transaction references, or context."
    )
    counter_evidence = forms.FileField(
        required=False,
        help_text="Optional proof of fulfillment, payment receipt, or communication log (PNG, JPG, PDF, DOCX — max 10 MB)."
    )

    def clean_counter_evidence(self):
        file = self.cleaned_data.get('counter_evidence')
        return validate_file_upload(file)


class ReportModerationActionForm(forms.Form):
    ACTION_CHOICES = (
        ('under_review', 'Mark Under Review'),
        ('published', 'Approve & Publish to Public Directory'),
        ('rejected', 'Reject Report (Decline)'),
        ('restricted', 'Quarantine / Restrict Report'),
    )
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    moderation_notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Internal notes explaining decision...'}),
        required=False
    )

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        notes = cleaned_data.get('moderation_notes')
        if action == 'rejected' and not (notes and notes.strip()):
            self.add_error('moderation_notes', "Moderation notes are mandatory when rejecting a report.")
        return cleaned_data


class DisputeResolutionForm(forms.Form):
    RESOLUTION_CHOICES = (
        ('accepted', 'Accept Dispute (Quarantine/Remove Report)'),
        ('rejected', 'Reject Dispute (Uphold Published Report)'),
    )
    resolution = forms.ChoiceField(
        choices=RESOLUTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    resolution_notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Explain findings of this dispute resolution...'}),
        required=True
    )

