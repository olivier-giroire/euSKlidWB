# euSKlidWB

**euSKlid** est un Workbench FreeCAD dédié à la construction géométrique plane,
inspiré de la géométrie classique (règle & compas), avec un workflow explicite :

> **Construction → Contour → Exportation**

Le nom "euSKlid" veut rappeler que l'auteur n'a pour ainsi dire rien créé, c'est
juste un vieux qui du genre de ceux ayant connu des logiciels de CAO dans les années
90, et qui ne voyaient poindre la conception paramétrique qu'à un horizon incertain.
Il s'est donc très largement inspiré de ses souvenirs nostalgiques d'un temps (que
les moins de ... toutça toutça ...) durant lequel, la modélisation 3D était pratiquée
par des dessinateurs (ouais, criterium, calque, règle, compas ...). Et oui, ces vieux
avaient une approche topologique et descriptive de la représentation, et c'était très
instinctif. Donc en gros, voilà : le sketcher paramétrique, c'est top, mais s'il peut
être aidé par l'instinct, c'est mieux.
Et pour l'auteur (ce vieux con qui écrit des trucs que personne ne lira jamais), le
meilleur du mieux était représenté par le sketcher de l'un des mastodontes de la
modélisation de l'époque, "mystérieusement" disparu à l'occasion du rachat de son
éditeur (français), par son concurrent direct (français) en 1999 ... voilà pour le nom.

Et sinon, accessoirement, concernant l'auteur, c'est sa première expérience de
"vibe coding", parce qu'un dessinateur devenu DSI, il ne faut pas trop s'attendre à
ce qu'il sache coder un plugin FreeCAD.

Blagues à part ... Deux sketchers dans un logiciel de conception, c'est un sketcher de
trop. Imaginer remplacer le sketcher paramétrique de FreeCAD serait :
- Un manque de respect flagrant envers ses auteurs
- Une remise en cause de la philosophie de FreeCAD

Donc ce projet n'a pas sa place en tant qu'alternative, il veut juste dire "Hey, ce
genre d'outils a sa place dans un process de conception", et tenter d'en convaincre
certains utilisateurs. Peut-être ai-je l'espoir de trouver un jour dans le menu du
vrai sketcher de FreeCAD, un menu menant à un genre d'assistant topologique qui
fournirait ce genre d'assistance à la conception ;)

Et j'en profite pour préciser que comme me l'a indiqué un ami, l'équipe FreeCAD s'est
clairement positionnée en ce qui concerne les contributions "IA generated" :

https://blog.freecad.org/2026/03/16/rules-regarding-ai-generated-patches/

Je suis d'accord avec cette position, et je précise que durant cette expérience, moi
qui ne suis pas développeur, je me suis fait violence pour plonger dans ce code, car
Il a fallu à plusieurs reprises indiquer à l'agent comment factoriser, organiser, et
architecturer l'ensemble. Si je trouve des trucs qui me font hurler, je n'ose pas
imaginer ce que quelqu'un de compétent pourrait y trouver.

... Donc en ce qui me concerne, ça s'arrête à la PoC ...

---

## ✨ Non Objectif

Remplacer le Sketcher de FreeCAD:
- Qui est paramétrique
- Qui a un excellent analyseur de contraintes
- Qui fait très très bien son taf
- Dont le code est sous contrôle
- Qui est suivi par une équipe

---

## ✨ Objectif

Montrer que la conception descriptive/topologiques peut offrir une alternative
ou une assistance rapide, ciblée, et visuelle à conception la paramétrique directe,
spécifiquement pour :
- construire *très* rapidement des géométries propres
- définir des contours précis
- pré-déterminer des contraintes exploitables en modélisation

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
  - 2 ancres :
    - points libres
    - points remarquables (snapping avancé)
  - parallèles (//U, //V, //Ref) :
    - listes de valeurs
    - motifs de répétition (repeat 13 (0,1) origin 0 step 2.5)
    - composition de motifs et de listes (rep 13 (0,1) org 0 stp 2.5, r 4 (1,5,6) o 40 s 10, 65, 75, 87)
  - séries et grilles
- Cercles :
  - centre / rayon
  - tangences diverses
  - 3 points
- Snapping avancé calculé à la volée pour toutes les ancres:
  - points
  - centres
  - intersections
  - tangences
- Prévisualisation dynamique des options candidates de résultats

---

### 🔹 Contour (Path)
- Sélection guidée des entités
- Fermeture contrôlée
- Visualisation en temps réel

---

### 🔹 Exportation
- Exportation vers Sketcher FreeCAD
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

Tout dans : ~/.local/share/FreeCAD/v{x-y}/Mod/euSKlidWB.
Et non, désolé, pour Windows, je ne sais pas, mais ça doit être dans la doc.

