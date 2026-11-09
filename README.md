# Pronósticos de fútbol

Aplicación para consultar partidos próximos, estimar probabilidades de resultados, evaluar el modelo y simular selecciones individuales y parlays con cuotas capturadas.

El proyecto registra predicciones y cuotas para comparar lo estimado con los resultados posteriores. No envía apuestas a casas de apuestas: marcar un registro como `Apostada` es una anotación manual.

## Tecnologías y fuentes de datos

| Componente | Tecnología o fuente |
| --- | --- |
| Backend y API | Python, FastAPI y Uvicorn |
| Vistas | Jinja2, Tailwind CSS y HTMX |
| Gráficas | Chart.js |
| Base de datos | PostgreSQL |
| Acceso a datos y migraciones | SQLAlchemy, psycopg y Alembic |
| Modelado y análisis | NumPy, pandas, SciPy, statsmodels y scikit-learn |
| Resultados históricos | CSV de football-data.co.uk |
| Calendario, horarios y estados | API de football-data.org |
| Cuotas | The Odds API, 1X2 (`h2h`) y captura opcional por evento de más/menos 2.5 y ambos anotan; región `uk`, formato decimal |

El modelo activo usa Poisson con corrección Dixon-Coles y ponderación temporal. Actualmente `app/services/cache.py` configura `xi = 0.004` para todas las ligas. El backtest también puede comparar una base histórica, Poisson y Elo.

Las fuentes football-data.co.uk y football-data.org son servicios distintos. Los CSV históricos no requieren la clave de la API de calendario.

## Módulos de la aplicación

### Próximos — `/`

Muestra partidos futuros por liga y periodo, con estado, hora de inicio y probabilidades del último pronóstico guardado. Las horas de las vistas se presentan en la zona de Ciudad de México.

Las tarjetas muestran el escudo cuando football-data.org lo incluye en el calendario o se obtiene con la sincronización de escudos; si no hay imagen disponible, muestran las iniciales del equipo. El detalle `/partido/{id}` permite consultar el partido, la forma reciente de los equipos y, cuando hay datos suficientes, marcadores probables y mercados derivados como ambos anotan y más de 2.5 goles.

### Precisión — `/precision`

Evalúa partidos con resultado y pronóstico publicado antes del inicio. Incluye acierto, log-loss, Brier y calibración por intervalos, con filtros por liga, versión y fechas.

La calibración compara probabilidades estimadas con frecuencias observadas. Log-loss y Brier más bajos indican mejores resultados bajo esas métricas. La precisión histórica de la vista y las pruebas temporales de `comparar.py` son evaluaciones diferentes.

### Análisis — `/analisis`

Genera parlays de 2 a 5 partidos distintos con cuotas de una misma casa. Permite elegir liga, periodo, mercado y cantidad de selecciones; el valor inicial es 2. Los mercados son 1X2 (local, empate, visitante), más/menos de 2.5 goles, ambos anotan (sí/no) y mixto (la opción con mayor valor esperado por partido entre los mercados disponibles). Se muestran hasta cinco combinaciones por categoría:

| Categoría de la interfaz | Probabilidad conjunta estimada |
| --- | --- |
| Seguras | 70 % o más |
| Para analizar | 60 % a menos de 70 % |
| Riesgosas | 40 % a menos de 60 % |
| Por si quieres regalar tu dinero | 20 % a menos de 40 % |

Las combinaciones inferiores al 20 % se omiten. “Seguras” es una etiqueta de la interfaz, no una garantía. La probabilidad conjunta se calcula multiplicando probabilidades, bajo una aproximación de independencia.

Las probabilidades de goles y ambos anotan se calculan con la matriz del modelo al generar cada pronóstico. Los pronósticos anteriores a la migración no tienen estos valores: genera pronósticos nuevos para ver estos mercados. Solo aparecen cuotas que el proveedor devolvió para la casa consultada; una ausencia de cuotas no se rellena con datos inventados. En modo mixto se elige una opción por partido y no se repite ningún encuentro en la combinación.

Para limitar el coste de generación se consideran hasta 16 selecciones con mayor probabilidad y 16 con mejor valor esperado. Si el parlay tiene 4 o 5 selecciones, el conjunto se reduce a 8 de cada grupo. Esto es una búsqueda parcial, no una revisión exhaustiva de todas las combinaciones. Se muestra la cuota decimal, el valor esperado y la comparación entre modelo y probabilidad implícita del mercado.

### Simulación — `/simulacion`

Reúne herramientas para probar y seguir decisiones:

- **Exposición:** banca de referencia, límites por partido/equipo y modo advertencia o bloqueo al crear parlays. El monto de un parlay cuenta completo en cada selección que lo integra.
- **Parlays:** guardar propuestas dobles del modelo o crear combinaciones personales de 2 a 5 partidos de una misma casa, eligiendo mercado y resultado para cada partido.
- **Individuales:** revisar selecciones automáticas y filtrar por liga, casa, probabilidad, valor esperado y rango de cuotas. Por defecto simulan 100 unidades por selección.
- **Estrategias guardadas:** conservar reglas y un monto para evaluar el historial y nuevas selecciones que cumplan los filtros.
- **Seguimiento:** marcar registros como `Simulada`, `Apostada` o `Descartada`; los descartados quedan fuera de las métricas de rendimiento.
- **Resultados:** acierto, inversión, retorno, ganancia y ROI; segmentación por liga, casa y probabilidad; comparación por tipo de apuesta.
- **Curva de banca:** inversión y retorno diarios, ganancia y ROI acumulados, y drawdown. Actualmente corresponde a individuales filtradas y agrupa por fecha de inicio, no por hora real de liquidación.
- **CLV:** compara la cuota tomada con la última cuota prepartido almacenada de la misma casa, para individuales que ya iniciaron o terminaron.

Limitaciones actuales que conviene conocer:

- Exposición incluye individuales automáticas pendientes en estado `Simulada`, además de las `Apostada`, y parlays guardados activos. Por eso puede mostrar partidos que no elegiste manualmente.
- El selector de propuestas del modelo en Simulación todavía genera dobles; elegir 3–5 selecciones en Análisis no transfiere automáticamente esa elección a Simulación. Sí se pueden crear parlays personales de hasta cinco.
- La tabla por tipo actualmente desglosa individuales, dobles, triples y cuádruples; todavía no tiene una categoría separada para cinco selecciones.
- La cuota de “cierre” es la última disponible en el historial local. Una captura antigua o única no equivale necesariamente al cierre real del mercado.

## Ligas disponibles

| Código para comandos | Liga |
| --- | --- |
| `E0` | Premier League |
| `SP1` | La Liga |
| `I1` | Serie A |
| `D1` | Bundesliga |
| `F1` | Ligue 1 |
| `N1` | Eredivisie |
| `P1` | Primeira Liga |
| `MX1` | Liga MX |
| `MLS` | Major League Soccer |
| `CL` | UEFA Champions League |
| `EL` | UEFA Europa League |

Liga MX y MLS importan su histórico desde los archivos mundiales de football-data.co.uk, disponibles desde 2012. Champions League usa football-data.org para histórico y calendario. La clave configurada actualmente no incluye Liga MX, MLS ni Europa League en football-data.org: al ejecutar la sincronización, Liga MX y MLS se omiten de calendario y Europa League informa que tu plan no autoriza la competencia. Las cuatro tienen soporte de cuotas en The Odds API; sin calendario e histórico suficientes no se generan pronósticos utilizables.

Para crear o actualizar próximos encuentros de Liga MX y MLS desde The Odds API, usa este comando explícito, que consume créditos:

```powershell
python -m app.services.fixtures MX1 MLS --cuotas
```

Solo guarda equipos que ya tengan historial en la liga y muestra los nombres que requieren un alias. Después ejecuta `python -m app.services.pronosticar` de forma explícita para cada liga:

```powershell
python -c "from app.services.pronosticar import generar; generar('MX1')"
python -c "from app.services.pronosticar import generar; generar('MLS')"
```

## Instalación local en Windows / PowerShell

Ejecuta los comandos desde la raíz del proyecto, donde están `requirements.txt` y `alembic.ini`. Se recomienda Python 3.12, usado en el entorno de desarrollo, y una instalación de PostgreSQL con servidor en ejecución.

### 1. Crear el entorno e instalar dependencias

```powershell
cd C:\Users\aarm1\Desktop\drafteant
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Crear el entorno se hace una vez; activarlo se repite en cada terminal nueva. Si ya existe `.venv`, usa el existente. Repite la instalación de dependencias cuando cambie `requirements.txt`.

Si PowerShell impide activar scripts, puedes ejecutar directamente el Python del entorno:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Este patrón sirve para todos los comandos `python` de la guía.

### 2. Configurar `.env`

Crea o edita `.env` en la raíz con estos nombres exactos. Los valores siguientes son ejemplos, no credenciales reales:

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:TU_PASSWORD@localhost:5432/pronosticos_db
FOOTBALL_DATA_API_KEY=TU_CLAVE_FOOTBALL_DATA
ODDS_API_KEY=TU_CLAVE_ODDS_API
```

| Variable | Uso |
| --- | --- |
| `DATABASE_URL` | Obligatoria para conectar PostgreSQL. Ajusta usuario, contraseña, host, puerto y nombre de BD. |
| `FOOTBALL_DATA_API_KEY` | Sincronización del calendario y de escudos de equipos mediante football-data.org. |
| `ODDS_API_KEY` | Captura manual de cuotas mediante The Odds API. |
| `THESPORTSDB_API_KEY` | Opcional; clave de TheSportsDB para completar escudos (la clave gratuita `123` se usa por defecto). |

Si la contraseña contiene caracteres especiales de URL, deben codificarse en la cadena de conexión. `.env` está excluido de Git; no publiques claves ni contraseñas. Reinicia la aplicación tras cambiar la configuración.

### 3. Preparar PostgreSQL

Para verificar el servicio y el puerto:

```powershell
Get-Service *postgres*
Test-NetConnection localhost -Port 5432
```

Si el servicio está detenido, abre PowerShell como administrador y arranca el nombre que aparezca en la consulta anterior:

```powershell
Start-Service -Name "NOMBRE_REAL_DEL_SERVICIO"
```

No todas las instalaciones usan el mismo nombre. Si no aparece ninguno, revisa la instalación/configuración del servidor; tener `psql.exe` no implica que el servidor esté iniciado.

Configura la ruta de utilidades según tu versión (ejemplo: PostgreSQL 18):

```powershell
$pg = "C:\Program Files\PostgreSQL\18\bin"
& "$pg\createdb.exe" -h localhost -U postgres pronosticos_db
```

Ejecuta `createdb` solo si la base aún no existe. Luego elige una de estas alternativas.

**A. Restaurar `pronosticos_db.backup` en una base vacía**

```powershell
& "$pg\pg_restore.exe" --list .\pronosticos_db.backup
& "$pg\pg_restore.exe" -h localhost -U postgres -d pronosticos_db --no-owner --no-acl --exit-on-error .\pronosticos_db.backup
python -m alembic current
python -m alembic upgrade head
```

`--list` inspecciona el archivo. `pg_restore` importa estructura y datos; `--no-owner --no-acl` evita depender de propietarios y permisos del equipo original. Alembic aplica los cambios posteriores al respaldo. No restaures otra vez sobre una BD ya usada sin revisar antes su contenido.

Si el respaldo no contiene un historial de Alembic coherente y aparecen errores como “table already exists”, revisa la revisión del esquema antes de continuar. No uses `stamp head` para ocultar ese problema: marca una versión sin ejecutar sus cambios.

**B. Empezar con una base vacía, sin restaurar un respaldo**

```powershell
python -m alembic upgrade head
python -m app.services.importar
```

El primer comando crea el esquema; el segundo importa el histórico desde la temporada que comienza en 2018 hasta la actual para todas las ligas. Requiere Internet y puede tardar.

### 4. Cargar calendario, generar pronósticos y capturar cuotas

Con datos históricos disponibles:

```powershell
python -m app.tareas
python -m app.services.cuotas TODAS
```

`app.tareas` actualiza resultados recientes, sincroniza próximos partidos si hay clave y genera pronósticos. La captura de cuotas es un paso aparte que consume créditos de The Odds API.

Para comenzar solo con Premier League:

```powershell
python -m app.tareas E0
python -m app.services.cuotas E0
```

Para importar por primera vez las nuevas ligas:

```powershell
python -m app.services.importar MX1 MLS CL EL
```

La importación de Champions League consulta una temporada por solicitud y puede tardar. Europa League mostrará una omisión mientras la clave de football-data.org no tenga cobertura. Tras una importación con resultados, ejecuta `python -m app.tareas CL` para traer su calendario y generar pronósticos.

### 5. Abrir la aplicación

```powershell
python -m uvicorn app.main:app --reload
```

Deja esta terminal abierta y visita:

- Aplicación: http://127.0.0.1:8000/
- Verificación de conexión a la BD: http://127.0.0.1:8000/salud
- Documentación interactiva de la API: http://127.0.0.1:8000/docs

`--reload` reinicia el servidor cuando cambia el código y se usa para desarrollo. Detén el servidor con `Ctrl+C`. Si el puerto está ocupado:

```powershell
python -m uvicorn app.main:app --reload --port 8001
```

En ese caso abre http://127.0.0.1:8001/.

## Comandos de actualización y para qué sirven

### Actualización habitual

```powershell
python -m app.tareas
python -m app.tareas E0 SP1 F1
```

Sin argumentos procesa todas las ligas; con códigos procesa las indicadas. En orden:

1. Importa resultados de la temporada anterior y la actual desde CSV.
2. Sincroniza el calendario de los próximos 14 días con football-data.org si existe la clave.
3. Entrena y guarda nuevos pronósticos por liga.

Este comando escribe en la BD y consulta fuentes externas, pero no captura cuotas. Usa códigos válidos: actualmente los argumentos desconocidos se filtran y, si ninguno es válido, se procesan todas las ligas. Revisa la salida porque algunas fallas por liga se imprimen y el proceso continúa.

### Importación histórica completa

```powershell
python -m app.services.importar
python -m app.services.importar E0 SP1
```

Importa desde 2018 hasta la temporada actual. Añade equipos/partidos y actualiza resultados existentes. Úsalo para llenar una BD nueva o ampliar el histórico; para el mantenimiento habitual es suficiente `app.tareas`.

Al finalizar cada importación, se sincronizan automáticamente los escudos disponibles con football-data.org y TheSportsDB. Si una fuente falla o no ofrece una liga, el error se informa y la importación de resultados no se interrumpe.

### Solo sincronizar calendario

```powershell
python -m app.services.fixtures
python -m app.services.fixtures E0 SP1
```

Actualiza partidos, identificadores externos, horarios y estados. La consulta actual solicita estados `SCHEDULED`, `TIMED`, `POSTPONED` y `CANCELLED`; los resultados históricos se actualizan mediante la importación CSV. Requiere `FOOTBALL_DATA_API_KEY`. No entrena ni genera pronósticos. El comando habitual consulta 14 días; para otra ventana:

```powershell
python -c "from app.services.fixtures import sincronizar; sincronizar('E0', dias=30)"
```

Seleccionar 30 días en una vista no descarga automáticamente 30 días de calendario: muestra los partidos que ya estén en la BD.

### Reintentar la sincronización de escudos

```powershell
python -m app.services.escudos
python -m app.services.escudos E0 SP1
```

Consulta football-data.org y luego TheSportsDB para completar los escudos que falten en `equipos.escudo_url`; no reemplaza los escudos existentes. El segundo proveedor cubre las ligas nacionales configuradas, Liga MX y MLS. Para Champions y Europa League busca los equipos en las ligas nacionales disponibles en TheSportsDB, así que algunos clubes pueden no aparecer. Solo se guardan URLs HTTPS alojadas por TheSportsDB. Si una liga no está cubierta por los proveedores, se mantienen las iniciales como alternativa.

La importación histórica y la actualización habitual con `app.tareas` ya realizan este intento automáticamente. Usa este comando solo si quieres reintentar sin importar resultados.

TheSportsDB tiene límites de uso y sus imágenes pueden estar sujetas a licencias de terceros. Verifica los derechos de cada escudo antes de publicar la aplicación o reutilizar imágenes fuera de tu entorno de desarrollo; consulta sus [términos de uso](https://www.thesportsdb.com/docs_terms_of_use.php).

### Solo generar pronósticos

```powershell
python -m app.services.pronosticar
python -c "from app.services.pronosticar import generar; generar('SP1')"
```

El primer comando genera únicamente para `E0`: ese módulo no interpreta argumentos de liga. Para otras ligas usa la llamada explícita o `python -m app.tareas SP1` si quieres hacer la actualización completa.

Entrena a partir del histórico local y añade pronósticos; no reemplaza los anteriores. Equipos sin historial suficiente pueden omitirse. Los pronósticos nuevos también guardan probabilidades de más/menos 2.5 goles y ambos anotan. Después, captura cuotas para poder usarlos en Análisis.

### Capturar cuotas y empezar a recopilar CLV

```powershell
python -m app.services.cuotas
python -m app.services.cuotas F1
python -m app.services.cuotas E0 SP1 I1
python -m app.services.cuotas TODAS
```

Sin argumentos consulta solo `E0`; `TODAS` consulta las siete ligas. Requiere `ODDS_API_KEY`, partidos futuros cruzables y conectividad. Guarda cuotas nuevas y crea selecciones de seguimiento cuando hay pronósticos y cuotas válidos. Imprime créditos usados/restantes y eventos sin coincidencia confiable.

Para medir CLV, repite la captura antes del inicio: una captura inicial y otra más cercana al partido permiten observar cambios. El código conserva cambios de cuota y evita duplicar el mismo evento/casa/fecha de actualización. No hay un programador automático de capturas: debes ejecutar estos comandos o programarlos por separado. Abrir las vistas no consume créditos de The Odds API. Consulta el saldo informado por cada captura antes de repetir procesos masivos.

Para traer cuotas de más/menos 2.5 goles y ambos anotan de los próximos partidos de una liga, primero ejecuta la captura 1X2 anterior y luego:

```powershell
python -m app.services.mercados E0 --limite 3
```

Consulta hasta tres eventos próximos ya cruzados con la BD; `--limite` acepta de 1 a 20. El endpoint por evento pide `totals`, `alternate_totals` y `btts`, guarda solo la línea exacta de 2.5 para goles y muestra los créditos usados/restantes. Puede gastar hasta tres créditos por evento con región `uk`, según los mercados que devuelva la API. Ejecutarlo otra vez solo guarda actualizaciones nuevas, pero la consulta vuelve a consumir créditos. La disponibilidad cambia según casa, liga y fecha. Si la respuesta no incluye esos mercados, Análisis no mostrará esa opción.

## Rutina de uso sugerida

1. Inicia PostgreSQL y activa `.venv`.
2. Ejecuta `python -m app.tareas E0` (o las ligas que vas a revisar).
3. Ejecuta `python -m app.services.cuotas E0` después de generar pronósticos. Si quieres mercados de goles y ambos anotan, añade `python -m app.services.mercados E0 --limite 3`.
4. Inicia Uvicorn y abre Próximos, Análisis o Simulación.
5. Guarda las combinaciones que quieras seguir y configura exposición.
6. Antes de los partidos, repite la captura si necesitas datos más cercanos al cierre.
7. Después de los partidos, vuelve a actualizar resultados; las métricas se recalculan al consultar las vistas.

Los resultados dependen de cuándo las fuentes publiquen sus marcadores. Además, algunos modelos de los endpoints se almacenan en memoria: reinicia Uvicorn después de actualizar el histórico para renovar esa caché.

## Evaluación y pruebas

### Backtest temporal por liga

```powershell
python comparar.py --help
python comparar.py --ligas E0 --dias-prueba 180 --paso 60 --modelos base dc
python comparar.py --ligas E0 SP1 I1 D1 F1 N1 P1
```

Entrena con partidos anteriores a cada corte y evalúa los posteriores. Reporta acierto, log-loss, Brier, RPS, cobertura, omisiones y fallos de entrenamiento. No descarga partidos ni cambia el modelo activo.

| Opción | Función / valor por defecto |
| --- | --- |
| `--ligas` | Ligas a comparar; por defecto todas. |
| `--dias-prueba` | Días de histórico reservados para prueba; 730. |
| `--paso` | Días entre reentrenamientos; 60. |
| `--modelos` | Uno o varios: `base`, `poisson`, `dc`, `elo`; por defecto todos. |
| `--xis` | Valores de decaimiento temporal para Dixon-Coles: `0.0019 0.003 0.004 0.006 0.008 0.012`. |
| `--salida` | CSV de resultados; `backtest_resultados.csv`. |
| `--configuracion` | JSON de sugerencias; `backtest_configuracion_recomendada.json`. |

Ejemplo con archivos de salida propios:

```powershell
python comparar.py --ligas E0 --modelos base dc --xis 0.003 0.004 --salida prueba_e0.csv --configuracion sugerencias_e0.json
```

La configuración sugerida no se aplica automáticamente: debe revisarse antes de modificar `app/services/cache.py`.

### Evaluación simple de Premier League

```powershell
python evaluar.py
```

Script básico que entrena Poisson y evalúa el último año del histórico de `E0`. Necesita partidos de entrenamiento y prueba; no maneja bien una muestra vacía. Para evaluación repetible por ligas utiliza `comparar.py`.

### Pruebas del proyecto

```powershell
python -m unittest discover -s tests -p "test_*.py" -q
python -m compileall -q app tests
```

El primer comando ejecuta las pruebas automatizadas. Las pruebas de cuotas simulan las respuestas externas y usan SQLite en memoria; no requieren consumir créditos. El segundo comprueba compilación/sintaxis de los archivos Python, pero no sustituye las pruebas funcionales.

## Comandos de base de datos

```powershell
python -m alembic current
python -m alembic heads
python -m alembic history
python -m alembic upgrade head
```

`current` muestra la versión aplicada en la BD; `heads`, la última revisión del código; `history`, la cadena de cambios; `upgrade head`, aplica migraciones pendientes. Haz respaldo antes de actualizar una base con datos importantes.

Para crear un respaldo con nombre distinto al original:

```powershell
$pg = "C:\Program Files\PostgreSQL\18\bin"
& "$pg\pg_dump.exe" -h localhost -U postgres -d pronosticos_db -Fc -f .\pronosticos_respaldo_manual.backup
```

El archivo de destino debe ser nuevo o uno que decidas reemplazar. Este comando respalda la BD; no modifica sus registros.

Para verificar la conexión desde PowerShell con la aplicación ejecutándose:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/salud
```

La respuesta esperada indica `estado: ok` y `base_de_datos: conectada`.

## API local adicional

| Ruta | Uso |
| --- | --- |
| `/salud` | Ejecuta una consulta simple para comprobar la BD. |
| `/equipos?liga=E0` | Equipos conocidos por el modelo de esa liga. |
| `/pronostico?local=Arsenal&visitante=Chelsea&liga=E0` | Calcula probabilidades; usa nombres exactos de `/equipos`. |
| `/proximos?liga=E0&dias=14` | Partidos futuros con el último pronóstico guardado. |
| `/docs` | Documentación y pruebas interactivas de endpoints. |

## Conceptos usados en las vistas

| Concepto | Significado |
| --- | --- |
| Cuota decimal `x2.00` | Una selección ganada de 100 retorna 200 en total, incluyendo el monto inicial. |
| Probabilidad implícita | `1 / cuota`; incluye el margen de la casa. |
| Diferencia modelo–mercado | Probabilidad del modelo menos la implícita, expresada en puntos porcentuales. |
| Valor esperado | `probabilidad × cuota − 1`. Depende de la calidad de la probabilidad estimada. |
| Ganancia | Retorno menos inversión de apuestas evaluadas. |
| ROI | Ganancia dividida entre inversión evaluada. |
| Drawdown | Caída de banca respecto a su máximo anterior. |
| CLV | `cuota tomada / cuota de cierre registrada − 1`. Positivo indica una cuota tomada mayor. |
| Selección o pierna | Cada resultado individual dentro de un parlay. |

## Estructura del proyecto

```text
app/
  main.py                 Aplicación y endpoints JSON
  config.py               Configuración desde .env
  database.py             Motor y sesiones de base de datos
  ligas.py                Ligas y temporadas
  tareas.py               Actualización coordinada
  models/__init__.py      Tablas SQLAlchemy
  routers/web.py          Rutas de las vistas y formularios
  services/
    importar.py           Importación de resultados CSV
    fixtures.py           Sincronización del calendario API
    modelo.py             Modelos predictivos
    cache.py              Configuración y caché del modelo activo
    pronosticar.py         Generación de pronósticos persistentes
    cuotas.py             Captura de cuotas 1X2
    mercados.py           Captura limitada de cuotas de goles y ambos anotan
    consultas.py          Consultas, precisión y generación de parlays
    seguimiento.py        Simulación, estrategias, exposición y CLV
  templates/              Vistas Jinja2
migrations/               Migraciones de esquema
tests/                    Pruebas automatizadas
comparar.py               Backtest temporal por liga
evaluar.py                Evaluación simple de Premier League
requirements.txt          Dependencias Python
alembic.ini               Configuración de Alembic
```

## Problemas frecuentes

- **`ModuleNotFoundError` (por ejemplo, `httpx`):** activa `.venv` y ejecuta `python -m pip install -r requirements.txt` con ese mismo intérprete.
- **`Connection refused` en el puerto 5432:** revisa el servicio PostgreSQL, host y puerto. El servidor puede estar detenido o configurado en otro puerto.
- **Error de contraseña:** revisa usuario y contraseña en `DATABASE_URL`; las utilidades `pg_restore` y `psql` usan sus propias opciones de conexión.
- **Tablas o columnas inexistentes:** consulta `python -m alembic current` y aplica las migraciones pendientes con `python -m alembic upgrade head`.
- **Próximos vacío:** revisa la clave de calendario, ejecuta `app.services.fixtures` y comprueba que existan encuentros dentro de las fechas filtradas.
- **Partidos sin pronóstico:** carga histórico y ejecuta `app.tareas` o `generar`; revisa omisiones por equipos sin datos.
- **Análisis sin parlays:** comprueba cuotas, coincidencia de equipos y versión de pronóstico, casa común, número de selecciones y umbral mínimo del 20 %.
- **CLV sin datos:** hacen falta cuotas guardadas antes del inicio; repetir una consulta después del partido no reconstruye el historial perdido.
- **Página sin estilos o gráficas:** Tailwind, HTMX y Chart.js se cargan desde CDN; el navegador necesita acceder a esos recursos.

Esta guía describe el comportamiento actual del código. Las claves, la disponibilidad de partidos y las cuotas dependen de los servicios configurados y sus permisos.
