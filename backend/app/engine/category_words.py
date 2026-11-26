"""categorise-1.4.0 (5G-C, D-155): the curated, Indian-focused names and words behind the
automatic categories. Data only; categorise.py decides with it.

Four kinds, each matched case-insensitively on the cleaned name's words and the words of its
UPI ID's local part (gateway prefixes and the handle are left out by merchant.parts):

- KNOWN: brand and chain names. A whole word or phrase of the name ("chai point"), the same
  written as one word ("chaipoint@ybl"), or, for names of 6 letters or more, the start of a
  word ("zolostays"). Brands the merchant engine already knows (brands.json) decide first
  as BRAND; KNOWN never changes a merchant key.
- STRONG keywords: words whose meaning is clear on their own ("pharmacy", "biryani").
- STEMS: the start of a word ("hungerhalt", "pharmaco", "medicine"); only stems no Indian
  given name or surname starts with.
- WEAK keywords: words that also turn up in personal names ("gift", "temple", "trust").
  They decide only when the payee is not clearly a person (a clearly personal name is never
  overridden by a weak keyword), or when two of them agree ("Temple Trust").

Ambiguous words ("hotel", "grab", "store", "shop", "centre", "point", "traders", "fees",
"district") are in no list: alone they say "business" but not which kind, so such a payee
stays Uncategorised and To-do asks. Words that 1.3.0 already used keep their category
("mart" is Groceries). NOT_PERSON_14 adds words no Indian name is ("grab"): with one, a
payee is never People.
"""

KNOWN = {
    "food_drinks": """
        amul, haldiram, haldirams, chaayos, chai point, chai kings, third wave, blue tokai,
        barista, cafe coffee day, ccd, wow momo, faasos, behrouz, box8, eatfit, freshmenu,
        rebel foods, barbeque nation, paradise biryani, meghana foods, adyar ananda bhavan,
        a2b, saravana bhavan, mtr, vidyarthi bhavan, theobroma, monginis, keventers,
        naturals ice cream, baskin robbins, cream stone, kwality walls, havmor, vadilal,
        wendys, taco bell, dunkin, krispy kreme, chilis, mad over donuts, bikanervala,
        rameshwaram cafe, udupi, sagar ratna, cafe niloufer, karachi bakery, kailash parbat,
        nandos, truffles, ice cream, icecream parlour, empire restaurant, mainland china,
        eat sure, eatsure,
        domino, dominos, mcdonald, mcdonalds, starbucks, subway, kfc, burger king, pizza hut
    """,
    "groceries": """
        bigbasket, blinkit, zepto, instamart, dmart, reliance fresh, reliance smart,
        smart bazaar, more supermarket, more retail, spencers, star bazaar, natures basket,
        ratnadeep, heritage fresh, lulu hypermarket, metro cash, big bazaar, jiomart,
        country delight, milkbasket, licious, freshtohome, fraazo, otipy, vijetha,
        easyday, nilgiris, foodhall, bb daily, swiggy instamart, dunzo, kpn fresh
    """,
    "rent_hostel": """
        rentok, nobroker, nestaway, stanza living, stanza, zolo, zolostays, colive,
        housing society, coho, your space, tribe stays, hostelworld, zostel, gostops
    """,
    "travel": """
        uber, ola, rapido, namma yatri, blusmart, irctc, redbus, abhibus, makemytrip,
        goibibo, cleartrip, yatra, easemytrip, ixigo, indigo, air india, akasa, spicejet,
        vistara, fastag, hpcl, bpcl, iocl, indian oil, bharat petroleum, hindustan petroleum,
        shell, nayara, jio bp, namma metro, bmrcl, dmrc, mmrcl, hmrl, cmrl, yulu, bounce,
        zoomcar, parkplus, park plus, ksrtc, tsrtc, apsrtc, msrtc, upsrtc, intrcity, zingbus
    """,
    "bills_recharges": """
        airtel, jio, vodafone idea, bsnl, act fibernet, hathway, excitel, tata play, dish tv,
        sun direct, d2h, bescom, tata power, adani electricity, msedcl, tneb, tangedco,
        bwssb, indane, hp gas, bharat gas, mahanagar gas, igl, mgl, torrent power, cesc,
        tsspdcl, apspdcl, kseb, bses, jio fiber, airtel xstream, you broadband
    """,
    "subscriptions": """
        netflix, spotify, hotstar, disney hotstar, prime video, amazon prime, youtube premium,
        youtube, google play, apple, icloud, zee5, sonyliv, jiocinema, gaana, wynk, audible,
        kindle unlimited, linkedin, chatgpt, openai, notion, canva, adobe, microsoft, dropbox,
        github, aha, sunnxt, mxplayer
    """,
    "shopping": """
        amazon, flipkart, myntra, ajio, meesho, decathlon, croma, ikea, reliance digital,
        reliance trends, trends, vijay sales, lifestyle, max fashion, westside, zudio, h and m,
        uniqlo, zara, bata, puma, nike, adidas, boat, pepperfry, urban ladder, firstcry,
        snapdeal, tata cliq, shoppers stop, pantaloons, tanishq, caratlane, bewakoof,
        sangeetha mobiles, poorvika, lot mobiles, pothys, nalli, fabindia, miniso, mr diy
    """,
    "health": """
        apollo, apollo pharmacy, medplus, 1mg, tata 1mg, pharmeasy, netmeds, practo,
        thyrocare, lal pathlabs, dr lal, metropolis, manipal, fortis, narayana health,
        aster, max healthcare, medanta, cloudnine, rainbow hospitals, healthians, truemeds,
        wellness forever, frank ross, lenskart, titan eye
    """,
    "personal_care": """
        nykaa, urban company, naturals salon, green trends, lakme salon, enrich, toni and guy,
        cult fit, cultfit, cure fit, gold gym, anytime fitness
    """,
    "entertainment": """
        bookmyshow, pvr, inox, cinepolis, district by zomato, district app, zomato district,
        paytm insider, steam, playstation,
        xbox, epic games, wonderla, timezone, smaaash, imagicaa, snow city, funcity
    """,
    "education": """
        coursera, udemy, byjus, unacademy, vedantu, physics wallah, upgrad, simplilearn,
        nptel, great learning, scaler, edx, khan academy, duolingo, testbook, adda247
    """,
    "investments": """
        zerodha, groww, upstox, kuvera, indmoney, paytm money, smallcase, angel one,
        icici direct, hdfc securities, kotak securities, motilal oswal, sharekhan,
        fyers, coin by zerodha, et money, scripbox, nps trust
    """,
    "gifts_donations": """
        ferns n petals, fnp, igp, archies, give india, giveindia, ketto, milaap,
        akshaya patra, cry india, helpage, goonj, isha foundation, iskcon
    """,
}

STRONG = {
    "food_drinks": """
        restaurant restaurants cafe cafes dhaba bakery bakers bakes sweets mithai food foods
        foodfill foodie foodies kitchen kitchens canteen caterers catering tiffin tiffins
        bhojanalaya juice juices chai coffee snacks biryani biriyani pizza pizzeria burger
        burgers shawarma momos eatery eats bistro wines bar icecream creamery dosa idli
        chaat paratha kulfi lassi falooda cakes cake bakehouse patisserie confectionery
        tandoor tandoori kebab kebabs rolls darshini tiffanys sweetmart bhel pani puri
        mess eatery tea
    """,
    "groceries": """
        kirana provision provisions supermarket supermart hypermarket mart grocery groceries
        dairy milk fruits vegetables veggies chicken mutton meat fish organics organic
        freshmart greengrocer
    """,
    "rent_hostel": "hostel hostels pg rent rental rentals stays coliving housing maintenance",
    "travel": """
        travels travel tours cabs cab taxi fuels petroleum petrol diesel lodge inn residency
        resort resorts rail railway railways metro bus buses airlines airways airport parking
        fastag toll tolls
    """,
    "bills_recharges": """
        telecom communications insurance electricity power recharge broadband fibernet
        gas water dth postpaid prepaid bescom tneb mseb discom
    """,
    "subscriptions": "subscription subscriptions",
    "shopping": """
        garments textiles fashion fashions boutique tailors footwear sarees silks
        electronics electricals mobiles computers furniture jewellers jewellery emporium
        showroom collections apparel toys handicrafts
    """,
    "health": """
        pharmacy pharma medical medicals medicos chemist chemists drugs surgicals hospital
        hospitals clinic clinics diagnostics diagnostic labs lab dental dentist opticals
        optical homoeo homeo homoeopathy ayurveda ayurvedic healthcare physiotherapy
        nursing
    """,
    "personal_care": "salon saloon parlour laundry cleaners gym fitness spa barber unisex",
    "entertainment": """
        cinema cinemas cineplex movies theatre theatres multiplex gaming bowling
    """,
    "education": """
        college school university academy institute coaching classes tuition tutorials
        stationery stationers books book library exam exams vidyalaya
    """,
    "emi_loans": "finance",
    "investments": "mutual securities broking demat sip amc",
    "gifts_donations": "gifts giftshop florist florists donation donations charity ngo foundation",
}

# Words that may be part of a person's name, or say little on their own: they decide only
# when the payee is not clearly a person (never against PERSON_name or PERSON_vpa).
WEAK = {
    "gifts_donations": "gift temple trust",
}

STEMS = {
    "food_drinks": "hunger foodi foodf restaura biryan burger bakery tiffin",
    "groceries": "grocer kirana supermar",
    "health": "pharm medical diagnos dental hospital clinic ayurved",
    "shopping": "fashion jewell electronic garment",
    "education": "academy tutorial",
    "travel": "travel petrol",
}


def _split_known(text: str) -> tuple[str, ...]:
    return tuple(" ".join(x.split()) for x in text.replace("\n", " ").split(",") if x.strip())


KNOWN_PHRASES: tuple[tuple[str, str], ...] = tuple(
    (phrase, slug) for slug, text in KNOWN.items() for phrase in _split_known(text)
)
WEAK_WORDS: dict[str, str] = {w: slug for slug, ws in WEAK.items() for w in ws.split()}
STRONG_WORDS: dict[str, str] = {
    w: slug for slug, ws in STRONG.items() for w in ws.split() if w not in WEAK_WORDS
}
STEM_LIST: tuple[tuple[str, str], ...] = tuple(
    (stem, slug) for slug, ws in STEMS.items() for stem in ws.split()
)


def size() -> dict[str, int]:
    """Entries per category, for the report and a test (at least 300 in all)."""
    out: dict[str, int] = {}
    for _, slug in KNOWN_PHRASES:
        out[slug] = out.get(slug, 0) + 1
    for table in (STRONG_WORDS, WEAK_WORDS):
        for slug in table.values():
            out[slug] = out.get(slug, 0) + 1
    for _, slug in STEM_LIST:
        out[slug] = out.get(slug, 0) + 1
    return out


# categorise-1.4.0: words no Indian given name or surname is, on top of categorise.NOT_PERSON.
NOT_PERSON_14 = frozenset("grab go".split())
