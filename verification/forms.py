
import json
from django import forms
from django.core.exceptions import ValidationError
from verification.models import VerificationRequest, VerificationResult
from identities.models import SubjectEntity
from identities.utils import SUPPORTED_IDENTIFIER_TYPES, normalize_identifier
from verification.models import VerificationCertificate

class VerificationRequestCreateForm(forms.Form):
    subject_name = forms.CharField(
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Full legal person name or registered business name'
        })
    )
    subject_type = forms.ChoiceField(
        choices=SubjectEntity.ENTITY_TYPES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    verification_type = forms.ChoiceField(
        choices=VerificationRequest.VERIFICATION_TYPES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    identifier_type = forms.ChoiceField(
        choices=[('', 'None / Not Provided')] + [(t, t.upper()) for t in sorted(SUPPORTED_IDENTIFIER_TYPES)],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    identifier_value = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Phone number, CAC RC number, or Email'
        })
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Provide any contextual background or specific verification requirements'
        })
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
            'rows': 4,
            'placeholder': 'Executive summary of findings (e.g. verified CAC status, confirmed employment record)'
        })
    )
    details_json = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control font-monospace',
            'rows': 4,
            'placeholder': '{\n  "registry_status": "Active",\n  "registration_date": "2020-01-15"\n}'
        }),
        help_text="Optional JSON object containing structured factual findings."
    )

    def clean_details_json(self):
        data = self.cleaned_data.get('details_json')
        if not data or not data.strip():
            return {}
        try:
            parsed = json.loads(data)
            if not isinstance(parsed, dict):
                raise ValidationError("Structured findings must be a valid JSON object (dictionary).")
            return parsed
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON syntax: {str(e)}")


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
# W-08: Certificate application form
# ============================================================

class CertificateApplyForm(forms.Form):
    """
    Form for a user to apply for a VerificationCertificate
    against one of their completed VerificationRequests.
    """
    verification_reference = forms.CharField(
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control font-monospace',
            'placeholder': 'e.g. VNG-VR-20261001-AB12',
        }),
        help_text="The reference number of your completed verification request."
    )
    certificate_type = forms.ChoiceField(
        choices=VerificationCertificate.CERTIFICATE_TYPES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    outcome_summary = forms.CharField(
        required=True,
        max_length=1000,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Brief plain-language summary of the verification outcome to appear on the certificate.'
        }),
        help_text="This summary will be printed on the issued certificate."
    )




