# Cotizador MAC/MAF (m³) — Transporte m3k

## Ejecutar
pip install -r requirements.txt
streamlit run app.py

## Roles
- Admin (por defecto): usuario `admin`, clave `admin123`
- Comercial (por defecto): usuario `comercial`, clave `user123`

> Cambia claves en la pestaña **Admin**.

## Configuración clave (Admin)
1) Definir tarifa m3k para MAC y MAF.
2) Mapear cada producto (MAC/MAF) a:
   - Partida de producción (costo unitario por m³)
   - Partidas de colocación (costo unitario por m³)
3) Ajustar GG, Riesgo, Márgenes y descuento máximo.

## Datos
Coloca `Documento_Maestro_Costeo_2026.xlsx` en la misma carpeta.
Las listas de precios y la config se guardan en `overrides/`.
