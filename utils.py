import json 
import streamlit as st

def load_translation(lang:str):
    with open(f"i18n/{lang}.json", "r", encoding="utf-8") as f:
        return json.load(f)
    
def t(key:str):
    lang = st.session_state.get("lang", "ru")
    translations = st.session_state.get("translations", {})
    return translations.get(key, key)
