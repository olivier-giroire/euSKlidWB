# euSKlidWB

**euSKlid** est un Workbench FreeCAD dédié à la construction géométrique plane,
inspiré de la géométrie classique (règle & compas), avec un workflow explicite :

> **Construction → Contour → Export**

Le nom "euSKlid" veut rappeler que l'auteur n'a pour ainsi dire rien créé, c'est
juste un vieux qui a connu des logiciels de CAO dans les années 90, qui ne voyaient
poindre la conception paramétrique qu'à un horizon incertain. Il s'est donc très
largement inspiré de ses souvenirs nostalgiques d'un temps (que les moins toutça
toutça ...) durant lequel, la modélisation 3D était pratiquée par des dessinateurs
(Ouais, criterium, calque, règle, compas ...). Et oui, ces vieux avaient une approche
topologique et descriptive de la représentation, et c'était très instinctif.
Donc en gros, voila : le sketcher paramétrique, c'est top, mais s'il peut être aidé
par l'instinct, c'est mieux.
Et pour l'auteur (ce vieux con qui écrit des trucs que personne ne lira jamais), le
meilleur du mieux était représenté par le sketcher de l'un des mastodontes de la
modélisation de l'époques, "mistérieusement" disparu à l'occasion du rachat de son
éditeur (français), par son concurrent direct (français) en 1999 ... voila pour le nom.

Et sinon, accessoirement, c'est sa premire expérience de "vibe coding", parce qu'un
dessinateur devenu DSI, il ne faut pas trop s'attendre à ce qu'il sache coder.

---

## ✨ Objectif

Offrir une alternative rapide et visuelle au Sketcher FreeCAD pour :
- construire des géométries propres
- définir des contours précis
- exporter vers le sketcher de FreeCAD, pour retrouver le workflow de conception

---

## 🧠 Philosophie

- ✔ Géométrie explicite
- ✔ Feedback visuel constant
- ✔ Aucune magie cachée
- ✔ Workflow linéaire et lisible

---

## 🚀 Fonctionnalités

### 🔹 Construction
- Lignes :
  - 2 points
  - parallèles (//U, //V, //Ref) 
  - séries et grilles
- Cercles :
  - centre / rayon
  - tangences (ligne, cercle)
  - 3 points
- Snapping avancé précalculé:
  - points
  - intersections
  - tangences

---

### 🔹 Contour (Path)
- Sélection guidée des entités
- Fermeture contrôlée
- Visualisation en temps réel

---

### 🔹 Export
- Export vers Sketcher FreeCAD
- Gestion de plusieurs contours
- Recherche de contraintes à exporter

---

## ⚙️ Configuration

### UI
- Couleurs, transparence, épaisseur des différents types de constructions
- Couleurs, transparence, taille des différents "Points"


### Work
- Construction
- Contour
- Highlight

### Feeling
- Snap threshold (pixels)
- Autogrid
- Messages console / aide

---

## 📦 Installation

Tout dans : ~/.local/share/FreeCAD/Mod/v{x-y}/euSKlidWB.
Et non, désolé, pour windows, je ne sais pas, mais ça doit être dans la doc.
