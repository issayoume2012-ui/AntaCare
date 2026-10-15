# ANTACARE — prototype local

## 1. Prérequis
- Python 3.10 ou plus récent
- Connexion Internet uniquement pour installer les bibliothèques et afficher la police distante facultative
- Windows : PowerShell ou Invite de commandes

## 2. Installation sous Windows
Ouvrez PowerShell dans le dossier qui contient `app.py`, puis exécutez :

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

Si l’activation est bloquée par Windows, utilisez directement :

```powershell
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

L’application s’ouvre généralement sur `http://localhost:8501`.

## 3. Connexion de démonstration
- Identifiant : `anta`
- Mot de passe initial : `AntaDemo2026!`

Changez ce mot de passe dans l’onglet **Paramètres** dès la première connexion.

## 4. Où sont les données ?
La base est créée automatiquement dans `antacare.db`, à côté de `app.py`.
Les PDF, fichiers Excel et sauvegardes se trouvent dans le dossier `exports/`.

Ne partagez pas `antacare.db` : il contient les enregistrements saisis. Faites régulièrement une sauvegarde dans un emplacement protégé.

## 5. Limites importantes
Ceci est un prototype destiné aux tests locaux. Il n’est pas prêt pour héberger des dossiers médicaux réels. Avant un usage professionnel, faire vérifier la sécurité du poste, les accès, le chiffrement, les sauvegardes, la gestion des suppressions et les obligations applicables au Sénégal. Les contenus d’éducation sanitaire doivent être validés par une professionnelle compétente. Les calculs de dates sont indicatifs et ne remplacent pas une évaluation clinique.

## 6. Design et centre de rapports (version V3)
- Navigation supérieure modernisée, effets discrets et transitions qui respectent le réglage « réduire les animations » du système.
- Centre de rapports organisé par sous-unités : synthèse, dossiers patientes, grossesses, consultations, rendez-vous, post-partum/nouveau-né, planification familiale, formations/séminaires et éducation sanitaire.
- Chaque sous-unité propose ses propres exports téléchargeables en PDF, Excel et CSV. Les PDF comprennent un tableau paginé, un en-tête et un pied de page.
- Les rapports de consultations et rendez-vous sont filtrés sur le mois choisi ; les registres complets restent disponibles pour les unités qui s’y prêtent.

## 7. Réinitialiser les données de test
Arrêtez l’application, puis supprimez `antacare.db`. Cette opération efface tous les enregistrements de test. Conservez une copie si vous souhaitez les garder.
