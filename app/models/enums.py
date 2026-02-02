from enum import Enum


class Category(str, Enum):
    # ==========================================
    # DRINKS - ALCOHOLIC
    # ==========================================
    BEER_PILS = "Beer (Pils)"                        # Jupiler, Stella, Maes, Cristal
    BEER_ABBEY_TRAPPIST = "Beer (Abbey/Trappist)"    # Leffe, Grimbergen, Westmalle, Chimay
    BEER_SPECIAL = "Beer (Special)"                  # Duvel, Chouffe, Karmeliet, Delirium
    BEER_WHITE_FRUIT = "Beer (White/Fruit)"          # Hoegaarden, Kriek, Pêcheresse
    BEER_NONALCOHOLIC = "Beer (Non-Alcoholic)"       # Jupiler 0.0, Leffe 0.0, Tourtel
    CIDER = "Cider"                                  # Stassen, Strongbow
    WINE_RED = "Wine (Red)"
    WINE_WHITE = "Wine (White)"
    WINE_ROSE = "Wine (Rosé)"
    WINE_SPARKLING = "Wine (Sparkling)"              # Cava, Prosecco, Champagne
    SPIRITS_WHISKY = "Spirits (Whisky)"
    SPIRITS_GIN = "Spirits (Gin)"                    # Gin, jenever
    SPIRITS_VODKA = "Spirits (Vodka)"
    SPIRITS_RUM = "Spirits (Rum)"
    SPIRITS_LIQUEUR = "Spirits (Liqueur)"            # Likeur, Amaretto, Baileys
    APERITIF = "Aperitif"                            # Martini, Porto, Sherry, Pastis

    # ==========================================
    # DRINKS - NON-ALCOHOLIC
    # ==========================================
    COLA = "Cola"                                    # Coca-Cola, Pepsi, cola zero
    LEMONADE_SODA = "Lemonade & Soda"                # Fanta, Sprite, 7up, Orangina
    ENERGY_DRINKS = "Energy Drinks"                  # Red Bull, Monster, Nalu
    ICE_TEA = "Ice Tea"                              # Lipton, Fuze Tea
    WATER_STILL = "Water (Still)"                    # Spa Reine, Evian, Vittel
    WATER_SPARKLING = "Water (Sparkling)"            # Spa Barisart, Bru, Perrier
    WATER_FLAVORED = "Water (Flavored)"              # Spa Touch, gearomatiseerd water
    FRUIT_JUICE = "Fruit Juice"                      # Appelsap, sinaasappelsap, Tropicana
    VEGETABLE_JUICE = "Vegetable Juice"              # Tomatensap, groentesap
    SMOOTHIES = "Smoothies"
    SYRUP = "Syrup"                                  # Grenadine, citroen siroop, Teisseire
    COFFEE_BEANS_GROUND = "Coffee (Beans/Ground)"    # Koffiebonen, gemalen koffie
    COFFEE_CAPSULES = "Coffee (Capsules)"            # Nespresso, Dolce Gusto, Tassimo
    COFFEE_INSTANT = "Coffee (Instant)"              # Oploskoffie, Nescafé
    TEA = "Tea"                                      # Thee, kruidenthee, groene thee
    HOT_CHOCOLATE = "Hot Chocolate"                  # Cacao, chocolademelk poeder
    PLANT_MILK = "Plant Milk"                        # Haver-, soja-, amandelmelk

    # ==========================================
    # DAIRY
    # ==========================================
    MILK_FRESH = "Milk (Fresh)"                      # Verse melk, volle/halfvolle/magere
    MILK_LONG_LIFE = "Milk (Long Life)"              # Houdbare melk, UHT
    CREAM = "Cream"                                  # Room, kookroom, slagroom
    YOGHURT_NATURAL = "Yoghurt (Natural)"            # Natuurlijke yoghurt, Griekse yoghurt
    YOGHURT_FRUIT = "Yoghurt (Fruit)"                # Fruityoghurt, Activia, Danone
    YOGHURT_DRINKS = "Yoghurt Drinks"                # Yakult, Actimel, drinkjoghurt
    SKYR_QUARK = "Skyr & Quark"                      # Skyr, platte kaas
    PUDDING_DESSERTS = "Pudding & Desserts"          # Pudding, mousse, rijstpap, Dame Blanche
    BUTTER = "Butter"                                # Boter, roomboter
    MARGARINE = "Margarine"                          # Margarine, Becel, Planta
    COOKING_FAT = "Cooking Fat"                      # Bak en braad, kokosolie, frituurvet

    # ==========================================
    # CHEESE
    # ==========================================
    CHEESE_HARD = "Cheese (Hard)"                    # Gouda, Emmental, Gruyère, Parmesan
    CHEESE_SOFT = "Cheese (Soft)"                    # Brie, Camembert
    CHEESE_BLUE = "Cheese (Blue)"                    # Roquefort, Gorgonzola
    CHEESE_FRESH = "Cheese (Fresh)"                  # Mozzarella, feta, ricotta, mascarpone
    CHEESE_SPREAD = "Cheese (Spread)"                # Smeerkaas, Philadelphia, Boursin
    CHEESE_SLICED = "Cheese (Sliced)"                # Plakjes kaas, voor boterham
    CHEESE_GRATED = "Cheese (Grated)"                # Geraspte kaas
    CHEESE_BELGIAN = "Cheese (Belgian)"              # Abdijkaas, Passendale, Herve, Chimay

    # ==========================================
    # EGGS
    # ==========================================
    EGGS = "Eggs"

    # ==========================================
    # MEAT - FRESH
    # ==========================================
    BEEF = "Beef"                                    # Rundvlees, steak, gehakt
    PORK = "Pork"                                    # Varkensvlees, kotelet, spek
    CHICKEN = "Chicken"                              # Kip, kipfilet, kippenbout
    TURKEY = "Turkey"                                # Kalkoen
    LAMB = "Lamb"
    MINCED_MEAT = "Minced Meat"                      # Gehakt (rund, varken, gemengd)
    MEAT_PREPARATIONS = "Meat Preparations"          # Marinades, brochettes, burgers
    OFFAL = "Offal"                                  # Orgaanvlees, lever

    # ==========================================
    # CHARCUTERIE & DELI
    # ==========================================
    HAM_COOKED = "Ham (Cooked)"                      # Gekookte ham, schouderham
    HAM_DRY = "Ham (Dry)"                            # Droge ham, Ardenner ham, Serrano, Parma
    SALAMI_SAUSAGE = "Salami & Sausage"              # Salami, chorizo, worst, merguez
    PATE_TERRINE = "Pâté & Terrine"                  # Paté, leverpaté, terrine
    BACON_LARDONS = "Bacon & Lardons"                # Spek, ontbijtspek, lardons
    CHICKEN_TURKEY_DELI = "Chicken/Turkey Deli"      # Kipfilet, kalkoenblanken
    VEGETARIAN_DELI = "Vegetarian Deli"              # Veggie charcuterie

    # ==========================================
    # FISH & SEAFOOD
    # ==========================================
    FISH_FRESH = "Fish (Fresh)"                      # Verse vis, zalm, kabeljauw
    FISH_SMOKED = "Fish (Smoked)"                    # Gerookte zalm, makreel
    FISH_FROZEN = "Fish (Frozen)"                    # Diepvries vis, vissticks
    SHELLFISH = "Shellfish"                          # Garnalen, mosselen, scampi
    CANNED_FISH = "Canned Fish"                      # Tonijn, sardines, makreel in blik
    SURIMI = "Surimi"                                # Surimi, krabsticks

    # ==========================================
    # FRUITS
    # ==========================================
    FRUIT_APPLES_PEARS = "Fruit (Apples/Pears)"      # Appels, peren
    FRUIT_CITRUS = "Fruit (Citrus)"                  # Sinaasappels, citroenen, mandarijnen
    FRUIT_BANANAS = "Fruit (Bananas)"
    FRUIT_BERRIES = "Fruit (Berries)"                # Aardbeien, frambozen, blauwe bessen
    FRUIT_STONE = "Fruit (Stone)"                    # Perziken, pruimen, abrikozen, kersen
    FRUIT_GRAPES = "Fruit (Grapes)"
    FRUIT_MELONS = "Fruit (Melons)"                  # Meloen, watermeloen
    FRUIT_TROPICAL = "Fruit (Tropical)"              # Ananas, mango, kiwi, passievrucht
    FRUIT_DRIED = "Fruit (Dried)"                    # Gedroogd fruit, rozijnen, dadels
    FRUIT_NUTS = "Nuts"                              # Noten, amandelen, walnoten, cashew

    # ==========================================
    # VEGETABLES
    # ==========================================
    VEG_TOMATOES = "Tomatoes"
    VEG_SALAD_LEAFY = "Salad & Leafy Greens"         # Sla, spinazie, rucola
    VEG_CUCUMBER_PEPPERS = "Cucumber & Peppers"      # Komkommer, paprika
    VEG_ONIONS_GARLIC = "Onions & Garlic"            # Ui, look, sjalot, prei
    VEG_CARROTS_ROOTS = "Carrots & Root Veg"         # Wortelen, rapen, pastinaak
    VEG_POTATOES = "Potatoes"                        # Aardappelen
    VEG_CABBAGE = "Cabbage & Broccoli"               # Kool, broccoli, bloemkool
    VEG_BEANS_PEAS = "Beans & Peas"                  # Sperziebonen, erwten, peultjes
    VEG_MUSHROOMS = "Mushrooms"                      # Champignons, paddenstoelen
    VEG_ZUCCHINI_EGGPLANT = "Zucchini & Eggplant"    # Courgette, aubergine
    VEG_CORN = "Corn"                                # Maïs
    VEG_FRESH_HERBS = "Fresh Herbs"                  # Verse kruiden, basilicum, peterselie
    VEG_PREPARED = "Prepared Vegetables"             # Voorgesneden groenten, slakmix

    # ==========================================
    # BREAD & BAKERY
    # ==========================================
    BREAD_FRESH = "Bread (Fresh)"                    # Vers brood, wit, grijs, volkoren
    BREAD_SLICED = "Bread (Sliced)"                  # Gesneden brood, pistolets
    BREAD_SPECIALTY = "Bread (Specialty)"            # Ciabatta, focaccia, stokbrood
    BREAD_WRAPS_PITA = "Wraps & Pita"                # Wraps, pita, tortilla
    CROISSANTS_PASTRIES = "Croissants & Pastries"    # Croissants, koffiekoeken, pain au chocolat
    CAKES_TARTS = "Cakes & Tarts"                    # Taart, cake, vlaai
    COOKIES_BISCUITS = "Cookies & Biscuits"          # Koekjes, speculoos, bastogne
    WAFFLES = "Waffles"                              # Wafels, Luikse wafels
    CRACKERS = "Crackers"                            # Crackers, rijstwafels, beschuiten

    # ==========================================
    # PASTA, RICE & GRAINS
    # ==========================================
    PASTA_DRY = "Pasta (Dry)"                        # Spaghetti, penne, macaroni
    PASTA_FRESH = "Pasta (Fresh)"                    # Verse pasta, ravioli, tortellini
    RICE = "Rice"                                    # Rijst, basmati, risotto, volkoren
    NOODLES_ASIAN = "Noodles (Asian)"                # Noedels, mie, rijstnoedels
    COUSCOUS_BULGUR = "Couscous & Bulgur"            # Couscous, bulgur, quinoa
    GRAINS_LEGUMES = "Grains & Legumes"              # Linzen, kikkererwten, bonen droog

    # ==========================================
    # CANNED & JARRED
    # ==========================================
    CANNED_TOMATOES = "Canned Tomatoes"              # Tomaten in blik, passata, tomatenpuree
    CANNED_VEGETABLES = "Canned Vegetables"          # Groenten in blik, maïs, erwten
    CANNED_BEANS = "Canned Beans"                    # Bonen in blik, kikkererwten, linzen
    CANNED_FRUITS = "Canned Fruits"                  # Fruit in blik, perziken, ananas
    PICKLES_OLIVES = "Pickles & Olives"              # Augurken, olijven, kappertjes
    JARRED_ANTIPASTI = "Jarred Antipasti"            # Zongedroogde tomaten, artisjok

    # ==========================================
    # SAUCES & CONDIMENTS
    # ==========================================
    PASTA_SAUCE = "Pasta Sauce"                      # Pastasaus, pesto, Bolognese
    TOMATO_SAUCE_KETCHUP = "Tomato Sauce & Ketchup"
    MAYONNAISE = "Mayonnaise"                        # Mayonaise, andalouse, cocktail
    MUSTARD = "Mustard"                              # Mosterd, moutarde
    SOY_ASIAN_SAUCE = "Soy & Asian Sauce"            # Sojasaus, teriyaki, hoisin
    BBQ_SAUCE = "BBQ Sauce"                          # BBQ saus, steaksaus
    SALAD_DRESSING = "Salad Dressing"                # Dressing, vinaigrette
    VINEGAR = "Vinegar"                              # Azijn, balsamico
    OIL_OLIVE = "Olive Oil"
    OIL_COOKING = "Cooking Oil"                      # Zonnebloemolie, arachideolie
    SALT_PEPPER_SPICES = "Salt, Pepper & Spices"     # Zout, peper, kruiden
    STOCK_BOUILLON = "Stock & Bouillon"              # Bouillonblokjes, fond
    HERBS_DRIED = "Dried Herbs"                      # Gedroogde kruiden

    # ==========================================
    # BREAKFAST
    # ==========================================
    CEREALS = "Cereals"                              # Cornflakes, muesli, granola
    OATMEAL = "Oatmeal"                              # Havermout, porridge
    SPREADS_CHOCOLATE = "Spreads (Chocolate)"        # Nutella, Côte d'Or, choco
    SPREADS_JAM = "Spreads (Jam)"                    # Confituur, jam, marmelade
    SPREADS_HONEY = "Spreads (Honey)"
    SPREADS_PEANUT = "Spreads (Peanut/Nut)"          # Pindakaas, notenboter
    SPREADS_SAVORY = "Spreads (Savory)"              # Smeerworst, leverpaté voor brood

    # ==========================================
    # SOUP
    # ==========================================
    SOUP_CANNED = "Soup (Canned)"
    SOUP_CARTON = "Soup (Carton/Fresh)"              # Soep in pak, verse soep
    SOUP_INSTANT = "Soup (Instant)"                  # Instant soep, zakjes

    # ==========================================
    # SNACKS - SAVORY
    # ==========================================
    CHIPS = "Chips"                                  # Chips, Lays, Pringles
    NUTS_SNACK = "Nuts (Snack)"                      # Nootjes, gezouten, cocktailnoten
    CRACKERS_SNACK = "Crackers (Snack)"              # Aperokoekjes, soepstengels, TUC
    POPCORN = "Popcorn"
    DRIED_MEAT_SNACK = "Dried Meat Snack"            # Biltong, beef jerky

    # ==========================================
    # SWEETS & CHOCOLATE
    # ==========================================
    CHOCOLATE_BARS = "Chocolate Bars"                # Chocoladerepen, Côte d'Or, Milka
    CHOCOLATE_PRALINES = "Chocolate Pralines"        # Pralines, bonbons, Leonidas
    CHOCOLATE_BAKING = "Chocolate (Baking)"          # Bakchocolade, chocolade druppels
    CANDY = "Candy"                                  # Snoep, zuurtjes, lolly
    LICORICE = "Licorice"                            # Drop
    GUM_MINTS = "Gum & Mints"                        # Kauwgom, pepermunt
    MARSHMALLOWS = "Marshmallows"                    # Marshmallows, schuimpjes

    # ==========================================
    # FROZEN - SAVORY
    # ==========================================
    FROZEN_FRIES = "Frozen Fries"                    # Frieten, kroketten, aardappel
    FROZEN_PIZZA = "Frozen Pizza"
    FROZEN_MEALS = "Frozen Meals"                    # Diepvries maaltijden
    FROZEN_VEGETABLES = "Frozen Vegetables"
    FROZEN_FISH = "Frozen Fish"                      # Diepvries vis, vissticks
    FROZEN_MEAT = "Frozen Meat"                      # Diepvries vlees, burgers
    FROZEN_SNACKS = "Frozen Snacks"                  # Loempia, bitterballen
    FROZEN_BREAD = "Frozen Bread"                    # Diepvries brood, afbakbroodjes

    # ==========================================
    # FROZEN - SWEET
    # ==========================================
    ICE_CREAM = "Ice Cream"                          # Ijs, roomijs, Magnum, Ben & Jerry's
    FROZEN_DESSERTS = "Frozen Desserts"              # Diepvries desserts, taart
    FROZEN_FRUITS = "Frozen Fruits"

    # ==========================================
    # READY MEALS & PREPARED
    # ==========================================
    MEALS_FRESH = "Meals (Fresh)"                    # Verse maaltijden, kant-en-klaar
    MEALS_SALADS = "Meals (Salads)"                  # Prepared salads, tabouleh
    PIZZA_FRESH = "Pizza (Fresh)"                    # Verse pizza
    SANDWICHES = "Sandwiches"                        # Belegde broodjes
    SUSHI = "Sushi"                                  # Sushi, poke bowl
    HUMMUS_DIPS = "Hummus & Dips"                    # Hummus, guacamole, tzatziki

    # ==========================================
    # VEGETARIAN & VEGAN
    # ==========================================
    MEAT_SUBSTITUTE = "Meat Substitute"              # Veggie burger, tofu, tempeh, seitan
    VEGETARIAN_MEALS = "Vegetarian Meals"
    VEGAN_CHEESE_DAIRY = "Vegan Cheese/Dairy"        # Vegan kaas, plantaardige room

    # ==========================================
    # WORLD FOOD
    # ==========================================
    ASIAN_FOOD = "Asian Food"                        # Wok, Aziatische producten
    MEXICAN_FOOD = "Mexican Food"                    # Taco, nachos, salsa
    ITALIAN_SPECIALTY = "Italian Specialty"          # Antipasti, Italiaanse specialiteiten
    MIDDLE_EASTERN = "Middle Eastern"                # Falafel, tahini

    # ==========================================
    # BAKING & DESSERT MAKING
    # ==========================================
    FLOUR = "Flour"                                  # Bloem, zelfrijzend bakmeel
    SUGAR = "Sugar"                                  # Suiker, bruine suiker, poedersuiker
    BAKING_INGREDIENTS = "Baking Ingredients"        # Bakpoeder, gist, vanille
    BAKING_DECORATIONS = "Baking Decorations"        # Glazuur, decoratie, marsepein

    # ==========================================
    # BABY
    # ==========================================
    BABY_MILK = "Baby Milk"                          # Babymelk, opvolgmelk
    BABY_FOOD = "Baby Food"                          # Potjes, babyvoeding
    BABY_SNACKS = "Baby Snacks"                      # Baby koekjes, puffs
    DIAPERS = "Diapers"                              # Luiers, Pampers
    BABY_CARE = "Baby Care"                          # Babyverzorging, doekjes

    # ==========================================
    # HOUSEHOLD - CLEANING
    # ==========================================
    CLEANING_ALLPURPOSE = "Cleaning (All-Purpose)"
    CLEANING_KITCHEN = "Cleaning (Kitchen)"          # Afwasmiddel, ontvetter
    CLEANING_BATHROOM = "Cleaning (Bathroom)"        # Badkamerreiniger, ontkalker
    CLEANING_FLOOR = "Cleaning (Floor)"
    CLEANING_GLASS = "Cleaning (Glass)"
    CLEANING_WC = "Cleaning (WC)"                    # WC reiniger, WC blokjes
    CLEANING_TOOLS = "Cleaning Tools"                # Sponzen, dweilen, bezems
    TRASH_BAGS = "Trash Bags"

    # ==========================================
    # HOUSEHOLD - LAUNDRY
    # ==========================================
    LAUNDRY_DETERGENT = "Laundry Detergent"          # Wasmiddel, waspoeder, pods
    LAUNDRY_SOFTENER = "Laundry Softener"            # Wasverzachter
    LAUNDRY_STAIN = "Laundry (Stain Remover)"
    LAUNDRY_IRONING = "Laundry (Ironing)"

    # ==========================================
    # HOUSEHOLD - PAPER
    # ==========================================
    TOILET_PAPER = "Toilet Paper"
    KITCHEN_PAPER = "Kitchen Paper"
    TISSUES = "Tissues"
    NAPKINS = "Napkins"

    # ==========================================
    # PERSONAL CARE - BODY
    # ==========================================
    SHOWER_GEL = "Shower Gel"                        # Douchegel, badschuim
    SOAP = "Soap"                                    # Zeep, handzeep
    DEODORANT = "Deodorant"
    BODY_LOTION = "Body Lotion"
    SUNSCREEN = "Sunscreen"

    # ==========================================
    # PERSONAL CARE - HAIR
    # ==========================================
    SHAMPOO = "Shampoo"
    CONDITIONER = "Conditioner"
    HAIR_STYLING = "Hair Styling"                    # Gel, wax, haarlak
    HAIR_COLOR = "Hair Color"

    # ==========================================
    # PERSONAL CARE - FACE & ORAL
    # ==========================================
    FACE_CARE = "Face Care"                          # Gezichtsverzorging, crème
    TOOTHPASTE = "Toothpaste"
    TOOTHBRUSH = "Toothbrush"
    MOUTHWASH = "Mouthwash"
    SHAVING = "Shaving"                              # Scheermesjes, scheerschuim

    # ==========================================
    # PERSONAL CARE - HEALTH
    # ==========================================
    FEMININE_HYGIENE = "Feminine Hygiene"            # Maandverband, tampons
    CONTRACEPTION = "Contraception"
    FIRST_AID = "First Aid"                          # Pleisters, verband
    VITAMINS_SUPPLEMENTS = "Vitamins & Supplements"
    PAIN_RELIEF = "Pain Relief"

    # ==========================================
    # PET SUPPLIES
    # ==========================================
    PET_FOOD_DOG = "Pet Food (Dog)"
    PET_FOOD_CAT = "Pet Food (Cat)"
    PET_TREATS = "Pet Treats"
    PET_LITTER = "Pet Litter"                        # Kattenbak vulling
    PET_CARE = "Pet Care"

    # ==========================================
    # OTHER
    # ==========================================
    TOBACCO = "Tobacco"
    BATTERIES = "Batteries"
    LIGHTBULBS = "Lightbulbs"
    KITCHEN_ACCESSORIES = "Kitchen Accessories"
    PARTY_SUPPLIES = "Party Supplies"
    FLOWERS_PLANTS = "Flowers & Plants"
    OTHER = "Other"


class ReceiptStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReceiptSource(str, Enum):
    RECEIPT_UPLOAD = "receipt_upload"
    BANK_IMPORT = "bank_import"


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"
