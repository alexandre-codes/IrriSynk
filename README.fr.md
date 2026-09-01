🇬🇧 [English](README.md) | 🇫🇷 **Français**

---

# IrriSynk

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![version](https://img.shields.io/badge/version-0.1.0-blue)
![HA min version](https://img.shields.io/badge/HA-2024.3%2B-blue)
![license](https://img.shields.io/badge/licence-GPL--3.0-green)

**IrriSynk** est une intégration Home Assistant pour la **gestion intelligente de l'arrosage par électrovannes**.

Elle calcule chaque jour, pour chaque zone, la quantité d'eau exacte à apporter selon la méthode scientifique **FAO-56** (Penman-Monteith simplifiée), puis **pilote automatiquement les électrovannes** à l'heure programmée — pour la durée précise calculée ou définie.

Pluie du jour, bilan de la veille, stade de végétation, type de sol, mode de culture : tout est pris en compte. Si la pluie suffit, l'arrosage est annulé. Le surplus ou le déficit s'accumule dans un bilan hydrique cumulatif borné par la réserve facilement utilisable du sol.

> Trois modes par zone — **Manuel**, **Programmé** ou **Auto** —, un mode **cascade** pour enchaîner les zones séquentiellement, et un dashboard Lovelace généré automatiquement pour tout piloter sans toucher au code YAML.

---

## Fonctionnalités principales

- [Calcul des besoins en eau (FAO-56)](#calcul-des-besoins-en-eau)
- [Modèle hydrique du sol (RAW/TAW)](#modèle-hydrique-du-sol)
- [Pilotage des électrovannes](#pilotage-des-électrovannes)
- [Trois modes de fonctionnement par zone](#trois-modes-de-fonctionnement-par-zone)
- [Arrosage en cascade](#arrosage-en-cascade)
- [Programmation horaire](#programmation-horaire)
- [Bilan hydrique journalier](#bilan-hydrique-journalier)
- [Cultures et stades phénologiques](#cultures-et-stades-phénologiques)
- [Modes de culture](#modes-de-culture)
- [Dashboard Lovelace automatique](#dashboard-lovelace-automatique)
- [Autres fonctionnalités](#autres-fonctionnalités)

---

### Calcul des besoins en eau
- Calcul automatique du besoin en eau par zone selon la formule FAO-56 :  
  `ET₀ × Kc − Pluie efficace − Arrosage du jour − Bilan hydrique − Tampon sol`
- Calcul de l'ET₀ depuis une entité météo HA ou des capteurs locaux (température, vent, pression, nébulosité)
- Bilan hydrique de la veille recalculé à minuit depuis l'historique des capteurs et des électrovannes
- Support des prévisions de pluie depuis la météo ou un capteur dédié
- Catalogue de 32 cultures intégré avec coefficients Kc et profondeurs racinaires FAO-56

### Modèle hydrique du sol
- **Type de sol** configurable par zone (7 classes FAO-56 : Sable, Sable limoneux, Limon sableux, Limon, Limon fin, Limon argileux, Argile)
- Calcul de la **Réserve facilement utilisable (RAW)** : `RAW = 0,4 × AWC × profondeur_effective`
- Profondeur racinaire **progressive** au fil des stades : pondération par durées cumulées de 15 cm (plantation) à la profondeur FAO-56 de la culture
- Bornes du bilan hydrique **dynamiques** `[−RAW ; +RAW]` — s'adaptent à la culture et au stade courant
- Capteur **Capacité sol (RAW)** affichant la réserve courante en mm
- Bouton de **remise à zéro** du bilan hydrique

### Pilotage des électrovannes
- Chaque zone est associée à une entité **switch** ou **valve** Home Assistant
- L'ouverture et la fermeture sont déclenchées automatiquement selon le mode et l'heure programmée
- Récupération automatique au redémarrage : les arrosages en cours sont re-armés, les arrosages en retard sont stoppés

### Trois modes de fonctionnement par zone

| Mode | Description |
|---|---|
| **Manuel** | Aucun arrosage automatique — la zone est gérée manuellement |
| **Programmé** | L'électrovanne s'ouvre à l'heure définie pour une durée fixe |
| **Auto** | L'électrovanne s'ouvre à l'heure définie pour la durée calculée FAO-56 (nulle si pluie suffisante) |

### Arrosage en cascade
- Un mode **cascade** permet d'arroser toutes les zones éligibles séquentiellement depuis une heure globale
- Les zones démarrent les unes après les autres avec 1 minute de battement
- Si une zone se termine en avance, les horaires des zones suivantes sont recalculés dynamiquement
- Compatible avec les modes Auto et Programmé par zone

### Programmation horaire
- Heure de démarrage configurable **par zone** (mode Auto ou Programmé)
- Heure de démarrage de la **cascade** globale
- Le planificateur tourne toutes les minutes et gère arrêts et démarrages précis

### Bilan hydrique journalier
- Chaque nuit à minuit, le bilan réel de la veille est recalculé :
  - ET₀ J-1 depuis l'historique des capteurs ou la valeur prévisionnelle
  - Pluie J-1 depuis l'historique du pluviomètre ou la météo
  - Arrosage J-1 depuis l'historique du switch/valve de chaque zone
- Le bilan est borné à `[−RAW ; +RAW]` pour éviter les accumulations irréalistes
- Un surplus cumulé réduit le besoin du jour ; un déficit l'augmente

### Cultures et stades phénologiques
- Catalogue intégré de **32 cultures** avec Kc FAO-56 par stade et profondeur racinaire (FAO-56, Tableau 22)
- Sélection manuelle du stade ou calcul automatique par date de plantation
- Création de cultures personnalisées avec leurs propres stades, coefficients Kc et profondeur racinaire
- Édition et suppression des stades personnalisés depuis le dashboard

### Modes de culture
- Plein champ, serre (hiver/printemps/été/automne), paillage (léger/moyen/épais), toile/film
- Facteur de correction ET₀ par mode
- Création de modes de culture personnalisés avec facteur ET₀ libre

### Dashboard Lovelace automatique
Le dashboard est généré automatiquement et mis à jour en temps réel. Il comprend **8 onglets** :

| Onglet | Contenu |
|---|---|
| **Accueil** | Vue synthétique des zones : besoins, durée recommandée, état, météo |
| **Programmation** | Mode de chaque zone, heure de démarrage, durée, cascade, bilan hydrique |
| **Paramètres** | Configuration par zone : électrovanne, débit, type de sol, culture, stade |
| **Modes de culture** | Création et suppression de modes personnalisés |
| **Cultures** | Catalogue des cultures, création/édition/suppression de cultures et stades |
| **Calculateur** | Calculateur de débit goutte-à-goutte (mm/m²/h) |
| **Statistiques** | Bilans hydriques, historiques d'arrosage par zone |
| **Wiki** | Documentation intégrée : formule, algorithme, référence FAO-56 |

### Autres fonctionnalités
- Support multi-zones (extensible via service `add_zones`)
- Interface en **français** et en **anglais** (selon la langue de Home Assistant)
- Services Home Assistant dédiés : recalcul, rechargement du catalogue, ajout de zones
- Persistance complète des états et réglages au redémarrage

---

## Installation via HACS

1. Ouvrir **HACS** dans Home Assistant
2. Aller dans **Intégrations** → menu ⋮ → **Dépôts personnalisés**
3. Ajouter l'URL : `https://github.com/alexandre-codes/irrisynk`  
   Catégorie : **Intégration**
4. Rechercher **IrriSynk** et installer
5. Redémarrer Home Assistant
6. Aller dans **Paramètres → Intégrations → Ajouter** → rechercher **IrriSynk**

---

## Installation manuelle

Copier le dossier `custom_components/irrisynk/` dans le dossier `custom_components/` de votre configuration Home Assistant, puis redémarrer.

---

## Configuration

### Paramètres initiaux (Config Flow)

Lors de l'ajout de l'intégration, saisir :
- L'**entité météo** Home Assistant à utiliser pour les calculs ET₀ et pluie prévisionnelle
- Le **nom** de votre installation
- La **latitude** (pré-remplie depuis HA)

### Capteurs locaux optionnels (amélioration de la précision)

| Capteur | Description |
|---|---|
| Température max/min | Calcul ET₀ J-1 depuis mesures réelles |
| Vitesse du vent | Calcul ET₀ J-1 depuis mesures réelles |
| Pression atmosphérique | Calcul ET₀ J-1 depuis mesures réelles |
| Nébulosité | Calcul ET₀ J-1 depuis mesures réelles |
| Pluviomètre | Pluie réelle J-1 (mode cumulatif ou incrémental) |
| Prévision pluie | Remplace la pluie prévisionnelle pour le calcul du jour J |

Si aucun capteur local n'est configuré, l'ET₀ et la pluie sont issus de la prévision météo.

### Configuration des zones

Depuis le dashboard, pour chaque zone :
- Associer une **entité switch ou valve** (électrovanne)
- Renseigner le **débit** en mm/h (calculateur intégré)
- Choisir le **type de sol** (7 classes FAO-56)
- Définir le **tampon sol** (mm avant déclenchement)
- Choisir la **culture**, le **stade** (ou la date de plantation pour le mode auto)
- Sélectionner le **mode de culture**
- Définir le **mode de fonctionnement** et l'**heure de démarrage**

---

## Formule de calcul

```
Besoin (mm) = max(0 ; ET₀ × Kc − Pluie efficace − Arrosage du jour − Bilan hydrique − Tampon sol)
Durée (min) = min(Besoin / Débit × 60 ; Durée max)
```

| Terme | Description |
|---|---|
| **ET₀** | Évapotranspiration de référence (Penman-Monteith FAO-56) |
| **Kc** | Coefficient cultural selon la culture et le stade phénologique |
| **Pluie efficace** | Précipitations × taux d'efficacité (défaut 80 %) |
| **Arrosage du jour** | Mm déjà apportés aujourd'hui par l'électrovanne |
| **Bilan hydrique** | Excédent ou déficit cumulatif — borné à `[−RAW ; +RAW]` |
| **RAW** | Réserve facilement utilisable : `0,4 × AWC × profondeur_racinaire_effective` |
| **Tampon sol** | Réserve minimale avant déclenchement |

---

## Services

| Service | Description |
|---|---|
| `irrisynk.recalculate_zone` | Recalcule les recommandations pour une zone |
| `irrisynk.recalculate_all` | Recalcule toutes les zones |
| `irrisynk.reload_kc_catalog` | Recharge le catalogue des cultures depuis le fichier JSON |
| `irrisynk.add_zones` | Ajoute une ou plusieurs zones (nommées zone_N+1, zone_N+2…) |

---

## Prérequis

- Home Assistant **2024.3+**
- Une entité météo configurée dans Home Assistant
- Des entités switch ou valve représentant les électrovannes

---

## Licence

GPL-3.0-or-later — voir [LICENSE](LICENSE)
