
import json
from django import forms
from django.core.exceptions import ValidationError
from verification.models import VerificationRequest, VerificationResult
from identities.models import SubjectEntity
from identities.utils import SUPPORTED_IDENTIFIER_TYPES, normalize_identifier
from verification.models import VerificationCertificate
from identities.utils import normalize_identifier
from reports.forms import validate_file_upload, NIGERIAN_STATES

IDENTIFIER_DISPLAY_CHOICES = [
    ('', '-- None / Not Provided --'),
    ('property_ref', 'Land / Title / C of O / Survey Plan Number'),
    ('plate_vin', 'Vehicle Plate or VIN / Chassis Number'),
    ('cert_no', 'Degree / Certificate / Matriculation Number'),
    ('cac', 'CAC Registration Number (RC / BN)'),
    ('phone', 'Phone Number'),
    ('nin', 'National Identification Number (NIN)'),
    ('bvn', 'Bank Verification Number (BVN)'),
    ('email', 'Email Address'),
    ('account', 'Bank Account Number'),
]

class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """
    Custom form field supporting both single and multi-file uploads.
    Cleans individual files without raising 'No file was submitted. Check the encoding type on the form.'
    """
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput(attrs={
            'class': 'form-control',
            'id': 'id_supporting_document',
            'accept': '.pdf,.png,.jpg,.jpeg,.doc,.docx',
            'multiple': True,
        }))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data if d]
        else:
            cleaned = single_file_clean(data, initial)
            result = [cleaned] if cleaned else []
        return result


class VerificationRequestCreateForm(forms.Form):
    verification_type = forms.ChoiceField(
        choices=[('', '-- Select Verification Scope --')] + list(VerificationRequest.VERIFICATION_TYPES),
        required=True,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_verification_scope'})
    )
    subject_type = forms.ChoiceField(
        choices=[('', '-- Select Entity Type --')] + list(SubjectEntity.ENTITY_TYPES),
        required=True,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_entity_type'})
    )
    subject_name = forms.CharField(
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Plot 14 Block 2 Lekki Phase 1, Toyota Camry 2021, UNILAG Graduate Name, or Company Name'
        })
    )
    identifier_type = forms.ChoiceField(
        choices=IDENTIFIER_DISPLAY_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    identifier_value = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. C of O No, Plate No, VIN, Certificate Serial No, CAC RC No'
        })
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Describe the specific details to investigate. For property: state, location, surveyor plan, seller name. For car: model, chassis, plate. For certificate: university, graduation year, course.'
        })
    )
    document = MultipleFileField(
        required=False,
        help_text="Attach relevant documents (e.g. C of O, survey plan, vehicle customs paper, academic certificate, CAC document). Max 10MB per file (PDF, PNG, JPG, DOC)."
    )

    def clean(self):
        cleaned_data = super().clean()
        id_type = cleaned_data.get('identifier_type')
        id_val = cleaned_data.get('identifier_value')

        if id_type and not id_val:
            self.add_error('identifier_value', "Identifier value must be provided if identifier type is selected.")
        elif id_val and not id_type:
            self.add_error('identifier_type', "Identifier type must be selected when specifying an identifier value.")
        elif id_type and id_val:
            try:
                normalize_identifier(id_type, id_val)
            except ValueError as e:
                self.add_error('identifier_value', str(e))

        # Validate uploaded document(s)
        uploaded_files = cleaned_data.get('document') or []
        valid_files = []
        for upload in uploaded_files:
            try:
                validate_file_upload(upload)
                valid_files.append(upload)
            except ValidationError as e:
                self.add_error('document', e.message if hasattr(e, 'message') else str(e))
        cleaned_data['documents'] = valid_files

        return cleaned_data


class OfficerResolutionForm(forms.Form):
    outcome = forms.ChoiceField(
        choices=VerificationResult.OUTCOME_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    summary = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Official finding summary (e.g. Official search at Lands Bureau confirms C of O #45/45/2019 is genuine and registered to Alhaji Musa Bello. No active lis pendens or caveat recorded.)'
        })
    )
    registry_checked = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Lagos State Lands Bureau (Alausa), CAC Portal, UNILAG Senate Archive, FRSC'
        })
    )
    registration_ref = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. C of O #45/45/2019, RC 1234567, VIN / Chassis No, Certificate Serial #'
        })
    )
    confirmed_owner = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Verified Owner Name, Title Holder, or Degree Awardee'
        })
    )
    record_status = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Active & Clean (No Caveat), Valid & Genuine, Counterfeit / Fake, Under Court Dispute'
        })
    )
    advisory = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'e.g. Safe to proceed with purchase. Recommend physical beacon inspection.'
        })
    )
    details_json = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    def clean(self):
        cleaned_data = super().clean()
        details = {}
        if cleaned_data.get('registry_checked'):
            details['registry_checked'] = cleaned_data['registry_checked'].strip()
        if cleaned_data.get('registration_ref'):
            details['registration_ref'] = cleaned_data['registration_ref'].strip()
        if cleaned_data.get('confirmed_owner'):
            details['confirmed_owner'] = cleaned_data['confirmed_owner'].strip()
        if cleaned_data.get('record_status'):
            details['record_status'] = cleaned_data['record_status'].strip()
        if cleaned_data.get('advisory'):
            details['officer_advisory'] = cleaned_data['advisory'].strip()
        from django.utils import timezone
        details['inspection_date'] = timezone.now().strftime('%d %b %Y')
        cleaned_data['details_dict'] = details
        return cleaned_data


class OfficerRejectionForm(forms.Form):
    reason = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'State specific reason for rejecting/declining this verification request'
        })
    )

# ============================================================
# TrustPass (Background Clearance Certificate) Application Form
# ============================================================

class CertificateApplyForm(forms.Form):
    """
    Direct registration form for an individual to apply for an official
    VerifyNG TrustPass (Background Clearance Certificate) — DBS-style workflow.
    """
    # ── Step 1: Personal Profile 
    full_name = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Full legal name (First Middle Surname)',
            'autocomplete': 'name',
        }),
        help_text="Provide your full legal name as recorded on official identity documents."
    )
    date_of_birth = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
        })
    )
    gender = forms.ChoiceField(
        choices=[
            ('male', 'Male'),
            ('female', 'Female'),
            ('other', 'Other / Prefer not to say'),
        ],
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    phone_number = forms.CharField(
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. 08012345678 or +23480...',
            'autocomplete': 'tel',
        }),
        help_text="Nigerian mobile number (11 digits) or international format."
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'applicant@example.com',
            'autocomplete': 'email',
        })
    )

    # ── Step 2: National Identity & Document Proof 
    nin = forms.CharField(
        max_length=11,
        min_length=11,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control font-monospace',
            'placeholder': '11-digit National Identity Number',
            'maxlength': '11',
            'pattern': '[0-9]{11}',
            'inputmode': 'numeric',
        }),
        help_text="Your 11-digit NIN. Stored securely as an irreversible SHA-256 hash in compliance with NDPR."
    )
    id_document_type = forms.ChoiceField(
        choices=[
            ('nin_slip', 'National NIN Slip / NIMC Card'),
            ('drivers_license', "Federal Driver's License (FRSC)"),
            ('passport', 'International Passport (NIS)'),
            ('voters_card', "Permanent Voter's Card (INEC)"),
        ],
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    id_document_file = forms.FileField(
        required=False,
        widget=MultipleFileInput(attrs={
            'class': 'form-control',
            'accept': '.png,.jpg,.jpeg,.pdf',
        }),
        help_text="Optional document proof (PNG, JPG, PDF — max 10 MB)."
    )

    # ── Step 3: Clearance Level & Purpose 
    check_level = forms.ChoiceField(
        choices=VerificationCertificate.CHECK_LEVEL_CHOICES,
        required=True,
        initial='employment',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    employer_name = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Supermarket Ltd, Logistics Hub, or Personal Check',
        }),
        help_text="Company or prospective employer requesting this clearance."
    )
    job_role = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Delivery Driver, Cashier, Operations, Security',
        }),
        help_text="Proposed job designation or role."
    )
    residential_state = forms.ChoiceField(
        choices=NIGERIAN_STATES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    residential_city = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Ikeja, Wuse II, Port Harcourt',
        })
    )

    # ── Step 4: Legal Good-Faith Declaration
    declaration = forms.BooleanField(
        required=True,
        error_messages={'required': "You must accept the legal declaration before submission."}
    )

    # Backwards-compatibility fields (optional so existing tests or routes never fail)
    verification_reference = forms.CharField(max_length=50, required=False)
    certificate_type = forms.CharField(max_length=50, required=False)
    outcome_summary = forms.CharField(max_length=1000, required=False)

    def clean_nin(self):
        val = str(self.cleaned_data.get('nin', '')).strip()
        if not val.isdigit() or len(val) != 11:
            raise forms.ValidationError("NIN must consist of exactly 11 numeric digits.")
        return val

    def clean_phone_number(self):
        val = str(self.cleaned_data.get('phone_number', '')).strip()
        if val:
            try:
                return normalize_identifier('phone', val)
            except ValueError:
                raise forms.ValidationError(
                    "Invalid Nigerian phone number. Must be 11 digits starting with 0 or international +234 format."
                )
        return val

    def clean_id_document_file(self):
        file = self.cleaned_data.get('id_document_file')
        if file:
            return validate_file_upload(file)
        return file

class UpdateServiceLoginForm(forms.Form):
    """
    DBS-style credential login form for the Update Service.
    Authenticates certificate holder by Certificate Reference ID, Surname, and Date of Birth.
    """
    certificate_id = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control py-2 font-monospace',
            'placeholder': 'e.g. VNG-2026-99E1E30C',
            'autocomplete': 'off',
            'style': 'text-transform: uppercase;',
        })
    )
    surname = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control py-2',
            'placeholder': 'Enter your surname (as on certificate)',
            'autocomplete': 'family-name',
        })
    )
    date_of_birth = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={
            'class': 'form-control py-2',
            'type': 'date',
        })
    )



class UpdateServiceJoinForm(forms.Form):
    """
    Form to apply/join the Continuous Update Service for a certificate.
    Confirms contact details (email, phone, residential address) before Paystack checkout.
    """
    certificate_id = forms.CharField(
        max_length=64,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control py-2 font-monospace fw-bold',
            'placeholder': 'e.g. VNG-2026-99E1E30C',
            'style': 'text-transform: uppercase;',
            'readonly': 'readonly',
        })
    )
    full_name = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control py-2 bg-light',
            'readonly': 'readonly',
        })
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control py-2',
            'placeholder': 'name@example.com',
            'autocomplete': 'email',
        })
    )
    phone_number = forms.CharField(
        max_length=25,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control py-2',
            'placeholder': 'e.g. 08012345678',
            'autocomplete': 'tel',
        })
    )
    residential_address = forms.CharField(
        max_length=300,
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control py-2',
            'rows': 2,
            'placeholder': 'Enter your full residential address (Street, City, State)',
        })
    )
    declaration = forms.BooleanField(
        required=True,
        label="I confirm the contact details above are correct and request enrollment of this certificate into the Continuous Update Service."
    )
