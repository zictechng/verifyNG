import os, base64
from django import forms
from django.core.files.base import ContentFile
from django.utils.text import slugify
from payments.models import MerchantProfile, NigerianBank
from payments.bank_services import resolve_bank_account

class MerchantApplicationForm(forms.ModelForm):
    # Live webcam photo (captured as base64 data url from frontend)
    webcam_selfie_data = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )
    
    # Store category choices (Comprehensive & inclusive)
    CATEGORY_CHOICES = [
        ('tech_software', 'Software, Web, Mobile & Tech Services'),
        ('fashion', 'Fashion, Clothing & Apparel'),
        ('beauty', 'Beauty, Cosmetics & Hair Care'),
        ('electronics', 'Phones, Computers & Gadgets'),
        ('groceries', 'Food, Pastries, Catering & Groceries'),
        ('home_living', 'Furniture, Home Decor & Interior Design'),
        ('creative_media', 'Media, Photography, Design & Branding'),
        ('services', 'Digital, Freelance & Professional Services'),
        ('consulting_legal', 'Legal, Financial & Business Advisory'),
        ('automotive', 'Automobile, Spare Parts & Logistics'),
        ('real_estate', 'Real Estate, Rentals & Construction'),
        ('education', 'Education, Coaching, Training & Books'),
        ('health', 'Health, Pharmacy, Fitness & Wellness'),
        ('travel_hospitality', 'Travel, Tourism & Hospitality'),
        ('agriculture', 'Agriculture, Agro-commodities & Livestock'),
        ('crafts_art', 'Art, Crafts, Gifts & Souvenirs'),
        ('other', 'General Retail, Commercial Goods & Other'),
    ]
    category = forms.ChoiceField(
        choices=CATEGORY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'merchantCategory'})
    )

    # Social links
    instagram_handle = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '@yourstore or instagram.com/yourstore'})
    )
    tiktok_handle = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '@yourstore or tiktok.com/@yourstore'})
    )
    facebook_handle = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'facebook.com/yourstore or Page Name'})
    )
    twitter_handle = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '@yourhandle or x.com/yourhandle'})
    )
    threads_handle = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '@yourhandle or threads.net/@yourhandle'})
    )
    youtube_handle = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'youtube.com/@yourchannel'})
    )
    linkedin_handle = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'linkedin.com/company/yourstore'})
    )

    # Nigerian States Choices
    STATE_CHOICES = [
        ('', '-- Select Operating State --'),
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
    operating_state = forms.ChoiceField(
        choices=STATE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'merchantOperatingState'})
    )

    class Meta:
        model = MerchantProfile
        fields = [
            'merchant_type',
            'store_name',
            'store_slug',
            'category',
            'description',
            'logo_image',
            'display_location',
            'operating_state',
            'city_town',
            'physical_address',
            'whatsapp_number',
            'website_or_linktree',
            'bank_name',
            'bank_account',
            'display_bank_on_seal',
            'selfie_image',
        ]
        widgets = {
            'merchant_type': forms.RadioSelect(attrs={'class': 'btn-check'}),
            'store_name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'e.g. Glam Store Nigeria',
                'id': 'merchantStoreName',
                'required': 'required'
            }),
            'store_slug': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. glamstore',
                'id': 'merchantStoreSlug',
                'required': 'required'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Brief description of what your store or brand offers to customers...'
            }),
            'city_town': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Ikeja, Lekki, Benin City, Wuse 2',
                'id': 'merchantCityTown'
            }),
            'physical_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Suite 4, Plaza B, Allen Avenue (Optional)',
                'id': 'merchantPhysicalAddress'
            }),
            'whatsapp_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. +234 801 234 5678',
                'id': 'merchantWhatsapp'
            }),
            'website_or_linktree': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://yourstore.com or https://linktr.ee/yourstore'
            }),
            'bank_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Select or type your bank name',
                'id': 'merchantBankName',
                'required': 'required'
            }),
            'bank_account': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '10-digit NUBAN account number',
                'id': 'merchantBankAccount',
                'maxlength': '10',
                'required': 'required'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # If merchant is already active and verified, lock critical identity fields:
        # store_slug and bank fields cannot be tampered with directly via standard form
        if self.instance and self.instance.pk and self.instance.status == 'active':
            if 'store_slug' in self.fields:
                self.fields['store_slug'].widget.attrs['readonly'] = 'readonly'
                self.fields['store_slug'].widget.attrs['disabled'] = 'disabled'
                self.fields['store_slug'].required = False
            if 'bank_name' in self.fields:
                self.fields['bank_name'].widget.attrs['readonly'] = 'readonly'
                self.fields['bank_name'].widget.attrs['disabled'] = 'disabled'
                self.fields['bank_name'].required = False
            if 'bank_account' in self.fields:
                self.fields['bank_account'].widget.attrs['readonly'] = 'readonly'
                self.fields['bank_account'].widget.attrs['disabled'] = 'disabled'
                self.fields['bank_account'].required = False

        # Make selfie_image field optional at standard model field level
        # so custom validation in clean() can allow either live webcam base64, 
        # an uploaded file, an existing photo, or CAC business exemption.
        if 'selfie_image' in self.fields:
            self.fields['selfie_image'].required = False

        # Populate initial social links if existing instance
        if self.instance and self.instance.pk and self.instance.social_links:
            links = self.instance.social_links
            for key in ['instagram', 'tiktok', 'facebook', 'twitter', 'threads', 'youtube', 'linkedin']:
                field_name = f"{key}_handle"
                if field_name in self.fields and key in links:
                    self.fields[field_name].initial = links[key]

    def clean_store_slug(self):
        # If already active, strictly preserve original store slug
        if self.instance and self.instance.pk and self.instance.status == 'active':
            return self.instance.store_slug

        slug = self.cleaned_data.get('store_slug', '').strip().lower()
        if not slug:
            store_name = self.cleaned_data.get('store_name', '')
            slug = slugify(store_name)
        
        slug = slugify(slug)
        if not slug or len(slug) < 3:
            raise forms.ValidationError("Store slug must be at least 3 alphanumeric characters.")
        
        # Reserved keywords check
        reserved = {'admin', 'api', 'portal', 'auth', 'login', 'register', 'dashboard', 'trust', 'verify', 'v', 'report', 'dispute'}
        if slug in reserved:
            raise forms.ValidationError(f"'{slug}' is a reserved URL path. Please choose another username/slug.")

        # Check unique constraint excluding self
        qs = MerchantProfile.objects.filter(store_slug__iexact=slug)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"The handle '@{slug}' is already registered. Please choose another slug.")

        return slug

    def clean_bank_account(self):
        # If already active, preserve existing verified bank account
        if self.instance and self.instance.pk and self.instance.status == 'active':
            return self.instance.bank_account

        acct = self.cleaned_data.get('bank_account', '').strip()
        if not (acct.isdigit() and len(acct) == 10):
            raise forms.ValidationError("Settlement account number must be exactly 10 numeric digits.")
        return acct

    def clean(self):
        cleaned_data = super().clean()
        merchant_type = cleaned_data.get('merchant_type')
        webcam_data = cleaned_data.get('webcam_selfie_data')
        selfie_file = cleaned_data.get('selfie_image')
        bank_name = cleaned_data.get('bank_name')
        bank_account = cleaned_data.get('bank_account')

        # Individual sellers MUST provide either a live webcam selfie or upload a selfie
        if merchant_type == 'individual':
            if not webcam_data and not selfie_file and (not self.instance or not self.instance.selfie_image):
                self.add_error('selfie_image', "Individual vendors are required to capture a live webcam selfie or upload a clear photo holding your ID.")
        elif merchant_type in ('business', 'cac_business'):
            # For CAC corporate accounts, personal selfie is optional since corporate directors are vetted via CAC
            pass

        # Auto-resolve bank account via NIBSS/Paystack/Database (only for new or unapproved profiles)
        if self.instance and self.instance.pk and self.instance.status == 'active':
            cleaned_data['bank_name'] = self.instance.bank_name
            cleaned_data['bank_account'] = self.instance.bank_account
            cleaned_data['bank_code'] = self.instance.bank_code
            cleaned_data['bank_account_name'] = self.instance.bank_account_name
        elif bank_name and bank_account and len(bank_account) == 10:
            res = resolve_bank_account(bank_account, bank_name)
            if res.get('success'):
                cleaned_data['bank_account_name'] = res.get('account_name')
                cleaned_data['bank_code'] = res.get('bank_code', '')
            else:
                # If resolution fails, attach error to bank account
                self.add_error('bank_account', res.get('message', 'Unable to verify account details with bank. Check account number and bank name.'))

        # Pack social handles into social_links dict
        socials = {}
        for key in ['instagram', 'tiktok', 'facebook', 'twitter', 'threads', 'youtube', 'linkedin']:
            val = cleaned_data.get(f"{key}_handle", '')
            if val:
                val = val.strip()
                if val:
                    socials[key] = val
        cleaned_data['cleaned_social_links'] = socials

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user and not instance.user_id:
            instance.user = self.user

        # Apply resolved bank details
        if 'bank_account_name' in self.cleaned_data and self.cleaned_data['bank_account_name']:
            instance.bank_account_name = self.cleaned_data['bank_account_name']
        if 'bank_code' in self.cleaned_data and self.cleaned_data['bank_code']:
            instance.bank_code = self.cleaned_data['bank_code']

        # Apply social links dictionary
        if 'cleaned_social_links' in self.cleaned_data:
            instance.social_links = self.cleaned_data['cleaned_social_links']

        # Handle webcam selfie base64 if supplied
        webcam_data = self.cleaned_data.get('webcam_selfie_data')
        if webcam_data and 'base64,' in webcam_data:
            try:
                format_part, imgstr = webcam_data.split(';base64,')
                ext = format_part.split('/')[-1] if '/' in format_part else 'jpg'
                file_name = f"merchant_selfie_{instance.user_id or 'webcam'}_{instance.store_slug}.{ext}"
                instance.selfie_image.save(file_name, ContentFile(base64.b64decode(imgstr)), save=False)
            except Exception:
                pass

        if commit:
            instance.save()
        return instance
