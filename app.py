"""Lazarus: punto de entrada. Define el menú y los nombres de las páginas."""
import streamlit as st

pages = {
    "Búsqueda de empleo": [
        st.Page("pages/0_Inicio.py", title="Inicio", icon=":material/home:", default=True),
        st.Page("pages/1_CV.py", title="Mi CV", icon=":material/description:"),
        st.Page("pages/2_Buscar.py", title="Buscar empleo", icon=":material/travel_explore:"),
        st.Page("pages/3_Vacantes.py", title="Vacantes recomendadas", icon=":material/work:"),
        st.Page("pages/9_Seguimiento.py", title="Mis postulaciones", icon=":material/bookmark:"),
        st.Page("pages/4_Carta.py", title="Carta de presentación", icon=":material/edit_note:"),
        st.Page("pages/8_Entrevista.py", title="Preparar entrevista", icon=":material/forum:"),
        st.Page("pages/5_Mercado.py", title="Qué pide el mercado", icon=":material/insights:"),
        st.Page("pages/10_Tutor.py", title="Tutor Lazarus", icon=":material/school:"),
    ],
    "Ajustes": [
        st.Page("pages/6_Configuracion.py", title="Configuración", icon=":material/settings:"),
        st.Page("pages/7_Corridas.py", title="Actividad y diagnóstico", icon=":material/monitoring:"),
    ],
}
st.navigation(pages).run()
