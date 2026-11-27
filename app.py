"""Lazarus: punto de entrada. Define el menú y los nombres de las páginas."""
import streamlit as st

pages = {
    "Búsqueda de empleo": [
        st.Page("pages/0_Inicio.py", title="Inicio", icon="🏠", default=True),
        st.Page("pages/1_CV.py", title="Mi CV", icon="📄"),
        st.Page("pages/2_Buscar.py", title="Buscar empleo", icon="🔍"),
        st.Page("pages/3_Vacantes.py", title="Vacantes recomendadas", icon="⭐"),
        st.Page("pages/4_Carta.py", title="Carta de presentación", icon="✉️"),
        st.Page("pages/8_Entrevista.py", title="Preparar entrevista", icon="🎯"),
        st.Page("pages/5_Mercado.py", title="Qué pide el mercado", icon="📊"),
    ],
    "Ajustes": [
        st.Page("pages/6_Configuracion.py", title="Configuración", icon="⚙️"),
        st.Page("pages/7_Corridas.py", title="Actividad y diagnóstico", icon="🧭"),
    ],
}
st.navigation(pages).run()
