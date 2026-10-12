
import json
from django import forms
from django.core.exceptions import ValidationError
from verification.models import VerificationRequest, VerificationResult
from identities.models import SubjectEntity
from identities.utils import SUPPORTED_IDENTIFIER_TYPES, normalize_identifier


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




# ── W-08: Certificate Application Form ────────────────────────────────────────
class CertificateApplyForm(forms.Form):
    CHECK_LEVEL_CHOICES = (
        ('employment', 'Employment Check — for general work and tenancy'),
        ('enhanced',   'Enhanced Check — for security, healthcare, and senior roles'),
    )

    check_level = forms.ChoiceField(
        choices=CHECK_LEVEL_CHOICES,
        label='Certificate Level',
        help_text='Choose the level appropriate for your role and industry.',
        widget=forms.RadioSelect,
    )

    def clean_check_level(self):
        value = self.cleaned_data.get('check_level')
        valid = {'employment', 'enhanced'}
        if value not in valid:
            raise forms.ValidationError("Invalid certificate level selected.")
        return value




