import streamlit as st
import pandas as pd
import pdfplumber
import re

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Riconciliazione Universale", layout="wide")
st.title("🧩 Riconciliatore Bancario Universale")

# --- FUNZIONI DI UTILITÀ ---
def parse_italian_currency(value):
    """Pulisce i numeri italiani (es. 1.200,50 -> 1200.50)"""
    if pd.isna(value) or str(value).strip() == '':
        return 0.0
    # Rimuove tutto tranne numeri, virgole, punti e meno
    clean_val = str(value).replace(' ', '')
    # Gestione del segno meno che a volte è alla fine (es: "100-")
    if clean_val.endswith('-'):
        clean_val = '-' + clean_val[:-1]
    
    # Rimuove punti migliaia e cambia virgola in punto
    clean_val = clean_val.replace('.', '').replace(',', '.')
    
    # Rimuove caratteri non numerici rimasti (es. €)
    clean_val = re.sub(r'[^\d\.\-]', '', clean_val)
    
    try:
        return float(clean_val)
    except ValueError:
        return 0.0

# --- INTERFACCIA ---

col_up1, col_up2 = st.columns(2)
with col_up1:
    file_excel = st.file_uploader("1. Carica il TUO Excel", type=["xlsx", "xls"])
with col_up2:
    file_pdf = st.file_uploader("2. Carica il PDF della Banca", type=["pdf"])

if file_excel and file_pdf:
    st.divider()
    
    # --- FASE 1: LETTURA "GREZZA" DEL PDF ---
    # Leggiamo solo la prima pagina per farti scegliere le colonne
    try:
        pdf_preview_df = pd.DataFrame()
        with pdfplumber.open(file_pdf) as pdf:
            # Cerchiamo la prima tabella utile nella prima pagina
            first_page = pdf.pages[0]
            tables = first_page.extract_tables()
            
            if tables:
                # Creiamo un dataframe grezzo
                pdf_preview_df = pd.DataFrame(tables[0])
                # Puliamo le righe vuote o con troppi pochi dati
                pdf_preview_df = pdf_preview_df.dropna(how='all')
            else:
                st.error("Non riesco a trovare tabelle in questo PDF. È un'immagine scansionata?")
                st.stop()
                
        st.subheader("🛠️ Configurazione PDF (Mappatura)")
        st.info("Guarda l'anteprima qui sotto e dimmi a cosa corrispondono le colonne.")
        
        # Mostriamo le prime 5 righe così capisci
        st.write("Anteprima dati letti dal PDF:")
        st.dataframe(pdf_preview_df.head(5))
        
        # --- MENU DI SELEZIONE COLONNE PDF ---
        # Creiamo una lista di colonne disponibili (0, 1, 2, 3...)
        col_options = pdf_preview_df.columns.tolist()
        
        c_pdf1, c_pdf2, c_pdf3 = st.columns(3)
        
        # Selezione Data e Descrizione
        idx_data = c_pdf1.selectbox("Quale colonna è la DATA?", col_options, index=0)
        idx_desc = c_pdf2.selectbox("Quale colonna è la DESCRIZIONE?", col_options, index=1 if len(col_options)>1 else 0)
        
        # Selezione Tipo Importi
        tipo_importi_pdf = c_pdf3.radio("Come sono gli importi nel PDF?", 
                                        ["Colonna Unica (+/-)", "Due Colonne (Dare/Avere)"])
        
        col_importo_unico = None
        col_dare_pdf = None
        col_avere_pdf = None
        
        if tipo_importi_pdf == "Colonna Unica (+/-)":
            col_importo_unico = st.selectbox("Seleziona la colonna IMPORTO", col_options, index=len(col_options)-1)
        else:
            c_sub1, c_sub2 = st.columns(2)
            # Cerchiamo di indovinare le colonne finali
            idx_def_dare = len(col_options)-2 if len(col_options) >= 2 else 0
            idx_def_avere = len(col_options)-1
            
            col_dare_pdf = c_sub1.selectbox("Colonna ADDEBITI (Uscite)", col_options, index=idx_def_dare)
            col_avere_pdf = c_sub2.selectbox("Colonna ACCREDITI (Entrate)", col_options, index=idx_def_avere)

        # --- FASE 2: ELABORAZIONE COMPLETA PDF ---
        # Ora che sappiamo le colonne, processiamo TUTTE le pagine
        if st.button("🚀 Elabora e Confronta"):
            all_transactions = []
            
            with st.spinner("Sto leggendo tutte le pagine del PDF..."):
                with pdfplumber.open(file_pdf) as pdf:
                    for page in pdf.pages:
                        tables = page.extract_tables()
                        for table in tables:
                            df_page = pd.DataFrame(table)
                            
                            # Iteriamo sulle righe
                            for index, row in df_page.iterrows():
                                try:
                                    # Recuperiamo i dati grezzi usando gli indici scelti dall'utente
                                    raw_data = row.get(idx_data)
                                    raw_desc = row.get(idx_desc)
                                    
                                    # Controllo base: se non c'è una data valida, saltiamo la riga
                                    # (Serve a saltare intestazioni e piè di pagina)
                                    if not raw_data or not re.search(r'\d', str(raw_data)):
                                        continue

                                    imp_finale = 0.0
                                    
                                    if tipo_importi_pdf == "Colonna Unica (+/-)":
                                        raw_val = row.get(col_importo_unico)
                                        imp_finale = parse_italian_currency(raw_val)
                                    else:
                                        val_dare = parse_italian_currency(row.get(col_dare_pdf))
                                        val_avere = parse_italian_currency(row.get(col_avere_pdf))
                                        # Dare è negativo, Avere è positivo
                                        imp_finale = val_avere - val_dare

                                    # Salviamo solo se l'importo non è zero
                                    if imp_finale != 0:
                                        all_transactions.append({
                                            "Data": str(raw_data),
                                            "Descrizione": str(raw_desc).replace('\n', ' '),
                                            "Importo": imp_finale,
                                            "Fonte": "PDF"
                                        })
                                except Exception as e:
                                    continue # Salta righe problematiche

            df_pdf_clean = pd.DataFrame(all_transactions)
            
            # --- FASE 3: LETTURA EXCEL ---
            # (Qui assumiamo una struttura standard o chiediamo mapping anche qui se serve, 
            # ma per ora semplifichiamo assumendo che tu sappia il tuo Excel)
            df_xls = pd.read_excel(file_excel)
            
            # Cerchiamo di normalizzare l'Excel dell'utente
            # Prendiamo le prime 3-4 colonne se non specificato
            cols_xls = df_xls.columns
            # Logica semplice: ultima colonna numeri = importo, prima colonna date = data
            # Per ora chiediamo mappatura veloce anche per Excel per sicurezza
            st.divider()
            st.write("### 🛠️ Configurazione Excel")
            c_ex1, c_ex2, c_ex3 = st.columns(3)
            xls_col_data = c_ex1.selectbox("Excel: Colonna Data", cols_xls)
            xls_col_imp = c_ex2.selectbox("Excel: Colonna Importo (o Entrate)", cols_xls)
            # Opzionale: seconda colonna per uscite se separate
            xls_mode = c_ex3.checkbox("Ho uscite ed entrate separate in Excel?")
            
            df_user_final = pd.DataFrame()
            df_user_final["Data"] = df_xls[xls_col_data].astype(str)
            
            if xls_mode:
                 xls_col_uscite = st.selectbox("Excel: Colonna Uscite", cols_xls)
                 # Entrate - Uscite
                 df_user_final["Importo"] = df_xls[xls_col_imp].fillna(0) - df_xls[xls_col_uscite].fillna(0)
            else:
                 df_user_final["Importo"] = df_xls[xls_col_imp]
            
            df_user_final["Fonte"] = "EXCEL"

            # --- FASE 4: CONFRONTO ---
            st.divider()
            st.subheader("📊 Risultati")
            
            # Arrotondamento
            df_pdf_clean["Check"] = df_pdf_clean["Importo"].round(2)
            df_user_final["Check"] = df_user_final["Importo"].round(2)
            
            # Movimenti mancanti
            missing_in_excel = df_pdf_clean[~df_pdf_clean["Check"].isin(df_user_final["Check"])]
            
            col_res1, col_res2 = st.columns(2)
            with col_res1:
                st.write(f"**Movimenti nel PDF ({len(df_pdf_clean)})**")
                st.dataframe(df_pdf_clean)
            
            with col_res2:
                if not missing_in_excel.empty:
                    st.error(f"⚠️ {len(missing_in_excel)} Movimenti presenti in Banca ma NON nel tuo Excel:")
                    st.dataframe(missing_in_excel[["Data", "Descrizione", "Importo"]])
                else:
                    st.success("Tutti i movimenti bancari sono stati trovati nel tuo Excel!")

            # Saldo
            diff = df_pdf_clean["Importo"].sum() - df_user_final["Importo"].sum()
            st.metric("Differenza Totale", f"€ {diff:,.2f}")

    except Exception as e:
        st.error(f"Qualcosa è andato storto: {e}")
