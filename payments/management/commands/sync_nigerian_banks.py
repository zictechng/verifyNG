import requests
from django.core.management.base import BaseCommand
from payments.models import NigerianBank
from django.utils.text import slugify

CORE_BANKS = [
    ("Access Bank", "044"),
    ("Citibank Nigeria", "023"),
    ("Ecobank Nigeria", "050"),
    ("Fidelity Bank", "070"),
    ("First Bank of Nigeria", "011"),
    ("First City Monument Bank (FCMB)", "214"),
    ("Guaranty Trust Bank (GTBank)", "058"),
    ("Heritage Bank", "030"),
    ("Jaiz Bank", "301"),
    ("Keystone Bank", "082"),
    ("Kuda Bank", "50211"),
    ("Moniepoint MFB", "50515"),
    ("OPay Digital Services (OPay)", "999992"),
    ("PalmPay", "999991"),
    ("Polaris Bank", "076"),
    ("Providus Bank", "101"),
    ("Stanbic IBTC Bank", "221"),
    ("Standard Chartered Bank", "068"),
    ("Sterling Bank", "232"),
    ("Taj Bank", "302"),
    ("Titan Trust Bank", "102"),
    ("Union Bank of Nigeria", "032"),
    ("United Bank for Africa (UBA)", "033"),
    ("Unity Bank", "215"),
    ("Wema Bank", "035"),
    ("Zenith Bank", "057"),
    ("Rubies MFB", "125"),
    ("VFD Microfinance Bank", "566"),
    ("Sparkle Microfinance Bank", "51310"),
    ("Eyowo", "50126"),
]

class Command(BaseCommand):
    help = "Syncs official Nigerian banks list from Paystack with offline fallback."

    def handle(self, *args, **options):
        self.stdout.write("Syncing Nigerian banks from Paystack directory...")
        synced_count = 0
        try:
            resp = requests.get('https://api.paystack.co/bank', timeout=12)
            if resp.status_code == 200:
                banks = resp.json().get('data', [])
                for b in banks:
                    name = b.get('name', '').strip()
                    code = b.get('code', '').strip()
                    nibss = b.get('nibss_bank_code', '') or ''
                    if name and code:
                        NigerianBank.objects.update_or_create(
                            code=code,
                            defaults={
                                'name': name,
                                'slug': slugify(name),
                                'nibss_code': nibss,
                                'is_active': True
                            }
                        )
                        synced_count += 1
                self.stdout.write(self.style.SUCCESS(f"Successfully synced {synced_count} banks from Paystack API."))
                return
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Live sync unreachable ({exc}). Applying offline core banks..."))

        # Fallback seeding
        for name, code in CORE_BANKS:
            NigerianBank.objects.update_or_create(
                code=code,
                defaults={
                    'name': name,
                    'slug': slugify(name),
                    'is_active': True
                }
            )
            synced_count += 1
        self.stdout.write(self.style.SUCCESS(f"Seeded {synced_count} core Nigerian banks into database."))
