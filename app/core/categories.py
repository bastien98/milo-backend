"""
Shared product categories for Belgian supermarkets.
Used by both receipt categorization and promo extraction.
"""

# All valid category values - used by LLMs for categorization
CATEGORIES = [
    # ALCOHOLIC DRINKS
    "Beer (Pils)",              # Jupiler, Stella, Maes, Cristal
    "Beer (Abbey/Trappist)",    # Leffe, Grimbergen, Westmalle, Chimay
    "Beer (Special)",           # Duvel, Chouffe, Karmeliet, Delirium
    "Beer (White/Fruit)",       # Hoegaarden, Kriek, Pêcheresse
    "Beer (Non-Alcoholic)",     # Jupiler 0.0, Leffe 0.0, Tourtel
    "Cider",                    # Stassen, Strongbow
    "Wine (Red)",
    "Wine (White)",
    "Wine (Rosé)",
    "Wine (Sparkling)",         # Cava, Prosecco, Champagne
    "Spirits (Whisky)",
    "Spirits (Gin)",            # Gin, jenever
    "Spirits (Vodka)",
    "Spirits (Rum)",
    "Spirits (Liqueur)",        # Likeur, Amaretto, Baileys
    "Aperitif",                 # Martini, Porto, Sherry, Pastis

    # NON-ALCOHOLIC DRINKS
    "Cola",                     # Coca-Cola, Pepsi, cola zero
    "Lemonade & Soda",          # Fanta, Sprite, 7up, Orangina
    "Energy Drinks",            # Red Bull, Monster, Nalu
    "Ice Tea",                  # Lipton, Fuze Tea
    "Water (Still)",            # Spa Reine, Evian, Vittel
    "Water (Sparkling)",        # Spa Barisart, Bru, Perrier
    "Water (Flavored)",         # Spa Touch, gearomatiseerd water
    "Fruit Juice",              # Appelsap, sinaasappelsap, Tropicana
    "Vegetable Juice",          # Tomatensap, groentesap
    "Smoothies",
    "Syrup",                    # Grenadine, citroen siroop, Teisseire
    "Coffee (Beans/Ground)",    # Koffiebonen, gemalen koffie
    "Coffee (Capsules)",        # Nespresso, Dolce Gusto, Tassimo
    "Coffee (Instant)",         # Oploskoffie, Nescafé
    "Tea",                      # Thee, kruidenthee, groene thee
    "Hot Chocolate",            # Cacao, chocolademelk poeder
    "Plant Milk",               # Haver-, soja-, amandelmelk

    # DAIRY
    "Milk (Fresh)",             # Verse melk, volle/halfvolle/magere
    "Milk (Long Life)",         # Houdbare melk, UHT
    "Cream",                    # Room, kookroom, slagroom
    "Yoghurt (Natural)",        # Natuurlijke yoghurt, Griekse yoghurt
    "Yoghurt (Fruit)",          # Fruityoghurt, Activia, Danone
    "Yoghurt Drinks",           # Yakult, Actimel, drinkjoghurt
    "Skyr & Quark",             # Skyr, platte kaas
    "Pudding & Desserts",       # Pudding, mousse, rijstpap, Dame Blanche
    "Butter",                   # Boter, roomboter
    "Margarine",                # Margarine, Becel, Planta
    "Cooking Fat",              # Bak en braad, kokosolie, frituurvet

    # CHEESE
    "Cheese (Hard)",            # Gouda, Emmental, Gruyère, Parmesan
    "Cheese (Soft)",            # Brie, Camembert
    "Cheese (Blue)",            # Roquefort, Gorgonzola
    "Cheese (Fresh)",           # Mozzarella, feta, ricotta, mascarpone
    "Cheese (Spread)",          # Smeerkaas, Philadelphia, Boursin
    "Cheese (Sliced)",          # Plakjes kaas, voor boterham
    "Cheese (Grated)",          # Geraspte kaas
    "Cheese (Belgian)",         # Abdijkaas, Passendale, Herve, Chimay

    # EGGS
    "Eggs",

    # MEAT
    "Beef",                     # Rundvlees, steak, gehakt
    "Pork",                     # Varkensvlees, kotelet, spek
    "Chicken",                  # Kip, kipfilet, kippenbout
    "Turkey",                   # Kalkoen
    "Lamb",
    "Minced Meat",              # Gehakt (rund, varken, gemengd)
    "Meat Preparations",        # Marinades, brochettes, burgers
    "Offal",                    # Orgaanvlees, lever

    # CHARCUTERIE
    "Ham (Cooked)",             # Gekookte ham, schouderham
    "Ham (Dry)",                # Droge ham, Ardenner ham, Serrano, Parma
    "Salami & Sausage",         # Salami, chorizo, worst, merguez
    "Pâté & Terrine",           # Paté, leverpaté, terrine
    "Bacon & Lardons",          # Spek, ontbijtspek, lardons
    "Chicken/Turkey Deli",      # Kipfilet, kalkoenblanken
    "Vegetarian Deli",          # Veggie charcuterie

    # FISH & SEAFOOD
    "Fish (Fresh)",             # Verse vis, zalm, kabeljauw
    "Fish (Smoked)",            # Gerookte zalm, makreel
    "Fish (Frozen)",            # Diepvries vis, vissticks
    "Shellfish",                # Garnalen, mosselen, scampi
    "Canned Fish",              # Tonijn, sardines, makreel in blik
    "Surimi",                   # Surimi, krabsticks

    # FRUITS
    "Fruit (Apples/Pears)",     # Appels, peren
    "Fruit (Citrus)",           # Sinaasappels, citroenen, mandarijnen
    "Fruit (Bananas)",
    "Fruit (Berries)",          # Aardbeien, frambozen, blauwe bessen
    "Fruit (Stone)",            # Perziken, pruimen, abrikozen, kersen
    "Fruit (Grapes)",
    "Fruit (Melons)",           # Meloen, watermeloen
    "Fruit (Tropical)",         # Ananas, mango, kiwi, passievrucht
    "Fruit (Dried)",            # Gedroogd fruit, rozijnen, dadels
    "Nuts",                     # Noten, amandelen, walnoten, cashew

    # VEGETABLES
    "Tomatoes",
    "Salad & Leafy Greens",     # Sla, spinazie, rucola
    "Cucumber & Peppers",       # Komkommer, paprika
    "Onions & Garlic",          # Ui, look, sjalot, prei
    "Carrots & Root Veg",       # Wortelen, rapen, pastinaak
    "Potatoes",                 # Aardappelen
    "Cabbage & Broccoli",       # Kool, broccoli, bloemkool
    "Beans & Peas",             # Sperziebonen, erwten, peultjes
    "Mushrooms",                # Champignons, paddenstoelen
    "Zucchini & Eggplant",      # Courgette, aubergine
    "Corn",                     # Maïs
    "Fresh Herbs",              # Verse kruiden, basilicum, peterselie
    "Prepared Vegetables",      # Voorgesneden groenten, slakmix

    # BREAD & BAKERY
    "Bread (Fresh)",            # Vers brood, wit, grijs, volkoren
    "Bread (Sliced)",           # Gesneden brood, pistolets
    "Bread (Specialty)",        # Ciabatta, focaccia, stokbrood
    "Wraps & Pita",             # Wraps, pita, tortilla
    "Croissants & Pastries",    # Croissants, koffiekoeken, pain au chocolat
    "Cakes & Tarts",            # Taart, cake, vlaai
    "Cookies & Biscuits",       # Koekjes, speculoos, bastogne
    "Waffles",                  # Wafels, Luikse wafels
    "Crackers",                 # Crackers, rijstwafels, beschuiten

    # PASTA, RICE & GRAINS
    "Pasta (Dry)",              # Spaghetti, penne, macaroni
    "Pasta (Fresh)",            # Verse pasta, ravioli, tortellini
    "Rice",                     # Rijst, basmati, risotto, volkoren
    "Noodles (Asian)",          # Noedels, mie, rijstnoedels
    "Couscous & Bulgur",        # Couscous, bulgur, quinoa
    "Grains & Legumes",         # Linzen, kikkererwten, bonen droog

    # CANNED & JARRED
    "Canned Tomatoes",          # Tomaten in blik, passata, tomatenpuree
    "Canned Vegetables",        # Groenten in blik, maïs, erwten
    "Canned Beans",             # Bonen in blik, kikkererwten, linzen
    "Canned Fruits",            # Fruit in blik, perziken, ananas
    "Pickles & Olives",         # Augurken, olijven, kappertjes
    "Jarred Antipasti",         # Zongedroogde tomaten, artisjok

    # SAUCES & CONDIMENTS
    "Pasta Sauce",              # Pastasaus, pesto, Bolognese
    "Tomato Sauce & Ketchup",
    "Mayonnaise",               # Mayonaise, andalouse, cocktail
    "Mustard",                  # Mosterd, moutarde
    "Soy & Asian Sauce",        # Sojasaus, teriyaki, hoisin
    "BBQ Sauce",                # BBQ saus, steaksaus
    "Salad Dressing",           # Dressing, vinaigrette
    "Vinegar",                  # Azijn, balsamico
    "Olive Oil",
    "Cooking Oil",              # Zonnebloemolie, arachideolie
    "Salt, Pepper & Spices",    # Zout, peper, kruiden
    "Stock & Bouillon",         # Bouillonblokjes, fond
    "Dried Herbs",              # Gedroogde kruiden

    # BREAKFAST
    "Cereals",                  # Cornflakes, muesli, granola
    "Oatmeal",                  # Havermout, porridge
    "Spreads (Chocolate)",      # Nutella, Côte d'Or, choco
    "Spreads (Jam)",            # Confituur, jam, marmelade
    "Spreads (Honey)",
    "Spreads (Peanut/Nut)",     # Pindakaas, notenboter
    "Spreads (Savory)",         # Smeerworst, leverpaté voor brood

    # SOUP
    "Soup (Canned)",
    "Soup (Carton/Fresh)",      # Soep in pak, verse soep
    "Soup (Instant)",           # Instant soep, zakjes

    # SNACKS
    "Chips",                    # Chips, Lays, Pringles
    "Nuts (Snack)",             # Nootjes, gezouten, cocktailnoten
    "Crackers (Snack)",         # Aperokoekjes, soepstengels, TUC
    "Popcorn",
    "Dried Meat Snack",         # Biltong, beef jerky

    # SWEETS & CHOCOLATE
    "Chocolate Bars",           # Chocoladerepen, Côte d'Or, Milka
    "Chocolate Pralines",       # Pralines, bonbons, Leonidas
    "Chocolate (Baking)",       # Bakchocolade, chocolade druppels
    "Candy",                    # Snoep, zuurtjes, lolly
    "Licorice",                 # Drop
    "Gum & Mints",              # Kauwgom, pepermunt
    "Marshmallows",             # Marshmallows, schuimpjes

    # FROZEN - SAVORY
    "Frozen Fries",             # Frieten, kroketten, aardappel
    "Frozen Pizza",
    "Frozen Meals",             # Diepvries maaltijden
    "Frozen Vegetables",
    "Frozen Fish",              # Diepvries vis, vissticks
    "Frozen Meat",              # Diepvries vlees, burgers
    "Frozen Snacks",            # Loempia, bitterballen
    "Frozen Bread",             # Diepvries brood, afbakbroodjes

    # FROZEN - SWEET
    "Ice Cream",                # Ijs, roomijs, Magnum, Ben & Jerry's
    "Frozen Desserts",          # Diepvries desserts, taart
    "Frozen Fruits",

    # READY MEALS
    "Meals (Fresh)",            # Verse maaltijden, kant-en-klaar
    "Meals (Salads)",           # Prepared salads, tabouleh
    "Pizza (Fresh)",            # Verse pizza
    "Sandwiches",               # Belegde broodjes
    "Sushi",                    # Sushi, poke bowl
    "Hummus & Dips",            # Hummus, guacamole, tzatziki

    # VEGETARIAN & VEGAN
    "Meat Substitute",          # Veggie burger, tofu, tempeh, seitan
    "Vegetarian Meals",
    "Vegan Cheese/Dairy",       # Vegan kaas, plantaardige room

    # WORLD FOOD
    "Asian Food",               # Wok, Aziatische producten
    "Mexican Food",             # Taco, nachos, salsa
    "Italian Specialty",        # Antipasti, Italiaanse specialiteiten
    "Middle Eastern",           # Falafel, tahini

    # BAKING
    "Flour",                    # Bloem, zelfrijzend bakmeel
    "Sugar",                    # Suiker, bruine suiker, poedersuiker
    "Baking Ingredients",       # Bakpoeder, gist, vanille
    "Baking Decorations",       # Glazuur, decoratie, marsepein

    # BABY
    "Baby Milk",                # Babymelk, opvolgmelk
    "Baby Food",                # Potjes, babyvoeding
    "Baby Snacks",              # Baby koekjes, puffs
    "Diapers",                  # Luiers, Pampers
    "Baby Care",                # Babyverzorging, doekjes

    # HOUSEHOLD - CLEANING
    "Cleaning (All-Purpose)",
    "Cleaning (Kitchen)",       # Afwasmiddel, ontvetter
    "Cleaning (Bathroom)",      # Badkamerreiniger, ontkalker
    "Cleaning (Floor)",
    "Cleaning (Glass)",
    "Cleaning (WC)",            # WC reiniger, WC blokjes
    "Cleaning Tools",           # Sponzen, dweilen, bezems
    "Trash Bags",

    # HOUSEHOLD - LAUNDRY
    "Laundry Detergent",        # Wasmiddel, waspoeder, pods
    "Laundry Softener",         # Wasverzachter
    "Laundry (Stain Remover)",
    "Laundry (Ironing)",

    # HOUSEHOLD - PAPER
    "Toilet Paper",
    "Kitchen Paper",
    "Tissues",
    "Napkins",

    # PERSONAL CARE - BODY
    "Shower Gel",               # Douchegel, badschuim
    "Soap",                     # Zeep, handzeep
    "Deodorant",
    "Body Lotion",
    "Sunscreen",

    # PERSONAL CARE - HAIR
    "Shampoo",
    "Conditioner",
    "Hair Styling",             # Gel, wax, haarlak
    "Hair Color",

    # PERSONAL CARE - FACE & ORAL
    "Face Care",                # Gezichtsverzorging, crème
    "Toothpaste",
    "Toothbrush",
    "Mouthwash",
    "Shaving",                  # Scheermesjes, scheerschuim

    # PERSONAL CARE - HEALTH
    "Feminine Hygiene",         # Maandverband, tampons
    "Contraception",
    "First Aid",                # Pleisters, verband
    "Vitamins & Supplements",
    "Pain Relief",

    # PET SUPPLIES
    "Pet Food (Dog)",
    "Pet Food (Cat)",
    "Pet Treats",
    "Pet Litter",               # Kattenbak vulling
    "Pet Care",

    # OTHER
    "Tobacco",
    "Batteries",
    "Lightbulbs",
    "Kitchen Accessories",
    "Party Supplies",
    "Flowers & Plants",
    "Other",
]

# Categories as a comma-separated string for LLM prompts
CATEGORIES_LIST_STR = ", ".join(f'"{cat}"' for cat in CATEGORIES)

# Generate category prompt section for LLM
CATEGORY_PROMPT_SECTION = """ALCOHOLIC DRINKS: "Beer (Pils)", "Beer (Abbey/Trappist)", "Beer (Special)", "Beer (White/Fruit)", "Beer (Non-Alcoholic)", "Cider", "Wine (Red)", "Wine (White)", "Wine (Rosé)", "Wine (Sparkling)", "Spirits (Whisky)", "Spirits (Gin)", "Spirits (Vodka)", "Spirits (Rum)", "Spirits (Liqueur)", "Aperitif"
NON-ALCOHOLIC DRINKS: "Cola", "Lemonade & Soda", "Energy Drinks", "Ice Tea", "Water (Still)", "Water (Sparkling)", "Water (Flavored)", "Fruit Juice", "Vegetable Juice", "Smoothies", "Syrup", "Coffee (Beans/Ground)", "Coffee (Capsules)", "Coffee (Instant)", "Tea", "Hot Chocolate", "Plant Milk"
DAIRY: "Milk (Fresh)", "Milk (Long Life)", "Cream", "Yoghurt (Natural)", "Yoghurt (Fruit)", "Yoghurt Drinks", "Skyr & Quark", "Pudding & Desserts", "Butter", "Margarine", "Cooking Fat"
CHEESE: "Cheese (Hard)", "Cheese (Soft)", "Cheese (Blue)", "Cheese (Fresh)", "Cheese (Spread)", "Cheese (Sliced)", "Cheese (Grated)", "Cheese (Belgian)"
EGGS: "Eggs"
MEAT: "Beef", "Pork", "Chicken", "Turkey", "Lamb", "Minced Meat", "Meat Preparations", "Offal"
CHARCUTERIE: "Ham (Cooked)", "Ham (Dry)", "Salami & Sausage", "Pâté & Terrine", "Bacon & Lardons", "Chicken/Turkey Deli", "Vegetarian Deli"
FISH & SEAFOOD: "Fish (Fresh)", "Fish (Smoked)", "Fish (Frozen)", "Shellfish", "Canned Fish", "Surimi"
FRUITS: "Fruit (Apples/Pears)", "Fruit (Citrus)", "Fruit (Bananas)", "Fruit (Berries)", "Fruit (Stone)", "Fruit (Grapes)", "Fruit (Melons)", "Fruit (Tropical)", "Fruit (Dried)", "Nuts"
VEGETABLES: "Tomatoes", "Salad & Leafy Greens", "Cucumber & Peppers", "Onions & Garlic", "Carrots & Root Veg", "Potatoes", "Cabbage & Broccoli", "Beans & Peas", "Mushrooms", "Zucchini & Eggplant", "Corn", "Fresh Herbs", "Prepared Vegetables"
BREAD & BAKERY: "Bread (Fresh)", "Bread (Sliced)", "Bread (Specialty)", "Wraps & Pita", "Croissants & Pastries", "Cakes & Tarts", "Cookies & Biscuits", "Waffles", "Crackers"
PASTA, RICE & GRAINS: "Pasta (Dry)", "Pasta (Fresh)", "Rice", "Noodles (Asian)", "Couscous & Bulgur", "Grains & Legumes"
CANNED & JARRED: "Canned Tomatoes", "Canned Vegetables", "Canned Beans", "Canned Fruits", "Pickles & Olives", "Jarred Antipasti"
SAUCES & CONDIMENTS: "Pasta Sauce", "Tomato Sauce & Ketchup", "Mayonnaise", "Mustard", "Soy & Asian Sauce", "BBQ Sauce", "Salad Dressing", "Vinegar", "Olive Oil", "Cooking Oil", "Salt, Pepper & Spices", "Stock & Bouillon", "Dried Herbs"
BREAKFAST: "Cereals", "Oatmeal", "Spreads (Chocolate)", "Spreads (Jam)", "Spreads (Honey)", "Spreads (Peanut/Nut)", "Spreads (Savory)"
SOUP: "Soup (Canned)", "Soup (Carton/Fresh)", "Soup (Instant)"
SNACKS: "Chips", "Nuts (Snack)", "Crackers (Snack)", "Popcorn", "Dried Meat Snack"
SWEETS & CHOCOLATE: "Chocolate Bars", "Chocolate Pralines", "Chocolate (Baking)", "Candy", "Licorice", "Gum & Mints", "Marshmallows"
FROZEN: "Frozen Fries", "Frozen Pizza", "Frozen Meals", "Frozen Vegetables", "Frozen Fish", "Frozen Meat", "Frozen Snacks", "Frozen Bread", "Ice Cream", "Frozen Desserts", "Frozen Fruits"
READY MEALS: "Meals (Fresh)", "Meals (Salads)", "Pizza (Fresh)", "Sandwiches", "Sushi", "Hummus & Dips"
VEGETARIAN & VEGAN: "Meat Substitute", "Vegetarian Meals", "Vegan Cheese/Dairy"
WORLD FOOD: "Asian Food", "Mexican Food", "Italian Specialty", "Middle Eastern"
BAKING: "Flour", "Sugar", "Baking Ingredients", "Baking Decorations"
BABY: "Baby Milk", "Baby Food", "Baby Snacks", "Diapers", "Baby Care"
HOUSEHOLD - CLEANING: "Cleaning (All-Purpose)", "Cleaning (Kitchen)", "Cleaning (Bathroom)", "Cleaning (Floor)", "Cleaning (Glass)", "Cleaning (WC)", "Cleaning Tools", "Trash Bags"
HOUSEHOLD - LAUNDRY: "Laundry Detergent", "Laundry Softener", "Laundry (Stain Remover)", "Laundry (Ironing)"
HOUSEHOLD - PAPER: "Toilet Paper", "Kitchen Paper", "Tissues", "Napkins"
PERSONAL CARE - BODY: "Shower Gel", "Soap", "Deodorant", "Body Lotion", "Sunscreen"
PERSONAL CARE - HAIR: "Shampoo", "Conditioner", "Hair Styling", "Hair Color"
PERSONAL CARE - FACE & ORAL: "Face Care", "Toothpaste", "Toothbrush", "Mouthwash", "Shaving"
PERSONAL CARE - HEALTH: "Feminine Hygiene", "Contraception", "First Aid", "Vitamins & Supplements", "Pain Relief"
PET SUPPLIES: "Pet Food (Dog)", "Pet Food (Cat)", "Pet Treats", "Pet Litter", "Pet Care"
OTHER: "Tobacco", "Batteries", "Lightbulbs", "Kitchen Accessories", "Party Supplies", "Flowers & Plants", "Other\""""
