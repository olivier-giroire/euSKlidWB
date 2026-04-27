# Releases

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
