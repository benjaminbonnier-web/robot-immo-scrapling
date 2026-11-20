import datetime
import re
import os
from scrapling.spiders import Spider, Request, Response
from scrapling.fetchers import AsyncStealthySession

class BienIciSpider(Spider):
    name = "bienici"
    concurrent_requests = 2 

    def __init__(self):
        super().__init__()
        self.mode = os.getenv("SCRAPING_MODE", "prod")
        self.max_pages = 1 if self.mode == "dev" else 999
        self.categories = {
            "maisonvilla": "Maison",
            "appartement": "Appartement",
            "terrain": "Terrain",
            "parking": "Parking",
            "commerce": "Commerce"
        }

    def configure_sessions(self, manager):
        # Utilisation du navigateur furtif intégré à Scrapling
        manager.add("stealth", AsyncStealthySession(headless=True), lazy=True)

    def start_requests(self):
        for code_url, nom_categorie in self.categories.items():
            url = f"https://www.bienici.com/recherche/achat/salon-de-provence-13300,lancon-provence-13680/{code_url}?page=1"
            # CORRECTION : On utilise self.parse au lieu de self.parse_liste
            yield Request(url, sid="stealth", callback=self.parse, cb_kwargs={"nom_cat": nom_categorie, "code_url": code_url, "page_num": 1})

    # CORRECTION : Cette méthode DOIT s'appeler "parse"
    async def parse(self, response: Response, nom_cat: str, code_url: str, page_num: int):
        self.logger.info(f"=== {nom_cat.upper()} (Page {page_num}) ===")
        
        annonces = response.css('article')
        if not annonces:
            self.logger.info(f"Fin {nom_cat} : 0 annonce trouvée.")
            return
        
        # --- SÉCURITÉ ANTI-BOUCLE INFALLIBLE ---
        premier_lien_brut = annonces[0].css('a::attr(href)').get()
        if premier_lien_brut:
            premier_lien_propre = premier_lien_brut.split('?')[0]
            cle_memoire = f"premier_lien_{code_url}"
            
            if getattr(self, cle_memoire, None) == premier_lien_propre and page_num > 1:
                self.logger.info(f"Boucle détectée pour {nom_cat}. Fin de la catégorie.")
                return
            setattr(self, cle_memoire, premier_lien_propre)

        # --- EXTRACTION ---
        for annonce in annonces:
            lien_relatif = annonce.css('a::attr(href)').get()
            if not lien_relatif: 
                continue
            lien_absolu = f"https://www.bienici.com{lien_relatif}" if lien_relatif.startswith('/') else lien_relatif

            texte_carte = " ".join(annonce.css('*::text').getall())
            
            m_prix = re.search(r'([\d\s]+)€', texte_carte)
            prix = m_prix.group(1).strip() if m_prix else "N/A"
            
            m_surf = re.search(r'(\d+[.,]?\d*)\s*m[2²]', texte_carte, re.IGNORECASE)
            surface = m_surf.group(1).strip() if m_surf else "N/A"
            
            m_pieces = re.search(r'(\d+)\s*pièce[s]?', texte_carte, re.IGNORECASE)
            pieces = m_pieces.group(1).strip() if m_pieces else "N/A"

            yield Request(
                lien_absolu, 
                sid="stealth", 
                callback=self.parse_detail, 
                cb_kwargs={
                    "base": {
                        "Catégorie": nom_cat, "Prix": prix, 
                        "Surface": surface, "Pièces": pieces, "Lien": lien_absolu
                    }
                }
            )
        
        # --- PAGE SUIVANTE ---
        if page_num < self.max_pages:
            next_url = f"https://www.bienici.com/recherche/achat/salon-de-provence-13300,lancon-provence-13680/{code_url}?page={page_num+1}"
            # CORRECTION : On utilise self.parse ici aussi
            yield Request(next_url, sid="stealth", callback=self.parse, cb_kwargs={"nom_cat": nom_cat, "code_url": code_url, "page_num": page_num+1})

    async def parse_detail(self, response: Response, base: dict):
        texte_detail = " ".join(response.css('body *::text').getall())
        
        terrain, chambres, bain, dpe = "N/A", "N/A", "N/A", "N/A"
        m_terrain = re.search(r'(\d+[.,]?\d*)\s*m[2²]\s*de\s*terrain', texte_detail, re.IGNORECASE)
        if m_terrain: terrain = m_terrain.group(1).strip()
        
        m_chambres = re.search(r'(\d+)\s*chambre[s]?', texte_detail, re.IGNORECASE)
        if m_chambres: chambres = m_chambres.group(1).strip()
        
        m_bain = re.search(r'(\d+)\s*salle[s]?\s*d', texte_detail, re.IGNORECASE)
        if m_bain: bain = m_bain.group(1).strip()
        
        m_dpe = re.search(r'(?:Performance énergétique|Classe|DPE|Émissions).*?\b([A-G])\b', texte_detail, re.IGNORECASE)
        if m_dpe: dpe = m_dpe.group(1).upper()

        date_jour = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        yield {
            "Date": date_jour,
            "Catégorie": base["Catégorie"],
            "Prix (€)": base["Prix"],
            "Surface (m²)": base["Surface"],
            "Terrain (m²)": terrain,
            "Pièces": base["Pièces"],
            "Chambres": chambres,
            "SDB": bain,
            "DPE": dpe,
            "Lien": base["Lien"]
        }


if __name__ == "__main__":
    spider = BienIciSpider()
    print(f"*** Lancement Scrapling en mode {spider.mode.upper()} ***")
    
    result = spider.start()
    
    # Export CSV géré nativement par Scrapling
    result.items.to_csv("resultats.csv")
    print(f"Scraping terminé. {len(result.items)} biens enregistrés dans resultats.csv.")
    
    # Reconstruction du HTML à partir des données en mémoire
    cartes_html = ""
    for item in result.items:
        nom_categorie = item.get("Catégorie", "Inconnu")
        prix = item.get("Prix (€)", "N/A")
        surface = item.get("Surface (m²)", "N/A")
        pieces = item.get("Pièces", "N/A")
        lien_absolu = item.get("Lien", "#")
        
        val_prix = re.sub(r'[^\d]', '', str(prix)) if prix != "N/A" else "0"
        val_surf = re.sub(r'[^\d]', '', str(surface).split(',')[0]) if surface != "N/A" else "0"
        val_pieces = re.sub(r'[^\d]', '', str(pieces)) if pieces != "N/A" else "0"
        
        badge_prix = f"{prix} €" if prix != "N/A" else "Prix N/A"
        badge_surf = f"{surface} m²" if surface != "N/A" else "Surf N/A"
        badge_pieces = f"{pieces} p." if pieces != "N/A" else "Pièces N/A"
        
        cartes_html += f"""
            <div class="card" data-categorie="{nom_categorie}" data-prix="{val_prix}" data-surface="{val_surf}" data-pieces="{val_pieces}">
                <div class="badges">
                    <span class="badge badge-prix">{badge_prix}</span>
                    <span class="badge">{badge_surf}</span>
                    <span class="badge">{badge_pieces}</span>
                </div>
                <a href="{lien_absolu}" target="_blank" class="btn">Voir l'annonce</a>
            </div>
        """

    css = """
        body { font-family: 'Segoe UI', sans-serif; background-color: #f4f7f6; color: #333; padding: 20px; }
        h1 { text-align: center; color: #2c3e50; }
        .category-bar { display: flex; justify-content: center; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
        .cat-btn { padding: 10px 20px; border: none; border-radius: 30px; background-color: #e0e0e0; cursor: pointer; font-weight: bold; transition: 0.3s; }
        .cat-btn.active { background-color: #3498db; color: white; }
        .cat-btn:hover:not(.active) { background-color: #bdc3c7; }
        .filters-panel { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); margin-bottom: 30px; display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; align-items: flex-end; max-width: 1000px; margin-left: auto; margin-right: auto; }
        .filter-group { display: flex; flex-direction: column; gap: 5px; }
        .filter-group label { font-size: 0.85em; font-weight: bold; color: #555; }
        .filter-group input { padding: 8px; border: 1px solid #ccc; border-radius: 5px; width: 110px; font-size: 14px; }
        .container { display: flex; flex-wrap: wrap; gap: 20px; justify-content: center; }
        .card { background: white; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); padding: 20px; width: 250px; border-top: 5px solid #3498db; display: flex; flex-direction: column; }
        .badges { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 15px; }
        .badge { background-color: #eee; padding: 5px 8px; border-radius: 4px; font-size: 0.85em; font-weight: bold; color: #333; }
        .badge-prix { background-color: #27ae60; color: white; }
        .btn { display: block; background-color: #3498db; color: white; padding: 10px 15px; text-align: center; text-decoration: none; border-radius: 5px; font-weight: bold; margin-top: auto; }
    """

    javascript = """
    <script>
        let activeCategory = 'Tous';
        document.querySelectorAll('.cat-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                activeCategory = this.getAttribute('data-cat');
                filterCards();
            });
        });
        const inputs = document.querySelectorAll('.filters-panel input');
        inputs.forEach(input => input.addEventListener('input', filterCards));
        function filterCards() {
            let minPrix = parseInt(document.getElementById('filter-prix-min').value) || 0;
            let maxPrix = parseInt(document.getElementById('filter-prix-max').value) || Infinity;
            let minSurf = parseInt(document.getElementById('filter-surf-min').value) || 0;
            let maxSurf = parseInt(document.getElementById('filter-surf-max').value) || Infinity;
            let cards = document.querySelectorAll('.card');
            cards.forEach(card => {
                let p = parseInt(card.getAttribute('data-prix')) || 0;
                let s = parseInt(card.getAttribute('data-surface')) || 0;
                let cat = card.getAttribute('data-categorie');
                let matchCat = (activeCategory === 'Tous' || cat === activeCategory);
                let matchPrix = (p >= minPrix && p <= maxPrix) || p === 0;
                let matchSurf = (s >= minSurf && s <= maxSurf) || s === 0;
                if(matchCat && matchPrix && matchSurf) {
                    card.style.display = 'flex';
                } else {
                    card.style.display = 'none';
                }
            });
        }
    </script>
    """

    date_jour = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html_content = f"""<!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <title>Dashboard Immobilier</title>
        <style>{css}</style>
    </head>
    <body>
        <h1>Marché Immobilier (MODE {spider.mode.upper()})</h1>
        <p style="text-align: center;">Mise à jour : {date_jour}</p>
        
        <div class="category-bar">
            <button class="cat-btn active" data-cat="Tous">Tous</button>
            <button class="cat-btn" data-cat="Maison">Maisons</button>
            <button class="cat-btn" data-cat="Appartement">Appartements</button>
            <button class="cat-btn" data-cat="Terrain">Terrains</button>
            <button class="cat-btn" data-cat="Parking">Parkings</button>
            <button class="cat-btn" data-cat="Commerce">Commerces</button>
        </div>
        
        <div class="filters-panel">
            <div class="filter-group"><label>Prix Min (€)</label><input type="number" id="filter-prix-min" placeholder="Min"></div>
            <div class="filter-group"><label>Prix Max (€)</label><input type="number" id="filter-prix-max" placeholder="Max"></div>
            <div class="filter-group"><label>Surface Min (m²)</label><input type="number" id="filter-surf-min" placeholder="Min"></div>
            <div class="filter-group"><label>Surface Max (m²)</label><input type="number" id="filter-surf-max" placeholder="Max"></div>
        </div>
        
        <div class="container" id="cards-container">
            {cartes_html}
        </div>
        {javascript}
    </body>
    </html>
    """
    
    with open("resultats.html", "w", encoding="utf-8") as fichier_html:
        fichier_html.write(html_content)
