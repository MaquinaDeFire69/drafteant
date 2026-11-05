# Captura de cuotas

La integración consulta las siete ligas configuradas, mercado `h2h` (1X2), región `uk` y cuotas decimales de The Odds API. Solo se ejecuta manualmente: abrir la página **Análisis** no consume créditos.

1. Añade `ODDS_API_KEY=tu_clave` al archivo `.env` local. No subas la clave a Git.
2. Aplica la migración aditiva `d7a60b4c129e` con `python -m alembic upgrade head` cuando esté autorizada.
3. Ejecuta `python -m app.services.cuotas TODAS` para las siete ligas, o por ejemplo `python -m app.services.cuotas F1` para Ligue 1. Sin argumentos captura solo Premier League.
4. Abre `/analisis`. Las cuotas aparecen en parlays cuando el partido, la casa y la versión del pronóstico coinciden.

El comando informa eventos recibidos, partidos cruzados, cuotas nuevas, selecciones nuevas, partidos sin cruce confiable y créditos usados/restantes. Una consulta de un mercado en una región cuesta **1 crédito**, según la [documentación de la API](https://the-odds-api.com/liveapi/guides/v4/). Repetir una respuesta sin cambios no duplica cuotas. Cada cambio posterior de cuota se guarda como una nueva captura.

El valor estimado se calcula como `probabilidad_del_modelo × cuota_decimal − 1`. La sección **Seguimiento de selecciones** fija una selección con la primera cuota capturada por pronóstico y simula 100 unidades por partido al llegar el resultado. Es una estimación antes de gastos y depende de que la probabilidad esté calibrada y de que la cuota siga disponible. Esta etapa no crea apuestas ni parlays.
