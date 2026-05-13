# Releases

## v1.3.1

- Contraintes utilisateur preservees lors de l'export Path vers Sketcher.
- Ajout des surcharges Preserve Tangent, Colinearity, Angle, Length et Distance comme intentions protegees.
- Preserve Distance conserve la semantique point/segment et distance normale entre segments paralleles.
- Preserve Angle conserve le cote signe de l'angle selectionne.
- Rejet automatique d'une contrainte si le solveur deplace la geometrie exportee.

## v1.2.0

- Dialogs non modaux + live preview
- Suppression des valeurs exemples
- Couleurs preview synchronisées config
- Réentrance configurable (Feeling)
- ESC = sortie outil
- Changement d’outil = arrêt automatique précédent
- Code mort supprimé
- Commandes inutiles supprimées

## v1.1.9

Major stabilization release.

- Full migration of previews and path rendering to Coin3D
- Reliable interaction model (no more selection conflicts)
- Stable redraw and rendering synchronization
- Persistent path preview behavior
- Lint cleanup and math utilities consolidation

## v1.1.6

Stabilisation des visuels temporaires avant migration technique vers Pivy/Coin3D.

- Correction du nettoyage des previews et highlights.
- Suppression des accumulations d'objets visuels parasites.
- Conservation des points interactifs.
- Base stabilisée avant reprise de l'architecture globale des overlays.

## v1.1.5

Version diffusable intégrant le workflow Contour → Sketcher stabilisé.

- Passage en politique XY-only.
- Suppression fonctionnelle du repère U/V.
- Réouverture d'un contour existant sans déclencher automatiquement l'export.
- Export possible vers un sketch actif existant.
- Tagging des exports euSKlid pour permettre la mise à jour sans toucher aux éléments utilisateur.
- Persistance du dernier contour fermé.

## v1.0.4

Version historique de référence avant reprise de l'architecture et du workflow d'export.
