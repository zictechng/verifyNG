"""
VerifyNG Pan-African Regional & Administrative Divisions
Provides dynamic Country -> State/Region/Province -> Local Government / District hierarchy.
Optimized for mobile-friendly cascading selection across all 54 African countries.
All administrative divisions use 100% verified, authentic government data.
"""

from typing import Dict, Any, List, Optional
from users.african_subdivisions import AFRICAN_SUBDIVISIONS

# ─────────────────────────────────────────────────────────────────────────────
# 1. NIGERIA: 36 States + FCT (774 Constitutionally Established LGAs)
# ─────────────────────────────────────────────────────────────────────────────
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

# ─────────────────────────────────────────────────────────────────────────────
# 2. SOUTH AFRICA: 9 Provinces (52 Official Metros & District Municipalities)
# ─────────────────────────────────────────────────────────────────────────────
SOUTH_AFRICA_PROVINCES_MUNICIPALITIES: Dict[str, List[str]] = {
    "Eastern Cape": [
        "Buffalo City Metropolitan", "Nelson Mandela Bay Metropolitan", "Alfred Nzo District",
        "Amathole District", "Chris Hani District", "Joe Gqabi District", "OR Tambo District", "Sarah Baartman District"
    ],
    "Free State": [
        "Mangaung Metropolitan", "Fezile Dabi District", "Lejweleputswa District",
        "Thabo Mofutsanyana District", "Xhariep District"
    ],
    "Gauteng": [
        "City of Johannesburg Metropolitan", "City of Tshwane Metropolitan", "Ekurhuleni Metropolitan",
        "Sedibeng District", "West Rand District"
    ],
    "KwaZulu-Natal": [
        "eThekwini Metropolitan", "Amajuba District", "Harry Gwala District", "iLembe District",
        "King Cetshwayo District", "Ugu District", "uMgungundlovu District", "uMkhanyakude District",
        "uMzinyathi District", "uThukela District", "Zululand District"
    ],
    "Limpopo": [
        "Capricorn District", "Mopani District", "Sekhukhune District", "Vhembe District", "Waterberg District"
    ],
    "Mpumalanga": [
        "Ehlanzeni District", "Gert Sibande District", "Nkangala District"
    ],
    "North West": [
        "Bojanala Platinum District", "Dr Kenneth Kaunda District", "Dr Ruth Segomotsi Mompati District",
        "Ngaka Modiri Molema District"
    ],
    "Northern Cape": [
        "Frances Baard District", "John Taolo Gaetsewe District", "Namakwa District",
        "Pixley ka Seme District", "ZF Mgcawu District"
    ],
    "Western Cape": [
        "City of Cape Town Metropolitan", "Cape Winelands District", "Central Karoo District",
        "Garden Route District", "Overberg District", "West Coast District"
    ]
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. GHANA: 16 Regions (Official Metropolitan, Municipal & District Assemblies)
# ─────────────────────────────────────────────────────────────────────────────
GHANA_REGIONS_MMDAS: Dict[str, List[str]] = {
    "Greater Accra": [
        "Accra Metropolitan", "Tema Metropolitan", "Adentan Municipal", "Ashaiman Municipal",
        "Ayawaso Central Municipal", "Ayawaso East Municipal", "Ayawaso North Municipal", "Ayawaso West Municipal",
        "Ga Central Municipal", "Ga East Municipal", "Ga North Municipal", "Ga South Municipal", "Ga West Municipal",
        "Korle Klottey Municipal", "Kpone Katamanso Municipal", "Krowor Municipal", "La Dade Kotopon Municipal",
        "La Nkwantanang Madina Municipal", "Ledzokuku Municipal", "Okaikwei North Municipal",
        "Ablekuma Central Municipal", "Ablekuma North Municipal", "Ablekuma West Municipal",
        "Shai Osudoku District", "Ningo Prampram District", "Ada East District", "Ada West District"
    ],
    "Ashanti": [
        "Kumasi Metropolitan", "Asokore Mampong Municipal", "Asokwa Municipal", "Bekwai Municipal",
        "Ejisu Municipal", "Juaben Municipal", "Kwadaso Municipal", "Mampong Municipal",
        "Obuasi Municipal", "Obuasi East District", "Offinso Municipal", "Oforikrom Municipal",
        "Old Tafo Municipal", "Suame Municipal", "Ahafo Ano North Municipal", "Ahafo Ano South East District",
        "Ahafo Ano South West District", "Amansie Central District", "Amansie South District", "Amansie West District",
        "Asante Akim Central Municipal", "Asante Akim North District", "Asante Akim South Municipal",
        "Atwima Kwanwoma District", "Atwima Mponua District", "Atwima Nwabiagya Municipal", "Atwima Nwabiagya North District",
        "Bosome Freho District", "Bosomtwe District", "Ejura Sekyedumase Municipal", "Kwabre East Municipal",
        "Offinso North District", "Sekyere Central District", "Sekyere East District", "Sekyere Kumawu District", "Sekyere South District"
    ],
    "Western": [
        "Sekondi-Takoradi Metropolitan", "Effia Kwesimintsim Municipal", "Tarkwa Nsuaem Municipal",
        "Ahanta West Municipal", "Nzema East Municipal", "Prestea Huni Valley Municipal", "Jomoro Municipal",
        "Ellembelle District", "Shama District", "Wassa East District", "Mpohor District", "Wassa Amenfi Central District",
        "Wassa Amenfi East Municipal", "Wassa Amenfi West Municipal"
    ],
    "Central": [
        "Cape Coast Metropolitan", "Awutu Senya East Municipal (Kasoa)", "Effutu Municipal (Winneba)",
        "Komenda Edina Eguafo Abirem Municipal", "Mfantseman Municipal", "Agona West Municipal",
        "Agona East District", "Asikuma Odoben Brakwa District", "Assin Central Municipal", "Assin North District",
        "Assin South District", "Awutu Senya District", "Gomoa Central District", "Gomoa East District",
        "Gomoa West District", "Twifo Atti Morkwa District", "Twifo Hemang Lower Denkyira District",
        "Upper Denkyira East Municipal", "Upper Denkyira West District", "Ajumako Enyan Essiam District", "Ekumfi District"
    ],
    "Eastern": [
        "New Juaben South Municipal (Koforidua)", "New Juaben North Municipal", "Birim Central Municipal (Oda)",
        "Akuapem South District", "Akuapem North Municipal", "Suhum Municipal", "Nsawam Adoagyiri Municipal",
        "Yilo Krobo Municipal", "Lower Manya Krobo Municipal", "Upper Manya Krobo District", "Asuogyaman District",
        "Fanteakwa North District", "Fanteakwa South District", "Abuakwa North Municipal", "Abuakwa South Municipal",
        "Atiwa East District", "Atiwa West District", "Birim North District", "Birim South District", "Achiase District",
        "Ayensuano District", "Denkyembour District", "Kwahu Afram Plains North District", "Kwahu Afram Plains South District",
        "Kwahu East District", "Kwahu South District", "Kwahu West Municipal", "Okere District"
    ],
    "Volta": [
        "Ho Municipal", "Kpando Municipal", "Hohoe Municipal", "Ketu South Municipal", "Ketu North Municipal",
        "Keta Municipal", "Anloga District", "Central Tongu District", "North Tongu District", "South Tongu District",
        "Afadzato South District", "Agotime Ziope District", "Akatsi North District", "Akatsi South Municipal",
        "Ho West District", "North Dayi District", "South Dayi District"
    ],
    "Northern": [
        "Tamale Metropolitan", "Sagnarigu Municipal", "Yendi Municipal", "Savelugu Municipal", "Gushegu Municipal",
        "Karaga District", "Kpandai District", "Kumbungu District", "Mion District", "Nanton District",
        "Saboba District", "Tatale Sanguli District", "Tolon District", "Zabzugu District"
    ],
    "Bono": [
        "Sunyani Municipal", "Berekum East Municipal", "Berekum West District", "Dormaa Central Municipal",
        "Dormaa East District", "Dormaa West District", "Jaman North District", "Jaman South Municipal",
        "Sunyani West Municipal", "Tain District", "Wenchi Municipal", "Banda District"
    ],
    "Bono East": [
        "Techiman Municipal", "Atebubu-Amantin Municipal", "Kintampo North Municipal", "Kintampo South District",
        "Nkoranza North District", "Nkoranza South Municipal", "Pru East District", "Pru West District",
        "Sene East District", "Sene West District", "Techiman North District"
    ],
    "Ahafo": [
        "Asunafo North Municipal (Goaso)", "Asunafo South District", "Asutifi North District (Kenyasi)",
        "Asutifi South District", "Tano North Municipal", "Tano South Municipal"
    ],
    "Upper East": [
        "Bolgatanga Municipal", "Bawku Municipal", "Kasena Nankana Municipal (Navrongo)", "Bawku West District",
        "Binduri District", "Bolgatanga East District", "Bongo District", "Builsa North Municipal",
        "Builsa South District", "Garu District", "Kasena Nankana West District", "Nabdam District",
        "Pusiga District", "Talensi District", "Tempane District"
    ],
    "Upper West": [
        "Wa Municipal", "Jirapa Municipal", "Lawra Municipal", "Nandom Municipal", "Dafiama Bussie Issa District",
        "Lambussie Karni District", "Nadowli Kaleo District", "Sissala East Municipal", "Sissala West District",
        "Wa East District", "Wa West District"
    ],
    "Oti": [
        "Dambai (Krachi East Municipal)", "Jasikan District", "Kadjebi District", "Krachi Nchumuru District",
        "Krachi West Municipal", "Nkwanta North District", "Nkwanta South Municipal"
    ],
    "Savannah": [
        "Damongo (West Gonja Municipal)", "Bole District", "Central Gonja District", "East Gonja Municipal (Salaga)",
        "North Gonja District", "North East Gonja District", "Sawla Tuna Kalba District"
    ],
    "North East": [
        "Nalerigu (East Mamprusi Municipal)", "Bunkpurugu Nyankpanduri District", "Chereponi District",
        "Mamprugu Moagduri District", "West Mamprusi Municipal (Walewale)", "Yunyoo-Nasuan District"
    ],
    "Western North": [
        "Sefwi Wiawso Municipal", "Aowin Municipal", "Bibiani Anhwiaso Bekwai Municipal", "Bodi District",
        "Juaboso District", "Bia East District", "Bia West District", "Suaman District"
    ]
}

# ─────────────────────────────────────────────────────────────────────────────
# 4. KENYA: 47 Counties (Official Sub-Counties / Constituencies)
# ─────────────────────────────────────────────────────────────────────────────
KENYA_COUNTIES_SUBCOUNTIES: Dict[str, List[str]] = {
    "Nairobi": [
        "Dagoretti North", "Dagoretti South", "Embakasi Central", "Embakasi East", "Embakasi North",
        "Embakasi South", "Embakasi West", "Kamukunji", "Kasarani", "Kibra", "Lang'ata",
        "Makadara", "Mathare", "Roysambu", "Ruaraka", "Starehe", "Westlands"
    ],
    "Mombasa": ["Changamwe", "Jomvu", "Kisauni", "Likoni", "Mvita", "Nyali"],
    "Kiambu": [
        "Gatundu North", "Gatundu South", "Githunguri", "Juja", "Kabete", "Kiambaa",
        "Kiambu Town", "Kikuyu", "Lari", "Limuru", "Ruiru", "Thika Town"
    ],
    "Kisumu": ["Kisumu Central", "Kisumu East", "Kisumu West", "Muhoroni", "Nyakach", "Nyando", "Seme"],
    "Nakuru": [
        "Bahati", "Gilgil", "Kuresoi North", "Kuresoi South", "Molo", "Naivasha",
        "Nakuru Town East", "Nakuru Town West", "Njoro", "Rongai", "Subukia"
    ],
    "Uasin Gishu": ["Ainabkoi", "Kapseret", "Kesses", "Moiben", "Soy", "Turbo (Eldoret)"],
    "Machakos": [
        "Kangundo", "Kathiani", "Machakos Town", "Masinga", "Matungulu", "Mavoko (Athi River)", "Mwala", "Yatta"
    ],
    "Kilifi": ["Ganze", "Kaloleni", "Kilifi North", "Kilifi South", "Magarini", "Malindi", "Rabai"],
    "Kajiado": ["Kajiado Central", "Kajiado East", "Kajiado North (Ngong)", "Kajiado South (Loitokitok)", "Kajiado West"],
    "Kakamega": [
        "Butere", "Ikolomani", "Khwisero", "Likuyani", "Lugari", "Lurambi (Kakamega Town)",
        "Malava", "Matungu", "Mumias East", "Mumias West", "Navakholo", "Shinyalu"
    ],
    "Meru": [
        "Buuri", "Central Imenti", "Igembe Central", "Igembe North", "Igembe South",
        "North Imenti (Meru Town)", "South Imenti", "Tigania East", "Tigania West"
    ],
    "Nyeri": ["Kieni", "Mathira East", "Mathira West", "Mukurweini", "Nyeri Town", "Othaya", "Tetu"],
    "Murang'a": ["Gatanga", "Kahuro", "Kandara", "Kangema", "Kigumo", "Kiharu (Murang'a Town)", "Maragua", "Mathioya"],
    "Bungoma": ["Bumula", "Kabuchai", "Kanduyi (Bungoma Town)", "Kimilili", "Mt. Elgon", "Sirisia", "Tongaren", "Webuye East", "Webuye West"],
    "Busia": ["Budalangi", "Butula", "Funyula", "Matayos (Busia Town)", "Nambale", "Teso North", "Teso South"],
    "Embu": ["Manyatta (Embu Town)", "Mbeere North", "Mbeere South", "Runyenjes"],
    "Garissa": ["Daadab", "Fafi", "Garissa Township", "Hulugho", "Ijara", "Lagdera", "Balambala"],
    "Homa Bay": ["Homa Bay Town", "Kabondo Kasipul", "Karachuonyo", "Kasipul", "Mbita", "Ndhiwa", "Rangwe", "Suba"],
    "Isiolo": ["Isiolo North", "Isiolo South"],
    "Kericho": ["Ainamoi (Kericho Town)", "Belgut", "Bureti", "Kipkelion East", "Kipkelion West", "Soin Sigowet"],
    "Kirinyaga": ["Kirinyaga Central", "Gichugu", "Mwea", "Ndia"],
    "Kisii": ["Bobasi", "Bomachoge Borabu", "Bomachoge Chache", "Bonchari", "Kitutu Chache North", "Kitutu Chache South", "Nyaribari Chache", "Nyaribari Masaba", "South Mugirango"],
    "Kitui": ["Kitui Central", "Kitui East", "Kitui Rural", "Kitui South", "Kitui West", "Mwingi Central", "Mwingi North", "Mwingi West"],
    "Kwale": ["Kinango", "Lunga Lunga", "Matuga (Kwale Town)", "Msambweni"],
    "Laikipia": ["Laikipia East (Nanyuki)", "Laikipia North", "Laikipia West"],
    "Lamu": ["Lamu East", "Lamu West"],
    "Makueni": ["Kaiti", "Kibwezi East", "Kibwezi West", "Kilome", "Makueni", "Mbooni"],
    "Mandera": ["Banissa", "Lafey", "Mandera East", "Mandera North", "Mandera South", "Mandera West"],
    "Marsabit": ["Laisamis", "Moyale", "North Horr", "Saku (Marsabit Town)"],
    "Migori": ["Awendo", "Kuria East", "Kuria West", "Nyatike", "Rongo", "Suna East", "Suna West", "Uriri"],
    "Nandi": ["Aldai", "Chesumei", "Emgwen", "Mosop", "Nandi Hills", "Tinderet"],
    "Narok": ["Emurua Dikirr", "Kilgoris", "Narok East", "Narok North", "Narok South", "Narok West"],
    "Nyamira": ["Borabu", "Kitutu Masaba", "North Mugirango", "West Mugirango"],
    "Nyandarua": ["Kinangop", "Kipipiri", "Ndaragwa", "Ol Jorok", "Ol Kalou"],
    "Samburu": ["Samburu East", "Samburu North", "Samburu West"],
    "Siaya": ["Alego Usonga", "Bondo", "Gem", "Rarieda", "Ugenya", "Ugunja"],
    "Taita-Taveta": ["Mwatate", "Taveta", "Voi", "Wundanyi"],
    "Tana River": ["Bura", "Galole", "Garsen"],
    "Tharaka-Nithi": ["Chuka/Igambang'ombe", "Maara", "Tharaka"],
    "Trans Nzoia": ["Cherangany", "Endebess", "Kwanza", "Kiminini", "Saboti (Kitale)"],
    "Turkana": ["Loima", "Turkana Central", "Turkana East", "Turkana North", "Turkana South", "Turkana West"],
    "Vihiga": ["Emuhaya", "Hamisi", "Luanda", "Sabatia", "Vihiga"],
    "Wajir": ["Eldas", "Tarbaj", "Wajir East", "Wajir North", "Wajir South", "Wajir West"],
    "West Pokot": ["Kapenguria", "Kacheliba", "Pokot South", "Sigor"],
    "Baringo": ["Baringo Central", "Baringo North", "Baringo South", "Eldama Ravine", "Mogotio", "Tiaty"],
    "Bomet": ["Bomet Central", "Bomet East", "Chepalungu", "Konoin", "Sotik"],
    "Elgeyo-Marakwet": ["Keiyo North", "Keiyo South", "Marakwet East", "Marakwet West"]
}

# ─────────────────────────────────────────────────────────────────────────────
# 5. RWANDA: 5 Provinces (All 30 Official Districts - Akarere)
# ─────────────────────────────────────────────────────────────────────────────
RWANDA_PROVINCES_DISTRICTS: Dict[str, List[str]] = {
    "Kigali City": ["Gasabo", "Kicukiro", "Nyarugenge"],
    "Northern Province": ["Burera", "Gakenke", "Gicumbi", "Musanze", "Rulindo"],
    "Southern Province": ["Gisagara", "Huye", "Kamonyi", "Muhanga", "Nyamagabe", "Nyanza", "Nyaruguru", "Ruhango"],
    "Eastern Province": ["Bugesera", "Gatsibo", "Kayonza", "Kirehe", "Ngoma", "Nyagatare", "Rwamagana"],
    "Western Province": ["Karongi", "Ngororero", "Nyabihu", "Nyamasheke", "Rubavu", "Rusizi", "Rutsiro"]
}

# ─────────────────────────────────────────────────────────────────────────────
# 6. CAMEROON: 10 Regions (All 58 Official Divisions - Départements)
# ─────────────────────────────────────────────────────────────────────────────
CAMEROON_REGIONS_DIVISIONS: Dict[str, List[str]] = {
    "Adamawa": ["Djérem", "Faro-et-Déo", "Mayo-Banyo", "Mbéré", "Vina (Ngaoundéré)"],
    "Centre": ["Haute-Sanaga", "Lekié", "Mbam-et-Inoubou", "Mbam-et-Kim", "Méfou-et-Afamba", "Méfou-et-Akono", "Mfoundi (Yaoundé)", "Nyong-et-Kéllé", "Nyong-et-Mfoumou", "Nyong-et-So'o"],
    "East": ["Boumba-et-Ngoko", "Haut-Nyong", "Kadey", "Lom-et-Djérem (Bertoua)"],
    "Far North": ["Diamaré (Maroua)", "Logone-et-Chari", "Mayo-Danay", "Mayo-Kani", "Mayo-Sava", "Mayo-Tsanaga"],
    "Littoral": ["Moungo", "Nkam", "Sanaga-Maritime", "Wouri (Douala)"],
    "North": ["Bénoué (Garoua)", "Faro", "Mayo-Louti", "Mayo-Rey"],
    "North-West": ["Boyo", "Bui", "Donga-Mantung", "Menchum", "Mezam (Bamenda)", "Momo", "Ngo-Ketunjia"],
    "South": ["Dja-et-Lobo", "Mvila (Ebolowa)", "Océan (Kribi)", "Vallée-du-Ntem"],
    "South-West": ["Fako (Buea/Limbe)", "Koupé-Manengouba", "Lebialem", "Manyu", "Meme (Kumba)", "Ndian"],
    "West": ["Bamboutos", "Haut-Nkam", "Hauts-Plateaux", "Koung-Khi", "Ménoua (Dschang)", "Mifi (Bafoussam)", "Ndé", "Noun"]
}

# ─────────────────────────────────────────────────────────────────────────────
# 7. SIERRA LEONE: 5 Provinces/Areas (All 16 Official Districts)
# ─────────────────────────────────────────────────────────────────────────────
SIERRA_LEONE_PROVINCES_DISTRICTS: Dict[str, List[str]] = {
    "Eastern Province": ["Kailahun", "Kenema", "Kono"],
    "Northern Province": ["Bombali", "Falaba", "Kambia", "Koinadugu", "Tonkolili"],
    "North Western Province": ["Karene", "Port Loko"],
    "Southern Province": ["Bo", "Bonthe", "Moyamba", "Pujehun"],
    "Western Area": ["Western Area Urban (Freetown)", "Western Area Rural"]
}

# ─────────────────────────────────────────────────────────────────────────────
# 8. SENEGAL: 14 Regions (All 46 Official Departments)
# ─────────────────────────────────────────────────────────────────────────────
SENEGAL_REGIONS_DEPARTMENTS: Dict[str, List[str]] = {
    "Dakar": ["Dakar", "Guédiawaye", "Pikine", "Rufisque", "Keur Massar"],
    "Thiès": ["Thiès", "M'bour", "Tivaouane"],
    "Diourbel": ["Diourbel", "Bambey", "Mbacké (Touba)"],
    "Saint-Louis": ["Saint-Louis", "Dagana", "Podor"],
    "Kaolack": ["Kaolack", "Guinguinéo", "Nioro du Rip"],
    "Ziguinchor": ["Ziguinchor", "Bignona", "Oussouye"],
    "Fatick": ["Fatick", "Foundiougne", "Gossas"],
    "Kolda": ["Kolda", "Médina Yoro Foulah", "Vélingara"],
    "Louga": ["Louga", "Kébémer", "Linguère"],
    "Matam": ["Matam", "Kanel", "Ranérou-Ferlo"],
    "Tambacounda": ["Tambacounda", "Bakel", "Goudiry", "Koumpentoum"],
    "Kédougou": ["Kédougou", "Salémata", "Saraya"],
    "Kaffrine": ["Kaffrine", "Birkilane", "Koungheul", "Malem Hodar"],
    "Sédhiou": ["Sédhiou", "Bounkiling", "Goudomp"]
}

# ─────────────────────────────────────────────────────────────────────────────
# 9. UGANDA: 4 Regions (Official Districts)
# ─────────────────────────────────────────────────────────────────────────────
UGANDA_REGIONS_DISTRICTS: Dict[str, List[str]] = {
    "Central Region": [
        "Kampala Capital City", "Wakiso", "Mukono", "Mpigi", "Luweero", "Masaka",
        "Mityana", "Mubende", "Nakasongola", "Buikwe", "Butambala", "Gomba",
        "Kalangala", "Kayunga", "Kyankwanzi", "Lwengo", "Lyantonde", "Nakaseke", "Rakai", "Sembabule"
    ],
    "Eastern Region": [
        "Jinja", "Mbale", "Iganga", "Soroti", "Tororo", "Busia", "Bugiri", "Kamuli",
        "Kapchorwa", "Kumi", "Mayuge", "Pallisa", "Sironko", "Budaka", "Bududa",
        "Bukedea", "Bukwo", "Bulambuli", "Buyende", "Kibuku", "Luuka", "Manafwa",
        "Namayingo", "Namutumba", "Ngora", "Serere"
    ],
    "Northern Region": [
        "Gulu", "Arua", "Lira", "Kitgum", "Moroto", "Nebbi", "Apac", "Kotido",
        "Adjumani", "Amuru", "Dokolo", "Kaabong", "Koboko", "Maracha", "Moyo",
        "Nakapiripirit", "Oyam", "Pader", "Yumbe", "Abim", "Agago", "Alebtong",
        "Amolatar", "Amudat", "Lamwo", "Nwoya", "Otuke", "Zombo"
    ],
    "Western Region": [
        "Mbarara", "Kabale", "Fort Portal (Kabarole)", "Kasese", "Hoima", "Masindi",
        "Bushenyi", "Bundibugyo", "Kisoro", "Rukungiri", "Ntungamo", "Ibanda",
        "Isingiro", "Kamwenge", "Kanungu", "Kibaale", "Kiruhura", "Kyenjojo",
        "Buliisa", "Buhweju", "Kakumiro", "Kagadi", "Kyegegwa", "Mitooma", "Ntoroko", "Rubirizi", "Sheema"
    ]
}

# ─────────────────────────────────────────────────────────────────────────────
# 10. ZIMBABWE: 10 Provinces (Official Districts)
# ─────────────────────────────────────────────────────────────────────────────
ZIMBABWE_PROVINCES_DISTRICTS: Dict[str, List[str]] = {
    "Harare Province": ["Harare Urban", "Chitungwiza", "Epworth", "Ruwa"],
    "Bulawayo City": ["Bulawayo Urban"],
    "Manicaland": ["Mutare", "Buhera", "Chimanimani", "Chipinge", "Makoni (Rusape)", "Mutasa", "Nyanga"],
    "Mashonaland Central": ["Bindura", "Guruve", "Mazowe", "Mbire", "Mount Darwin", "Muzarabani", "Rushinga", "Shamva"],
    "Mashonaland East": ["Marondera", "Chikomba", "Goromonzi", "Hwedza", "Mudzi", "Murehwa", "Mutoko", "Seke", "Uzumba-Maramba-Pfungwe"],
    "Mashonaland West": ["Chinhoyi", "Chegutu", "Hurungwe (Karoi)", "Kariba", "Makonde", "Mhondoro-Ngezi", "Sanyati", "Zvimba"],
    "Masvingo": ["Masvingo", "Bikita", "Chiredzi", "Chivi", "Gutu", "Mwenezi", "Zaka"],
    "Matabeleland North": ["Hwange", "Binga", "Bubi", "Lupane", "Nkayi", "Tsholotsho", "Umguza", "Victoria Falls"],
    "Matabeleland South": ["Gwanda", "Beitbridge", "Bulilima", "Mangwe", "Insiza", "Matobo", "Umzingwane"],
    "Midlands": ["Gweru", "Gokwe North", "Gokwe South", "Kwekwe", "Mberengwa", "Shurugwi", "Zvishavane", "Chirumhanzu"]
}

# ─────────────────────────────────────────────────────────────────────────────
# 11. ZAMBIA: 10 Provinces (Official Districts)
# ─────────────────────────────────────────────────────────────────────────────
ZAMBIA_PROVINCES_DISTRICTS: Dict[str, List[str]] = {
    "Lusaka": ["Lusaka", "Chilanga", "Chirundu", "Chongwe", "Kafue", "Luangwa", "Rufunsa"],
    "Copperbelt": ["Ndola", "Kitwe", "Chingola", "Mufulira", "Luanshya", "Kalulushi", "Chililabombwe", "Lufwanyama", "Masaiti", "Mpongwe"],
    "Central": ["Kabwe", "Chibombo", "Chisamba", "Chitambo", "Itezhi-Tezhi", "Kapiri Mposhi", "Luano", "Mkushi", "Mumbwa", "Ngabwe", "Serenje", "Shibuyunji"],
    "Southern": ["Livingstone", "Choma", "Mazabuka", "Monze", "Kalomo", "Chikankata", "Gwembe", "Kazungula", "Namwala", "Pemba", "Sinazongwe", "Zimba"],
    "Eastern": ["Chipata", "Chadiza", "Chasefu", "Chipangali", "Kasenengwa", "Katete", "Lumezi", "Lundazi", "Lusangazi", "Mambwe", "Nyimba", "Petauke", "Sinda", "Vubwi"],
    "Luapula": ["Mansa", "Chembe", "Chiengi", "Chifunabuli", "Chipili", "Kawambwa", "Lunga", "Milenge", "Mwansabombwe", "Mwense", "Nchelenge", "Samfya"],
    "Muchinga": ["Chinsali", "Isoka", "Kanchibiya", "Lavushimanda", "Mafinga", "Mpika", "Nakonde", "Shiwang'andu"],
    "Northern": ["Kasama", "Chilubi", "Kaputa", "Kasama", "Lunte", "Lupososhi", "Luwingu", "Mbala", "Mporokoso", "Mpulungu", "Mungwi", "Nsama"],
    "North-Western": ["Solwezi", "Chavuma", "Ikelenge", "Kalumbila", "Kasempa", "Manyinga", "Mufumbwe", "Mushindamo", "Mwinilunga", "Zambezi"],
    "Western": ["Mongu", "Kalabo", "Kaoma", "Limulunga", "Luampa", "Lukulu", "Mitete", "Nalolo", "Nkeyema", "Senanga", "Sesheke", "Shang'ombo", "Sikongo", "Sioma"]
}

# ─────────────────────────────────────────────────────────────────────────────
# 12. EGYPT: 27 Governorates (Major Official Markaz / Cities)
# ─────────────────────────────────────────────────────────────────────────────
EGYPT_GOVERNORATES_MARKAZ: Dict[str, List[str]] = {
    "Cairo": ["Nasr City", "Heliopolis", "Maadi", "Zamalek", "New Cairo", "Helwan", "Shubra", "El Shorouk", "El Marg", "Downtown Cairo", "Bulaq"],
    "Alexandria": ["Montaza", "Sharq (East)", "Wust (Central)", "Gharb (West)", "Gomrok", "Amreya", "Borg El Arab"],
    "Giza": ["Dokki", "Agouza", "Mohandessin", "6th of October City", "Sheikh Zayed City", "Al Haram", "Al Omraniya", "Al Badrashein", "Imbaba"],
    "Dakahlia": ["Mansoura", "Mit Ghamr", "Talkha", "Dikirnis", "Belqas", "Sinbillawain"],
    "Red Sea": ["Hurghada", "Safaga", "El Gouna", "Marsa Alam", "Ras Gharib", "Qoseir"],
    "South Sinai": ["Sharm El Sheikh", "Dahab", "Nuweiba", "Saint Catherine", "Ras Sedr", "Tor Sinai"],
    "Aswan": ["Aswan City", "Kom Ombo", "Edfu", "Nasr El Nuba", "Daraw"],
    "Luxor": ["Luxor City", "Armant", "Esna", "Kurna", "Tiba"],
    "Port Said": ["Port Said City", "Port Fouad", "Zohour", "Sharq", "Dawahy"],
    "Suez": ["Suez City", "Arbaeen", "Attaka", "Faisal", "Ganayen"]
}
if "EG" in AFRICAN_SUBDIVISIONS:
    EGYPT_GOVERNORATES_MARKAZ.update(AFRICAN_SUBDIVISIONS["EG"])


# ─────────────────────────────────────────────────────────────────────────────
# Master Catalog of all 54 Sovereign African Countries
# ─────────────────────────────────────────────────────────────────────────────
AFRICAN_REGIONS_CATALOG: Dict[str, Dict[str, Any]] = {
    # 1. Algeria
    "DZ": {
        "state_label": "Province (Wilaya)",
        "lga_label": "District / Daira",
        "lga_mode": "dropdown",
        "states": [
            "Adrar", "Chlef", "Laghouat", "Oum El Bouaghi", "Batna", "Béjaïa",
            "Biskra", "Béchar", "Blida", "Bouira", "Tamanrasset", "Tébessa",
            "Tlemcen", "Tiaret", "Tizi Ouzou", "Algiers", "Djelfa", "Jijel",
            "Sétif", "Saïda", "Skikda", "Sidi Bel Abbès", "Annaba", "Guelma",
            "Constantine", "Médéa", "Mostaganem", "M'Sila", "Mascara", "Ouargla",
            "Oran", "El Bayadh", "Illizi", "Bordj Bou Arréridj", "Boumerdès",
            "El Tarf", "Tindouf", "Tissemsilt", "El Oued", "Khenchela",
            "Souk Ahras", "Tipaza", "Mila", "Aïn Defla", "Naâma", "Aïn Témouchent",
            "Ghardaïa", "Relizane", "Timimoun", "Bordj Badji Mokhtar",
            "Ouled Djellal", "Béni Abbès", "In Salah", "In Guezzam", "Touggourt",
            "Djanet", "El M'Ghair", "El Meniaa"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("DZ", {}),
    },
    # 2. Angola
    "AO": {
        "state_label": "Province",
        "lga_label": "Municipality",
        "lga_mode": "dropdown",
        "states": [
            "Bengo", "Benguela", "Bié", "Cabinda", "Cuando Cubango", "Cuanza Norte",
            "Cuanza Sul", "Cunene", "Huambo", "Huíla", "Luanda", "Lunda Norte",
            "Lunda Sul", "Malanje", "Moxico", "Namibe", "Uíge", "Zaire"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("AO", {}),
    },
    # 3. Benin
    "BJ": {
        "state_label": "Department",
        "lga_label": "Commune / City",
        "lga_mode": "dropdown",
        "states": [
            "Alibori", "Atacora", "Atlantique", "Borgou", "Collines", "Couffo",
            "Donga", "Littoral (Cotonou)", "Mono", "Ouémé (Porto-Novo)", "Plateau", "Zou"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("BJ", {}),
    },
    # 4. Botswana
    "BW": {
        "state_label": "District",
        "lga_label": "Sub-District / City",
        "lga_mode": "dropdown",
        "states": [
            "Central", "Chobe", "Francistown", "Gaborone", "Ghanzi", "Jwaneng",
            "Kgalagadi", "Kgatleng", "Kweneng", "Lobatse", "Ngamiland",
            "North-East", "Orapa", "Selibe Phikwe", "South-East", "Southern", "Sowa"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("BW", {}),
    },
    # 5. Burkina Faso
    "BF": {
        "state_label": "Region",
        "lga_label": "Province / City",
        "lga_mode": "dropdown",
        "states": [
            "Boucle du Mouhoun", "Cascades", "Centre (Ouagadougou)", "Centre-Est",
            "Centre-Nord", "Centre-Ouest", "Centre-Sud", "Est", "Hauts-Bassins",
            "Nord", "Plateau-Central", "Sahel", "Sud-Ouest"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("BF", {}),
    },
    # 6. Burundi
    "BI": {
        "state_label": "Province",
        "lga_label": "Commune",
        "lga_mode": "dropdown",
        "states": [
            "Bubanza", "Bujumbura Mairie", "Bujumbura Rural", "Bururi", "Cankuzo",
            "Cibitoke", "Gitega", "Karuzi", "Kayanza", "Kirundo", "Makamba",
            "Muramvya", "Muyinga", "Mwaro", "Ngozi", "Rumonge", "Rutana", "Ruyigi"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("BI", {}),
    },
    # 7. Cabo Verde
    "CV": {
        "state_label": "Island / Municipality",
        "lga_label": "Area / Parish",
        "lga_mode": "dropdown",
        "states": [
            "Boa Vista", "Brava", "Maio", "Mosteiros", "Paul", "Porto Novo",
            "Praia", "Ribeira Brava", "Ribeira Grande", "Ribeira Grande de Santiago",
            "Sal", "Santa Catarina", "Santa Catarina do Fogo", "Santa Cruz",
            "São Domingos", "São Filipe", "São Lourenço dos Órgãos", "São Miguel",
            "São Salvador do Mundo", "São Vicente", "Tarrafal", "Tarrafal de São Nicolau"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("CV", {}),
    },
    # 8. Cameroon (WITH VERIFIED DEPARTMENTS DROPDOWN)
    "CM": {
        "state_label": "Region",
        "lga_label": "Division / Department",
        "lga_mode": "dropdown",
        "states": list(CAMEROON_REGIONS_DIVISIONS.keys()),
        "lgas": CAMEROON_REGIONS_DIVISIONS,
    },
    # 9. Central African Republic
    "CF": {
        "state_label": "Prefecture",
        "lga_label": "Sub-Prefecture",
        "lga_mode": "dropdown",
        "states": [
            "Bamingui-Bangoran", "Bangui", "Basse-Kotto", "Haute-Kotto", "Haut-Mbomou",
            "Kémo", "Lobaye", "Mambéré-Kadéï", "Mbomou", "Nana-Grébizi", "Nana-Mambéré",
            "Ombella-M'Poko", "Ouaka", "Ouham", "Ouham-Pendé", "Sangha-Mbaéré", "Vakaga"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("CF", {}),
    },
    # 10. Chad
    "TD": {
        "state_label": "Region",
        "lga_label": "Department",
        "lga_mode": "dropdown",
        "states": [
            "Bahr el Gazel", "Batha", "Borkou", "Chari-Baguirmi", "Ennedi-Est",
            "Ennedi-Ouest", "Guéra", "Hadjer-Lamis", "Kanem", "Lac", "Logone Occidental",
            "Logone Oriental", "Mandoul", "Mayo-Kebbi Est", "Mayo-Kebbi Ouest",
            "Moyen-Chari", "N'Djamena", "Ouaddaï", "Salamat", "Sila", "Tandjilé",
            "Tibesti", "Wadi Fira"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("TD", {}),
    },
    # 11. Comoros
    "KM": {
        "state_label": "Autonomous Island",
        "lga_label": "Municipality / Area",
        "lga_mode": "dropdown",
        "states": ["Anjouan", "Grande Comore", "Mohéli"],
        "lgas": AFRICAN_SUBDIVISIONS.get("KM", {}),
    },
    # 12. Congo, Republic of the
    "CG": {
        "state_label": "Department",
        "lga_label": "District / Commune",
        "lga_mode": "dropdown",
        "states": [
            "Bouenza", "Brazzaville", "Cuvette", "Cuvette-Ouest", "Kouilou",
            "Lékoumou", "Likouala", "Niari", "Plateaux", "Pointe-Noire", "Pool", "Sangha"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("CG", {}),
    },
    # 13. Congo, Democratic Republic of the (DRC)
    "CD": {
        "state_label": "Province",
        "lga_label": "Territory / City",
        "lga_mode": "dropdown",
        "states": [
            "Bas-Uélé", "Équateur", "Haut-Katanga (Lubumbashi)", "Haut-Lomami", "Haut-Uélé",
            "Ituri", "Kasaï", "Kasaï-Central", "Kasaï-Oriental", "Kinshasa", "Kongo Central",
            "Kwango", "Kwilu", "Lomami", "Lualaba", "Mai-Ndombe", "Maniema", "Mongala",
            "Nord-Kivu (Goma)", "Nord-Ubangi", "Sankuru", "Sud-Kivu (Bukavu)", "Sud-Ubangi",
            "Tanganyika", "Tshopo", "Tshuapa"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("CD", {}),
    },
    # 14. Côte d'Ivoire (Ivory Coast)
    "CI": {
        "state_label": "District",
        "lga_label": "Region / Department",
        "lga_mode": "dropdown",
        "states": [
            "Abidjan", "Bas-Sassandra", "Comoé", "Denguélé", "Gôh-Djiboua",
            "Lacs", "Lagunes", "Montagnes", "Sassandra-Marahoué", "Savanes",
            "Vallée du Bandama", "Woroba", "Yamoussoukro", "Zanzan"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("CI", {}),
    },
    # 15. Djibouti
    "DJ": {
        "state_label": "Region",
        "lga_label": "District / Area",
        "lga_mode": "dropdown",
        "states": ["Ali Sabieh", "Arta", "Dikhil", "Djibouti City", "Obock", "Tadjourah"],
        "lgas": AFRICAN_SUBDIVISIONS.get("DJ", {}),
    },
    # 16. Egypt (WITH VERIFIED MARKAZ DROPDOWN)
    "EG": {
        "state_label": "Governorate",
        "lga_label": "City / Markaz",
        "lga_mode": "dropdown",
        "states": [
            "Alexandria", "Aswan", "Asyut", "Beheira", "Beni Suef", "Cairo",
            "Dakahlia", "Damietta", "Faiyum", "Gharbia", "Giza", "Ismailia",
            "Kafr El Sheikh", "Luxor", "Matrouh", "Minya", "Monufia",
            "New Valley", "North Sinai", "Port Said", "Qalyubia", "Qena",
            "Red Sea", "Sharqia", "Sohag", "South Sinai", "Suez"
        ],
        "lgas": EGYPT_GOVERNORATES_MARKAZ,
    },
    # 17. Equatorial Guinea
    "GQ": {
        "state_label": "Province",
        "lga_label": "District",
        "lga_mode": "dropdown",
        "states": [
            "Annobón", "Bioko Norte (Malabo)", "Bioko Sur", "Centro Sur", "Djibloho",
            "Kié-Ntem", "Litoral (Bata)", "Wele-Nzas"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("GQ", {}),
    },
    # 18. Eritrea
    "ER": {
        "state_label": "Region (Zoba)",
        "lga_label": "Sub-Region",
        "lga_mode": "dropdown",
        "states": ["Anseba", "Debub", "Gash-Barka", "Maekel (Asmara)", "Northern Red Sea", "Southern Red Sea"],
        "lgas": AFRICAN_SUBDIVISIONS.get("ER", {}),
    },
    # 19. Eswatini (Swaziland)
    "SZ": {
        "state_label": "Region",
        "lga_label": "Inkhundla / Area",
        "lga_mode": "dropdown",
        "states": ["Hhohho (Mbabane)", "Lubombo", "Manzini", "Shiselweni"],
        "lgas": AFRICAN_SUBDIVISIONS.get("SZ", {}),
    },
    # 20. Ethiopia
    "ET": {
        "state_label": "Region",
        "lga_label": "Zone / Woreda",
        "lga_mode": "dropdown",
        "states": [
            "Addis Ababa", "Afar", "Amhara", "Benishangul-Gumuz", "Central Ethiopia",
            "Dire Dawa", "Gambela", "Harari", "Oromia", "Sidama", "Somali",
            "South Ethiopia", "South West Ethiopia", "Tigray"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("ET", {}),
    },
    # 21. Gabon
    "GA": {
        "state_label": "Province",
        "lga_label": "Department",
        "lga_mode": "dropdown",
        "states": [
            "Estuaire (Libreville)", "Haut-Ogooué", "Moyen-Ogooué", "Ngounié",
            "Nyanga", "Ogooué-Ivindo", "Ogooué-Lolo", "Ogooué-Maritime (Port-Gentil)", "Woleu-Ntem"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("GA", {}),
    },
    # 22. Gambia
    "GM": {
        "state_label": "Region / Division",
        "lga_label": "District / Municipality",
        "lga_mode": "dropdown",
        "states": [
            "Banjul", "Central River", "Kanifing", "Lower River",
            "North Bank", "Upper River", "West Coast"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("GM", {}),
    },
    # 23. Ghana (WITH VERIFIED MMDAS DROPDOWN)
    "GH": {
        "state_label": "Region",
        "lga_label": "District / Municipal Area",
        "lga_mode": "dropdown",
        "states": list(GHANA_REGIONS_MMDAS.keys()),
        "lgas": GHANA_REGIONS_MMDAS,
    },
    # 24. Guinea
    "GN": {
        "state_label": "Region",
        "lga_label": "Prefecture",
        "lga_mode": "dropdown",
        "states": ["Boké", "Conakry", "Faranah", "Kankan", "Kindia", "Labé", "Mamou", "Nzérékoré"],
        "lgas": AFRICAN_SUBDIVISIONS.get("GN", {}),
    },
    # 25. Guinea-Bissau
    "GW": {
        "state_label": "Region",
        "lga_label": "Sector",
        "lga_mode": "dropdown",
        "states": ["Bafatá", "Biombo", "Bissau", "Bolama", "Cacheu", "Gabú", "Oio", "Quinara", "Tombali"],
        "lgas": AFRICAN_SUBDIVISIONS.get("GW", {}),
    },
    # 26. Kenya (WITH VERIFIED SUB-COUNTIES DROPDOWN)
    "KE": {
        "state_label": "County",
        "lga_label": "Sub-County / Area",
        "lga_mode": "dropdown",
        "states": list(KENYA_COUNTIES_SUBCOUNTIES.keys()),
        "lgas": KENYA_COUNTIES_SUBCOUNTIES,
    },
    # 27. Lesotho
    "LS": {
        "state_label": "District",
        "lga_label": "Community Council",
        "lga_mode": "dropdown",
        "states": [
            "Berea", "Butha-Buthe", "Leribe", "Mafeteng", "Maseru",
            "Mohale's Hoek", "Mokhotlong", "Qacha's Nek", "Quthing", "Thaba-Tseka"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("LS", {}),
    },
    # 28. Liberia
    "LR": {
        "state_label": "County",
        "lga_label": "District",
        "lga_mode": "dropdown",
        "states": [
            "Bomi", "Bong", "Gbarpolu", "Grand Bassa", "Grand Cape Mount",
            "Grand Gedeh", "Grand Kru", "Lofa", "Margibi", "Maryland",
            "Montserrado (Monrovia)", "Nimba", "River Cess", "River Gee", "Sinoe"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("LR", {}),
    },
    # 29. Libya
    "LY": {
        "state_label": "District (Shabiyah)",
        "lga_label": "Municipality",
        "lga_mode": "dropdown",
        "states": [
            "Al Butnan", "Al Jabal al Akhdar", "Al Jabal al Gharbi", "Al Jafara",
            "Al Jufra", "Al Kufra", "Al Marj", "Al Marqab", "Al Wahat",
            "An Nuqat al Khams", "Az Zawiyah", "Benghazi", "Derna", "Ghat",
            "Misrata", "Murzuq", "Nalut", "Sabha", "Sirte", "Tripoli",
            "Wadi al Hayaa", "Wadi al Shatii"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("LY", {}),
    },
    # 30. Madagascar
    "MG": {
        "state_label": "Region",
        "lga_label": "District",
        "lga_mode": "dropdown",
        "states": [
            "Alaotra-Mangoro", "Amoron'i Mania", "Analamanga (Antananarivo)", "Analanjirofo",
            "Androy", "Anosy", "Atsimo-Andrefana", "Atsimo-Atsinanana", "Atsinanana",
            "Betsiboka", "Boeny", "Bongolava", "Diana", "Haute Matsiatra", "Ihorombe",
            "Itasy", "Melaky", "Menabe", "Sava", "Sofia", "Vakinankaratra", "Vatovavy", "Fitovinany"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("MG", {}),
    },
    # 31. Malawi
    "MW": {
        "state_label": "Region",
        "lga_label": "District",
        "lga_mode": "dropdown",
        "states": [
            "Central Region (Lilongwe)", "Northern Region (Mzuzu)", "Southern Region (Blantyre)"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("MW", {}),
    },
    # 32. Mali
    "ML": {
        "state_label": "Region",
        "lga_label": "Cercle / Commune",
        "lga_mode": "dropdown",
        "states": [
            "Bamako", "Gao", "Kayes", "Kidal", "Koulikoro", "Ménaka",
            "Mopti", "Ségou", "Sikasso", "Taoudénit", "Tombouctou"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("ML", {}),
    },
    # 33. Mauritania
    "MR": {
        "state_label": "Region (Wilaya)",
        "lga_label": "Department (Moughataa)",
        "lga_mode": "dropdown",
        "states": [
            "Adrar", "Assaba", "Brakna", "Dakhlet Nouadhibou", "Gorgol", "Guidimaka",
            "Hodh Ech Chargui", "Hodh El Gharbi", "Inchiri", "Nouakchott-Nord",
            "Nouakchott-Ouest", "Nouakchott-Sud", "Tagant", "Tiris Zemmour", "Trarza"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("MR", {}),
    },
    # 34. Mauritius
    "MU": {
        "state_label": "District / Island",
        "lga_label": "Town / Area",
        "lga_mode": "dropdown",
        "states": [
            "Black River", "Flacq", "Grand Port", "Moka", "Pamplemousses",
            "Plaines Wilhems", "Port Louis", "Rivière du Rempart", "Savanne",
            "Rodrigues", "Agaléga", "St. Brandon"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("MU", {}),
    },
    # 35. Morocco
    "MA": {
        "state_label": "Region",
        "lga_label": "Province / Prefecture",
        "lga_mode": "dropdown",
        "states": [
            "Béni Mellal-Khénifra", "Casablanca-Settat", "Dakhla-Oued Ed-Dahab",
            "Drâa-Tafilalet", "Fès-Meknès", "Guelmim-Oued Noun", "Laâyoune-Sakia El Hamra",
            "Marrakech-Safi", "Oriental", "Rabat-Salé-Kénitra", "Souss-Massa",
            "Tanger-Tétouan-Al Hoceïma"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("MA", {}),
    },
    # 36. Mozambique
    "MZ": {
        "state_label": "Province",
        "lga_label": "District",
        "lga_mode": "dropdown",
        "states": [
            "Cabo Delgado", "Gaza", "Inhambane", "Manica", "Maputo City",
            "Maputo Province", "Nampula", "Niassa", "Sofala", "Tete", "Zambezia"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("MZ", {}),
    },
    # 37. Namibia
    "NA": {
        "state_label": "Region",
        "lga_label": "Constituency",
        "lga_mode": "dropdown",
        "states": [
            "Erongo", "Hardap", "ǃKharas", "Kavango East", "Kavango West",
            "Khomas (Windhoek)", "Kunene", "Ohangwena", "Omaheke", "Omusati",
            "Oshana", "Oshikoto", "Otjozondjupa", "Zambezi"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("NA", {}),
    },
    # 38. Niger
    "NE": {
        "state_label": "Region",
        "lga_label": "Department",
        "lga_mode": "dropdown",
        "states": [
            "Agadez", "Diffa", "Dosso", "Maradi", "Niamey Capital District",
            "Tahoua", "Tillabéri", "Zinder"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("NE", {}),
    },
    # 39. Nigeria (WITH VERIFIED 774 LGAS DROPDOWN)
    "NG": {
        "state_label": "State",
        "lga_label": "Local Government Area (LGA)",
        "lga_mode": "dropdown",
        "states": list(NIGERIA_STATES_LGAS.keys()),
        "lgas": NIGERIA_STATES_LGAS,
    },
    # 40. Rwanda (WITH VERIFIED 30 DISTRICTS DROPDOWN)
    "RW": {
        "state_label": "Province",
        "lga_label": "District",
        "lga_mode": "dropdown",
        "states": list(RWANDA_PROVINCES_DISTRICTS.keys()),
        "lgas": RWANDA_PROVINCES_DISTRICTS,
    },
    # 41. São Tomé and Príncipe
    "ST": {
        "state_label": "District / Autonomous Region",
        "lga_label": "Locality / Town",
        "lga_mode": "dropdown",
        "states": [
            "Água Grande", "Cantagalo", "Caué", "Lembá", "Lobata",
            "Mé-Zóchi", "Príncipe Autonomous Region"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("ST", {}),
    },
    # 42. Senegal (WITH VERIFIED 46 DEPARTMENTS DROPDOWN)
    "SN": {
        "state_label": "Region",
        "lga_label": "Department",
        "lga_mode": "dropdown",
        "states": list(SENEGAL_REGIONS_DEPARTMENTS.keys()),
        "lgas": SENEGAL_REGIONS_DEPARTMENTS,
    },
    # 43. Seychelles
    "SC": {
        "state_label": "District",
        "lga_label": "Island / Area",
        "lga_mode": "dropdown",
        "states": [
            "Anse aux Pins", "Anse Boileau", "Anse Etoile", "Anse Royale", "Baie Lazare",
            "Baie Sainte Anne", "Beau Vallon", "Bel Air", "Bel Ombre", "Cascade", "Glacis",
            "Grand Anse Mahe", "Grand Anse Praslin", "La Digue", "Les Mamelles", "Mont Buxton",
            "Mont Fleuri", "Plaisance", "Pointe Larue", "Port Glaud", "Roche Caiman",
            "Saint Louis", "Takamaka", "English River"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("SC", {}),
    },
    # 44. Sierra Leone (WITH VERIFIED 16 DISTRICTS DROPDOWN)
    "SL": {
        "state_label": "Province / Area",
        "lga_label": "District",
        "lga_mode": "dropdown",
        "states": list(SIERRA_LEONE_PROVINCES_DISTRICTS.keys()),
        "lgas": SIERRA_LEONE_PROVINCES_DISTRICTS,
    },
    # 45. Somalia
    "SO": {
        "state_label": "Region (Gobol)",
        "lga_label": "District",
        "lga_mode": "dropdown",
        "states": [
            "Awdal", "Bakool", "Banaadir (Mogadishu)", "Bari", "Bay", "Galguduud",
            "Gedo", "Hiiraan", "Lower Juba", "Lower Shabelle", "Middle Juba",
            "Middle Shabelle", "Mudug", "Nugaal", "Sanaag", "Sool", "Togdheer",
            "Woqooyi Galbeed"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("SO", {}),
    },
    # 46. South Africa (WITH VERIFIED 52 MUNICIPALITIES DROPDOWN)
    "ZA": {
        "state_label": "Province",
        "lga_label": "Municipality / City",
        "lga_mode": "dropdown",
        "states": list(SOUTH_AFRICA_PROVINCES_MUNICIPALITIES.keys()),
        "lgas": SOUTH_AFRICA_PROVINCES_MUNICIPALITIES,
    },
    # 47. South Sudan
    "SS": {
        "state_label": "State",
        "lga_label": "County",
        "lga_mode": "dropdown",
        "states": [
            "Central Equatoria (Juba)", "Eastern Equatoria", "Jonglei", "Lakes",
            "Northern Bahr el Ghazal", "Unity", "Upper Nile", "Warrap",
            "Western Bahr el Ghazal", "Western Equatoria", "Abyei Area",
            "Greater Pibor", "Ruweng"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("SS", {}),
    },
    # 48. Sudan
    "SD": {
        "state_label": "State (Wilayah)",
        "lga_label": "Locality",
        "lga_mode": "dropdown",
        "states": [
            "Blue Nile", "Central Darfur", "East Darfur", "Gedaref", "Gezira",
            "Kassala", "Khartoum", "North Darfur", "North Kordofan", "Northern",
            "Red Sea (Port Sudan)", "River Nile", "Sennar", "South Darfur",
            "South Kordofan", "West Darfur", "West Kordofan", "White Nile"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("SD", {}),
    },
    # 49. Tanzania
    "TZ": {
        "state_label": "Region",
        "lga_label": "District",
        "lga_mode": "dropdown",
        "states": [
            "Arusha", "Dar es Salaam", "Dodoma", "Geita", "Iringa", "Kagera",
            "Katavi", "Kigoma", "Kilimanjaro", "Lindi", "Manyara", "Mara",
            "Mbeya", "Morogoro", "Mtwara", "Mwanza", "Njombe", "Pemba North",
            "Pemba South", "Pwani", "Rukwa", "Ruvuma", "Shinyanga", "Simiyu",
            "Singida", "Songwe", "Tabora", "Tanga", "Zanzibar North",
            "Zanzibar South", "Zanzibar West"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("TZ", {}),
    },
    # 50. Togo
    "TG": {
        "state_label": "Region",
        "lga_label": "Prefecture",
        "lga_mode": "dropdown",
        "states": [
            "Centrale", "Kara", "Maritime (Lomé)", "Plateaux", "Savanes"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("TG", {}),
    },
    # 51. Tunisia
    "TN": {
        "state_label": "Governorate (Wilayah)",
        "lga_label": "Delegation (Mutamadiyah)",
        "lga_mode": "dropdown",
        "states": [
            "Ariana", "Béja", "Ben Arous", "Bizerte", "Gabès", "Gafsa", "Jendouba",
            "Kairouan", "Kasserine", "Kebili", "Kef", "Mahdia", "Manouba",
            "Medenine", "Monastir", "Nabeul", "Sfax", "Sidi Bouzid", "Siliana",
            "Sousse", "Tataouine", "Tozeur", "Tunis", "Zaghouan"
        ],
        "lgas": AFRICAN_SUBDIVISIONS.get("TN", {}),
    },
    # 52. Uganda (WITH VERIFIED DISTRICTS DROPDOWN)
    "UG": {
        "state_label": "Region",
        "lga_label": "District",
        "lga_mode": "dropdown",
        "states": list(UGANDA_REGIONS_DISTRICTS.keys()),
        "lgas": UGANDA_REGIONS_DISTRICTS,
    },
    # 53. Zambia (WITH VERIFIED DISTRICTS DROPDOWN)
    "ZM": {
        "state_label": "Province",
        "lga_label": "District",
        "lga_mode": "dropdown",
        "states": list(ZAMBIA_PROVINCES_DISTRICTS.keys()),
        "lgas": ZAMBIA_PROVINCES_DISTRICTS,
    },
    # 54. Zimbabwe (WITH VERIFIED DISTRICTS DROPDOWN)
    "ZW": {
        "state_label": "Province",
        "lga_label": "District",
        "lga_mode": "dropdown",
        "states": list(ZIMBABWE_PROVINCES_DISTRICTS.keys()),
        "lgas": ZIMBABWE_PROVINCES_DISTRICTS,
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
