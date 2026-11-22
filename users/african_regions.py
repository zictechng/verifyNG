"""
VerifyNG Pan-African Regional & Administrative Divisions
Provides dynamic Country -> State/Region/Province -> Local Government / District hierarchy.
Optimized for mobile-friendly cascading selection across all 54 African countries.
"""

from typing import Dict, Any, List, Optional

# Complete catalog of Nigerian 36 States + FCT and their 774 LGAs
NIGERIA_STATES_LGAS: Dict[str, List[str]] = {
    "Abia": [
        "Aba North", "Aba South", "Arochukwu", "Bende", "Ikwuano",
        "Isiala Ngwa North", "Isiala Ngwa South", "Isuikwuato", "Obi Ngwa",
        "Ohafia", "Osisioma", "Ugwunagbo", "Ukwa East", "Ukwa West",
        "Umuahia North", "Umuahia South", "Umu Nneochi"
    ],
    "Adamawa": [
        "Demsa", "Fufore", "Ganye", "Girei", "Gombi", "Guyuk", "Hong",
        "Jada", "Lamurde", "Madagali", "Maiha", "Mayo Belwa", "Michika",
        "Mubi North", "Mubi South", "Numan", "Shelleng", "Song", "Toungo",
        "Yola North", "Yola South"
    ],
    "Akwa Ibom": [
        "Abak", "Eastern Obolo", "Eket", "Esit Eket", "Essien Udim",
        "Etim Ekpo", "Etinan", "Ibeno", "Ibesikpo Asutan", "Ibiono Ibom",
        "Ika", "Ikono", "Ikot Abasi", "Ikot Ekpene", "Ini", "Itu", "Mbo",
        "Mkpat Enin", "Nsit Atai", "Nsit Ibom", "Nsit Ubium", "Obot Akara",
        "Okobo", "Onna", "Oron", "Oruk Anam", "Udung Uko", "Ukanafun",
        "Uruan", "Urue-Offong/Oruko", "Uyo"
    ],
    "Anambra": [
        "Aguata", "Anambra East", "Anambra West", "Anaocha", "Awka North",
        "Awka South", "Ayamelum", "Dunukofia", "Ekwusigo", "Idemili North",
        "Idemili South", "Ihiala", "Njikoka", "Nnewi North", "Nnewi South",
        "Ogbaru", "Onitsha North", "Onitsha South", "Orumba North",
        "Orumba South", "Oyi"
    ],
    "Bauchi": [
        "Alkaleri", "Bauchi", "Bogoro", "Damban", "Darazo", "Dass", "Gamawa",
        "Ganjuwa", "Giade", "Itas/Gadau", "Jama'are", "Katagum", "Kirfi",
        "Misau", "Ningi", "Shira", "Tafawa Balewa", "Toro", "Warji", "Zaki"
    ],
    "Bayelsa": [
        "Brass", "Ekeremor", "Kolokuma/Opokuma", "Nembe", "Ogbia",
        "Sagbama", "Southern Ijaw", "Yenagoa"
    ],
    "Benue": [
        "Ado", "Agatu", "Apa", "Buruku", "Gboko", "Guma", "Gwer East",
        "Gwer West", "Katsina-Ala", "Konshisha", "Kwande", "Logo", "Makurdi",
        "Obi", "Ogbadibo", "Ohimini", "Oju", "Okpokwu", "Otukpo", "Tarka",
        "Ukum", "Ushongo", "Vandeikya"
    ],
    "Borno": [
        "Abadam", "Askira/Uba", "Bama", "Bayo", "Biu", "Chibok", "Damboa",
        "Dikwa", "Gubio", "Guzamala", "Gwoza", "Hawul", "Jere", "Kaga",
        "Kala/Balge", "Konduga", "Kukawa", "Kwaya Kusar", "Mafa", "Magumeri",
        "Maiduguri", "Marte", "Mobbar", "Monguno", "Ngala", "Nganzai", "Shani"
    ],
    "Cross River": [
        "Abi", "Akamkpa", "Akpabuyo", "Bakassi", "Bekwarra", "Biase", "Boki",
        "Calabar Municipal", "Calabar South", "Etung", "Ikom", "Obanliku",
        "Obubra", "Obudu", "Odukpani", "Ogoja", "Yakuur", "Yala"
    ],
    "Delta": [
        "Aniocha North", "Aniocha South", "Bomadi", "Burutu", "Ethiope East",
        "Ethiope West", "Ika North East", "Ika South", "Isoko North",
        "Isoko South", "Ndokwa East", "Ndokwa West", "Okpe", "Oshimili North",
        "Oshimili South", "Patani", "Sapele", "Udu", "Ughelli North",
        "Ughelli South", "Ukwuani", "Uvwie", "Warri North", "Warri South",
        "Warri South West"
    ],
    "Ebonyi": [
        "Abakaliki", "Afikpo North", "Afikpo South", "Ebonyi", "Ezza North",
        "Ezza South", "Ikwo", "Ishielu", "Ivo", "Izzi", "Ohaozara",
        "Ohaukwu", "Onicha"
    ],
    "Edo": [
        "Akoko-Edo", "Egor", "Esan Central", "Esan North-East", "Esan South-East",
        "Esan West", "Etsako Central", "Etsako East", "Etsako West", "Igueben",
        "Ikpoba Okha", "Oredo", "Orhionmwon", "Ovia North-East", "Ovia South-West",
        "Owan East", "Owan West", "Uhunmwonde"
    ],
    "Ekiti": [
        "Ado Ekiti", "Efon", "Ekiti East", "Ekiti South-West", "Ekiti West",
        "Emure", "Gbonyin", "Ido Osi", "Ijero", "Ikole", "Ilejemeje",
        "Irepodun/Ifelodun", "Ise/Orun", "Moba", "Oye"
    ],
    "Enugu": [
        "Aninri", "Awgu", "Enugu East", "Enugu North", "Enugu South", "Ezeagu",
        "Igbo Etiti", "Igbo Eze North", "Igbo Eze South", "Isi Uzo", "Nkanu East",
        "Nkanu West", "Nsukka", "Oji River", "Udenu", "Udi", "Uzo Uwani"
    ],
    "FCT (Abuja)": [
        "Abaji", "Bwari", "Gwagwalada", "Kuje", "Kwali", "Municipal Area Council"
    ],
    "Gombe": [
        "Akko", "Balanga", "Billiri", "Dukku", "Funakaye", "Gombe", "Kaltungo",
        "Kwami", "Nafada", "Shongom", "Yamaltu/Deba"
    ],
    "Imo": [
        "Aboh Mbaise", "Ahiazu Mbaise", "Ehime Mbano", "Ezinihitte", "Ideato North",
        "Ideato South", "Ihitte/Uboma", "Ikeduru", "Isiala Mbano", "Isu",
        "Mbaitoli", "Ngor Okpala", "Njaba", "Nkwerre", "Nwangele", "Obowo",
        "Oguta", "Ohaji/Egbema", "Okigwe", "Onuimo", "Orlu", "Orsu", "Oru East",
        "Oru West", "Owerri Municipal", "Owerri North", "Owerri West"
    ],
    "Jigawa": [
        "Auyo", "Babura", "Biriniwa", "Birnin Kudu", "Buji", "Dutse", "Gagarawa",
        "Garki", "Gumel", "Guri", "Gwaram", "Gwiwa", "Hadejia", "Jahun",
        "Kafin Hausa", "Kaugama", "Kazaure", "Kiri Kasama", "Kiyawa", "Maigatari",
        "Malam Madori", "Miga", "Ringim", "Roni", "Sule Tankarkar", "Taura",
        "Yankwashi"
    ],
    "Kaduna": [
        "Birnin Gwari", "Chikun", "Giwa", "Igabi", "Ikara", "Jaba", "Jema'a",
        "Kachia", "Kaduna North", "Kaduna South", "Kagarko", "Kajuru", "Kaura",
        "Kauru", "Kubau", "Kudan", "Lere", "Makarfi", "Sabon Gari", "Sanga",
        "Soba", "Zangon Kataf", "Zaria"
    ],
    "Kano": [
        "Ajingi", "Albasu", "Bagwai", "Bebeji", "Bichi", "Bunkure", "Dala",
        "Dambatta", "Dawakin Kudu", "Dawakin Tofa", "Doguwa", "Fagge", "Gabasawa",
        "Garko", "Garun Mallam", "Gaya", "Gezawa", "Gwale", "Gwarzo", "Kabo",
        "Kano Municipal", "Karaye", "Kibiya", "Kiru", "Kumbotso", "Kunchi", "Kura",
        "Madobi", "Makoda", "Minjibir", "Nasarawa", "Rano", "Rimin Gado", "Rogo",
        "Shanono", "Sumaila", "Takai", "Tarauni", "Tofa", "Tsanyawa", "Tudun Wada",
        "Ungogo", "Warawa", "Wudil"
    ],
    "Katsina": [
        "Bakori", "Batagarawa", "Batsari", "Baure", "Bindawa", "Charanchi",
        "Dandume", "Danja", "Dan Musa", "Daura", "Dutsin Ma", "Faskari", "Funtua",
        "Ingawa", "Jibia", "Kafur", "Kaita", "Kankara", "Kankia", "Katsina",
        "Kurfi", "Kusada", "Mai'Adua", "Malumfashi", "Mani", "Mashi", "Matazu",
        "Musawa", "Rimi", "Sabuwa", "Safana", "Sandamu", "Zango"
    ],
    "Kebbi": [
        "Aleiro", "Arewa Dandi", "Argungu", "Augie", "Bagudo", "Birnin Kebbi",
        "Bunza", "Dandi", "Fakai", "Gwandu", "Jega", "Kalgo", "Koko/Besse",
        "Maiyama", "Ngaski", "Sakaba", "Shanga", "Suru", "Danko/Wasagu",
        "Yauri", "Zuru"
    ],
    "Kogi": [
        "Adavi", "Ajaokuta", "Ankpa", "Bassa", "Dekina", "Ibaji", "Idah",
        "Igalamela Odolu", "Ijumu", "Kabba/Bunu", "Koton Karfe", "Lokoja",
        "Mopa Muro", "Ofu", "Ogori/Magongo", "Okehi", "Okene", "Olamaboro",
        "Omala", "Yagba East", "Yagba West"
    ],
    "Kwara": [
        "Asa", "Baruten", "Edu", "Ekiti", "Ifelodun", "Ilorin East", "Ilorin South",
        "Ilorin West", "Irepodun", "Isin", "Kaiama", "Moro", "Offa", "Oke Ero",
        "Oyun", "Pategi"
    ],
    "Lagos": [
        "Agege", "Ajeromi-Ifelodun", "Alimosho", "Amuwo-Odofin", "Apapa", "Badagry",
        "Epe", "Eti Osa", "Ibeju-Lekki", "Ifako-Ijaiye", "Ikeja", "Ikorodu",
        "Kosofe", "Lagos Island", "Lagos Mainland", "Mushin", "Ojo",
        "Oshodi-Isolo", "Shomolu", "Surulere"
    ],
    "Nasarawa": [
        "Akwanga", "Awe", "Doma", "Karu", "Keana", "Keffi", "Kokona", "Lafia",
        "Nasarawa", "Nasarawa Egon", "Obi", "Toto", "Wamba"
    ],
    "Niger": [
        "Agaie", "Agwara", "Bida", "Borgu", "Bosso", "Chanchaga", "Edati",
        "Gbako", "Gurara", "Katcha", "Kontagora", "Lapai", "Lavun", "Magama",
        "Mariga", "Mashegu", "Mokwa", "Moya", "Paikoro", "Rafi", "Rijau",
        "Shiroro", "Suleja", "Tafa", "Wushishi"
    ],
    "Ogun": [
        "Abeokuta North", "Abeokuta South", "Ado-Odo/Ota", "Ewekoro", "Ifo",
        "Ijebu East", "Ijebu North", "Ijebu North East", "Ijebu Ode", "Ikenne",
        "Imeko Afon", "Ipokia", "Obafemi Owode", "Odeda", "Odogbolu",
        "Ogun Waterside", "Remo North", "Shagamu", "Yewa North", "Yewa South"
    ],
    "Ondo": [
        "Akoko North-East", "Akoko North-West", "Akoko South-East", "Akoko South-West",
        "Akure North", "Akure South", "Ese Odo", "Idanre", "Ifedore", "Ilaje",
        "Ile Oluji/Okeigbo", "Irele", "Odigbo", "Okitipupa", "Ondo East",
        "Ondo West", "Ose", "Owo"
    ],
    "Osun": [
        "Atakunmosa East", "Atakunmosa West", "Aiyedaade", "Aiyedire", "Boluwaduro",
        "Boripe", "Ede North", "Ede South", "Ife Central", "Ife East", "Ife North",
        "Ife South", "Egbedore", "Ejigbo", "Ifelodun", "Ila", "Ilesa East",
        "Ilesa West", "Irepodun", "Irewole", "Isokan", "Iwo", "Obokun",
        "Odo Otin", "Ola Oluwa", "Olorunda", "Oriade", "Orolu", "Osogbo"
    ],
    "Oyo": [
        "Afijio", "Akinyele", "Atiba", "Atisbo", "Egbeda", "Ibadan North",
        "Ibadan North-East", "Ibadan North-West", "Ibadan South-East",
        "Ibadan South-West", "Ibarapa Central", "Ibarapa East", "Ibarapa North",
        "Ido", "Irepo", "Iseyin", "Itesiwaju", "Iwajowa", "Kajola", "Lagelu",
        "Ogbomosho North", "Ogbomosho South", "Ogo Oluwa", "Olorunsogo", "Oluyole",
        "Ona Ara", "Orelope", "Ori Ire", "Oyo East", "Oyo West", "Saki East",
        "Saki West", "Surulere"
    ],
    "Plateau": [
        "Barkin Ladi", "Bassa", "Bokkos", "Jos East", "Jos North", "Jos South",
        "Kanam", "Kanke", "Langtang North", "Langtang South", "Mangu", "Mikang",
        "Pankshin", "Qua'an Pan", "Riyom", "Shendam", "Wase"
    ],
    "Rivers": [
        "Abua/Odual", "Ahoada East", "Ahoada West", "Akuku-Toru", "Andoni",
        "Asari-Toru", "Bonny", "Degema", "Eleme", "Emuoha", "Etche", "Gokana",
        "Ikwerre", "Khana", "Obio/Akpor", "Ogba/Egbema/Ndoni", "Ogu/Bolo",
        "Okrika", "Omuma", "Opobo/Nkoro", "Oyigbo", "Port Harcourt", "Tai"
    ],
    "Sokoto": [
        "Binji", "Bodinga", "Dange Shuni", "Gada", "Goronyo", "Gudu", "Gawabawa",
        "Illela", "Isa", "Kebbe", "Kware", "Rabah", "Sabon Birni", "Shagari",
        "Silame", "Sokoto North", "Sokoto South", "Tambuwal", "Tangaza", "Tureta",
        "Wamako", "Wurno", "Yabo"
    ],
    "Taraba": [
        "Ardo Kola", "Bali", "Donga", "Gashaka", "Gassol", "Ibi", "Jalingo",
        "Karim Lamido", "Kurmi", "Lau", "Sardauna", "Takum", "Ussa", "Wukari",
        "Yorro", "Zing"
    ],
    "Yobe": [
        "Bade", "Bursari", "Damaturu", "Fika", "Fune", "Geidam", "Gujba", "Gulani",
        "Jakusko", "Karasuwa", "Machina", "Nangere", "Nguru", "Potiskum",
        "Tarmuwa", "Yunusari", "Yusufari"
    ],
    "Zamfara": [
        "Anka", "Bakura", "Birnin Magaji/Kiyaw", "Bukkuyum", "Bungudu", "Gummi",
        "Gusau", "Kaura Namoda", "Maradun", "Maru", "Shinkafi", "Talata Mafara",
        "Tsafe", "Zurmi"
    ]
}

# Pan-African Regional Configurations
AFRICAN_REGIONS_CATALOG: Dict[str, Dict[str, Any]] = {
    "NG": {
        "state_label": "State",
        "lga_label": "Local Government Area (LGA)",
        "lga_mode": "dropdown",  # Has full cascading LGA dropdown list
        "states": list(NIGERIA_STATES_LGAS.keys()),
        "lgas": NIGERIA_STATES_LGAS,
    },
    "GH": {
        "state_label": "Region",
        "lga_label": "District / Municipal Area",
        "lga_mode": "input",
        "states": [
            "Ahafo", "Ashanti", "Bono", "Bono East", "Central", "Eastern",
            "Greater Accra", "North East", "Northern", "Oti", "Savannah",
            "Upper East", "Upper West", "Volta", "Western", "Western North"
        ],
        "lgas": {},
    },
    "KE": {
        "state_label": "County",
        "lga_label": "Sub-County / Area",
        "lga_mode": "input",
        "states": [
            "Baringo", "Bomet", "Bungoma", "Busia", "Elgeyo-Marakwet", "Embu",
            "Garissa", "Homa Bay", "Isiolo", "Kajiado", "Kakamega", "Kericho",
            "Kiambu", "Kilifi", "Kirinyaga", "Kisii", "Kisumu", "Kitui", "Kwale",
            "Laikipia", "Lamu", "Machakos", "Makueni", "Mandera", "Marsabit",
            "Meru", "Migori", "Mombasa", "Murang'a", "Nairobi", "Nakuru", "Nandi",
            "Narok", "Nyamira", "Nyandarua", "Nyeri", "Samburu", "Siaya",
            "Taita-Taveta", "Tana River", "Tharaka-Nithi", "Trans Nzoia",
            "Turkana", "Uasin Gishu", "Vihiga", "Wajir", "West Pokot"
        ],
        "lgas": {},
    },
    "ZA": {
        "state_label": "Province",
        "lga_label": "Municipality / City",
        "lga_mode": "input",
        "states": [
            "Eastern Cape", "Free State", "Gauteng", "KwaZulu-Natal",
            "Limpopo", "Mpumalanga", "North West", "Northern Cape", "Western Cape"
        ],
        "lgas": {},
    },
    "EG": {
        "state_label": "Governorate",
        "lga_label": "City / District",
        "lga_mode": "input",
        "states": [
            "Alexandria", "Aswan", "Asyut", "Beheira", "Beni Suef", "Cairo",
            "Dakahlia", "Damietta", "Faiyum", "Gharbia", "Giza", "Ismailia",
            "Kafr El Sheikh", "Luxor", "Matrouh", "Minya", "Monufia",
            "New Valley", "North Sinai", "Port Said", "Qalyubia", "Qena",
            "Red Sea", "Sharqia", "Sohag", "South Sinai", "Suez"
        ],
        "lgas": {},
    },
    "RW": {
        "state_label": "Province",
        "lga_label": "District",
        "lga_mode": "input",
        "states": [
            "Kigali City", "Eastern Province", "Northern Province",
            "Southern Province", "Western Province"
        ],
        "lgas": {},
    },
    "CM": {
        "state_label": "Region",
        "lga_label": "Department / Division",
        "lga_mode": "input",
        "states": [
            "Adamawa", "Centre", "East", "Far North", "Littoral", "North",
            "North-West", "South", "South-West", "West"
        ],
        "lgas": {},
    },
    "UG": {
        "state_label": "Region",
        "lga_label": "District / Municipality",
        "lga_mode": "input",
        "states": ["Central Region", "Eastern Region", "Northern Region", "Western Region"],
        "lgas": {},
    },
    "TZ": {
        "state_label": "Region",
        "lga_label": "District / City",
        "lga_mode": "input",
        "states": [
            "Arusha", "Dar es Salaam", "Dodoma", "Geita", "Iringa", "Kagera",
            "Katavi", "Kigoma", "Kilimanjaro", "Lindi", "Manyara", "Mara",
            "Mbeya", "Morogoro", "Mtwara", "Mwanza", "Njombe", "Pemba North",
            "Pemba South", "Pwani", "Rukwa", "Ruvuma", "Shinyanga", "Simiyu",
            "Singida", "Songwe", "Tabora", "Tanga", "Zanzibar North",
            "Zanzibar South", "Zanzibar West"
        ],
        "lgas": {},
    },
    "SN": {
        "state_label": "Region",
        "lga_label": "Department / City",
        "lga_mode": "input",
        "states": [
            "Dakar", "Diourbel", "Fatick", "Kaffrine", "Kaolack", "Kédougou",
            "Kolda", "Louga", "Matam", "Saint-Louis", "Sédhiou", "Tambacounda",
            "Thiès", "Ziguinchor"
        ],
        "lgas": {},
    },
    "CI": {
        "state_label": "District",
        "lga_label": "Region / City",
        "lga_mode": "input",
        "states": [
            "Abidjan", "Bas-Sassandra", "Comoé", "Denguélé", "Gôh-Djiboua",
            "Lacs", "Lagunes", "Montagnes", "Sassandra-Marahoué", "Savanes",
            "Vallée du Bandama", "Woroba", "Yamoussoukro", "Zanzan"
        ],
        "lgas": {},
    },
    "ET": {
        "state_label": "Region",
        "lga_label": "Zone / Woreda",
        "lga_mode": "input",
        "states": [
            "Addis Ababa", "Afar", "Amhara", "Benishangul-Gumuz", "Dire Dawa",
            "Gambela", "Harari", "Oromia", "Sidama", "Somali",
            "South West Ethiopia", "Southern Nations", "Tigray"
        ],
        "lgas": {},
    },
    "MA": {
        "state_label": "Region",
        "lga_label": "Province / Prefecture",
        "lga_mode": "input",
        "states": [
            "Béni Mellal-Khénifra", "Casablanca-Settat", "Dakhla-Oued Ed-Dahab",
            "Drâa-Tafilalet", "Fès-Meknès", "Guelmim-Oued Noun", "Laâyoune-Sakia El Hamra",
            "Marrakech-Safi", "Oriental", "Rabat-Salé-Kénitra", "Souss-Massa",
            "Tanger-Tétouan-Al Hoceïma"
        ],
        "lgas": {},
    }
}

DEFAULT_AFRICAN_REGION_CONFIG: Dict[str, Any] = {
    "state_label": "State / Province / Region",
    "lga_label": "City / District / Area",
    "lga_mode": "input",
    "states": [],
    "lgas": {},
}


def get_african_region_config(country_code: Optional[str]) -> Dict[str, Any]:
    """Returns region and district config for a given ISO country code."""
    if not country_code:
        return DEFAULT_AFRICAN_REGION_CONFIG
    code = country_code.strip().upper()
    return AFRICAN_REGIONS_CATALOG.get(code, DEFAULT_AFRICAN_REGION_CONFIG)


def get_all_african_regions_catalog() -> Dict[str, Any]:
    """Returns full catalog dictionary for client-side serialization."""
    return AFRICAN_REGIONS_CATALOG
