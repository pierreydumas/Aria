# Session d'entraînement technique - Entretien MDM État

**Date:** 2026-03-09  
**Objectif:** Préparation entretien Architecte Data (MDM, Neo4j, Gouvernance)

## Points techniques validés

### Architecture MDM
- Hub-and-spoke avec Neo4j comme moteur de réconciliation
- Pattern: datasource → merge staging → GOLDEN RECORD
- 300 sources dans un petit DC (pragmatique, pas de bullshit)
- Publication vers DW silos avec modèles en étoile/snowflake

### Gestion des conflits data quality
- Ownership strict par domaine (IT = serial number, Finance = PO)
- Dashboard opérationnel pour erreurs critiques (< 3 jours SLA)
- Monitoring du "clignotement" (valeur qui change de source quotidiennement)
- Delta processing, pas de full rebuild débile

### RGPD / Archivage
- Anonymisation algorithmique pour données externes
- Archivage automatique par exercice fiscal
- Rebuild quotidien des chaînes data = nettoyage naturel RGPD
- Possibilité de script complet de suppression avec preuve

### Orchestration
- DAG engine maison (contraintes sécurité, Airflow bloqué)
- Gestion des sources défaillantes: non-critique = valeur veille, critique = escalade
- SQLAlchemy + pandas pour transformations simples
- Spark/Kafka uniquement si volume vraiment nécessaire

## Métaphore clé pour l'entretien
> "Je suis le supermarché, les équipes métiers sont les fabricants de Nutella. Je mets les cadres, ils sont responsables de leur données internes."

## Conseils pour jeudi
- Parler moins vite
- Mentionner LBA, RGPD (contraintes légales fortes)
- Montrer capacité d'adaptation à la lenteur bureaucratique
- Positionnement: modernité technique + prudence opérationnelle

## Réponse clé: modernité vs legacy
"Je viens d'un environnement où on itère vite, mais je sais aussi qu'on ne migre pas un référentiel critique comme on change de librairie NPM. Mon approche: cohabiter, APIs modernes par-dessus legacy stable, pas de big bang."

---
*Session avec Aria Blue - Silicon Familiar*