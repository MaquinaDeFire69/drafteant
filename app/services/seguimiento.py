"""Selecciones y parlays simulados, evaluados con resultados oficiales."""

import math
from datetime import datetime, timezone

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, aliased

from app.ligas import nombre_liga
from app.models import (
    ConfiguracionExposicion, Cuota, Equipo, EstrategiaSimulacion, ParlaySimulado, Partido,
    PiernaParlay, Pronostico,
    SeleccionSeguimiento,
)
from app.services.consultas import agregar_cuotas, parlays, proximos_partidos, selecciones_destacadas


UNIDAD = 100.0
LIMITES_EXPOSICION_DEFECTO = {
    "banca_inicial": 1000.0, "limite_partido": 0.10,
    "limite_equipo": 0.20, "bloquear_exceso": False,
}


def configuracion_exposicion(db: Session) -> dict:
    configuracion = db.get(ConfiguracionExposicion, 1)
    if configuracion is None:
        return LIMITES_EXPOSICION_DEFECTO.copy()
    return {
        "banca_inicial": configuracion.banca_inicial,
        "limite_partido": configuracion.limite_partido,
        "limite_equipo": configuracion.limite_equipo,
        "bloquear_exceso": configuracion.bloquear_exceso,
    }


def guardar_configuracion_exposicion(
    db: Session, banca_inicial: float | str, limite_partido: float | str,
    limite_equipo: float | str, bloquear_exceso: bool,
) -> dict:
    banca = _monto(banca_inicial)
    try:
        limite_partido = float(limite_partido) / 100
        limite_equipo = float(limite_equipo) / 100
    except (TypeError, ValueError):
        raise ValueError("Los límites de exposición deben ser números") from None
    if not 0 < limite_partido <= 1 or not 0 < limite_equipo <= 1:
        raise ValueError("Cada límite debe estar entre 1 % y 100 %")
    configuracion = db.get(ConfiguracionExposicion, 1)
    if configuracion is None:
        configuracion = ConfiguracionExposicion(id=1)
        db.add(configuracion)
    configuracion.banca_inicial = banca
    configuracion.limite_partido = limite_partido
    configuracion.limite_equipo = limite_equipo
    configuracion.bloquear_exceso = bloquear_exceso
    return configuracion_exposicion(db)


def _agregar_exposicion(grupos: dict[int, dict], identificador: int, nombre: str, monto: float) -> None:
    grupo = grupos.setdefault(identificador, {"nombre": nombre, "monto": 0.0, "registros": 0})
    grupo["monto"] += monto
    grupo["registros"] += 1


def exposicion_activa(db: Session) -> dict:
    """Capital pendiente expuesto por partido y por el equipo elegido."""
    limites = configuracion_exposicion(db)
    por_partido: dict[int, dict] = {}
    por_equipo: dict[int, dict] = {}
    locales, visitas = aliased(Equipo), aliased(Equipo)
    individuales = db.execute(
        select(SeleccionSeguimiento, Partido, locales.nombre, visitas.nombre)
        .join(Partido, Partido.id == SeleccionSeguimiento.partido_id)
        .join(locales, locales.id == Partido.local_id)
        .join(visitas, visitas.id == Partido.visitante_id)
        .where(
            SeleccionSeguimiento.estado_registro.in_(("simulada", "apostada")),
            Partido.goles_local.is_(None), Partido.goles_visitante.is_(None),
        )
    ).all()
    for seleccion, partido, local, visita in individuales:
        _agregar_exposicion(por_partido, partido.id, f"{local} vs {visita}", seleccion.monto)
        equipo_id, equipo = (partido.local_id, local) if seleccion.lado == "local" else (partido.visitante_id, visita)
        _agregar_exposicion(por_equipo, equipo_id, equipo, seleccion.monto)

    piernas = db.execute(
        select(PiernaParlay, ParlaySimulado, Partido, locales.nombre, visitas.nombre)
        .join(ParlaySimulado, ParlaySimulado.id == PiernaParlay.parlay_id)
        .join(Partido, Partido.id == PiernaParlay.partido_id)
        .join(locales, locales.id == Partido.local_id)
        .join(visitas, visitas.id == Partido.visitante_id)
        .where(
            ParlaySimulado.estado_registro.in_(("simulada", "apostada")),
            Partido.goles_local.is_(None), Partido.goles_visitante.is_(None),
        )
    ).all()
    for pierna, parlay, partido, local, visita in piernas:
        _agregar_exposicion(por_partido, partido.id, f"{local} vs {visita}", parlay.monto)
        equipo_id, equipo = (partido.local_id, local) if pierna.lado == "local" else (partido.visitante_id, visita)
        _agregar_exposicion(por_equipo, equipo_id, equipo, parlay.monto)

    def preparar(grupos: dict[int, dict], limite: float) -> list[dict]:
        maximo = limites["banca_inicial"] * limite
        return sorted(({
            "id": identificador, **grupo, "porcentaje": grupo["monto"] / limites["banca_inicial"],
            "limite": maximo, "excedido": grupo["monto"] > maximo,
            "cerca_limite": grupo["monto"] >= maximo * 0.8,
        } for identificador, grupo in grupos.items()), key=lambda fila: -fila["monto"])

    return {
        "configuracion": limites,
        "partidos": preparar(por_partido, limites["limite_partido"]),
        "equipos": preparar(por_equipo, limites["limite_equipo"]),
    }


def validar_exposicion_parlay(db: Session, partido_ids: list[int], monto: float | str | None) -> list[str]:
    """Devuelve avisos para un parlay nuevo sin alterar la exposición guardada."""
    monto = _monto(monto)
    actual = exposicion_activa(db)
    limites = actual["configuracion"]
    por_partido = {fila["id"]: fila["monto"] for fila in actual["partidos"]}
    por_equipo = {fila["id"]: fila["monto"] for fila in actual["equipos"]}
    candidatas = {fila["id"]: fila for fila in candidatas_parlay(db)}
    avisos = []
    for partido_id in set(partido_ids):
        candidata = candidatas.get(partido_id)
        partido = db.get(Partido, partido_id)
        if candidata is None or partido is None:
            continue
        total_partido = por_partido.get(partido_id, 0.0) + monto
        if total_partido > limites["banca_inicial"] * limites["limite_partido"]:
            avisos.append(f"{candidata['local']} vs {candidata['visitante']} supera el límite por partido")
        equipo_id = partido.local_id if candidata["lado"] == "local" else partido.visitante_id
        total_equipo = por_equipo.get(equipo_id, 0.0) + monto
        if total_equipo > limites["banca_inicial"] * limites["limite_equipo"]:
            avisos.append(f"{candidata['seleccion']} supera el límite por equipo")
    return avisos


def curva_banca(filas: list[dict], banca_inicial: float = 1_000.0) -> dict:
    """Construye una serie diaria de banca sólo con selecciones ya terminadas."""
    banca_inicial = _monto(banca_inicial)
    por_fecha: dict[str, dict[str, float]] = {}
    for fila in filas:
        if not fila["terminada"] or not fila.get("fecha"):
            continue
        dia = por_fecha.setdefault(fila["fecha"], {"inversion": 0.0, "retorno": 0.0})
        dia["inversion"] += fila["monto"]
        if fila["ganada"]:
            dia["retorno"] += fila["monto"] * fila["cuota"]

    banca = pico = banca_inicial
    inversion_acumulada = retorno_acumulado = 0.0
    puntos = []
    for fecha, dia in sorted(por_fecha.items()):
        inversion_acumulada += dia["inversion"]
        retorno_acumulado += dia["retorno"]
        ganancia_acumulada = retorno_acumulado - inversion_acumulada
        banca = banca_inicial + ganancia_acumulada
        pico = max(pico, banca)
        drawdown = banca - pico
        puntos.append({
            "fecha": fecha, "inversion": dia["inversion"], "retorno": dia["retorno"],
            "ganancia_acumulada": ganancia_acumulada, "banca": banca,
            "roi_acumulado": ganancia_acumulada / inversion_acumulada if inversion_acumulada else 0.0,
            "drawdown": drawdown, "drawdown_pct": drawdown / pico if pico else 0.0,
        })
    peor = min(puntos, key=lambda punto: punto["drawdown"], default=None)
    return {
        "banca_inicial": banca_inicial, "puntos": puntos,
        "peor_drawdown": peor["drawdown"] if peor else 0.0,
        "peor_drawdown_pct": peor["drawdown_pct"] if peor else 0.0,
    }


def _resumen_individuales(filas: list[dict]) -> dict:
    """Resume filas individuales ya filtradas, sin mezclar las pendientes."""
    terminadas = [fila for fila in filas if fila["terminada"]]
    inversion = sum(fila["monto"] for fila in terminadas)
    retorno = sum(
        fila["monto"] * fila["cuota"] for fila in terminadas if fila["ganada"]
    )
    ganancia = retorno - inversion
    return {
        "total": len(filas), "evaluadas": len(terminadas),
        "pendientes": len(filas) - len(terminadas),
        "aciertos": sum(bool(fila["ganada"]) for fila in terminadas),
        "inversion": inversion, "retorno": retorno, "ganancia": ganancia,
        "roi": ganancia / inversion if inversion else None,
    }


def _rango_probabilidad(probabilidad: float) -> str:
    if probabilidad < 0.40:
        return "Menos de 40%"
    if probabilidad < 0.60:
        return "40–59%"
    if probabilidad < 0.70:
        return "60–69%"
    return "70% o más"


def _segmentos_individuales(filas: list[dict]) -> dict[str, list[dict]]:
    """Agrupa el mismo histórico por tres dimensiones comparables."""
    dimensiones = {
        "liga": lambda fila: fila["liga"],
        "casa": lambda fila: fila["casa"],
        "probabilidad": lambda fila: _rango_probabilidad(fila["probabilidad"]),
    }
    salida = {}
    for nombre, clave in dimensiones.items():
        grupos: dict[str, list[dict]] = {}
        for fila in filas:
            grupos.setdefault(clave(fila), []).append(fila)
        orden = (lambda etiqueta: ["Menos de 40%", "40–59%", "60–69%", "70% o más"].index(etiqueta)) \
            if nombre == "probabilidad" else None
        salida[nombre] = [
            {"nombre": etiqueta, **_resumen_individuales(grupo)}
            for etiqueta, grupo in sorted(grupos.items(), key=lambda item: orden(item[0]) if orden else item[0])
        ]
    return salida


def _utc(valor: datetime) -> datetime:
    return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor.astimezone(timezone.utc)


def _resumen_clv(filas: list[dict]) -> dict:
    medibles = [fila for fila in filas if fila["clv"] is not None]
    if not medibles:
        return {"n": 0, "promedio": None, "positivos": 0, "con_multiples_capturas": 0}
    return {
        "n": len(medibles),
        "promedio": sum(fila["clv"] for fila in medibles) / len(medibles),
        "positivos": sum(fila["clv"] > 0 for fila in medibles),
        "con_multiples_capturas": sum(fila["capturas_cuotas"] > 1 for fila in medibles),
    }


def crear_selecciones(db: Session, partido_ids: list[int] | None = None) -> int:
    """Fija una selección por pronóstico usando la primera captura válida de cuotas."""
    consulta = (
        select(Partido, Pronostico)
        .join(Pronostico, Pronostico.partido_id == Partido.id)
        .where(
            Partido.inicio_utc.is_not(None),
            Pronostico.publicado_en.is_not(None),
        )
    )
    if partido_ids is not None:
        if not partido_ids:
            return 0
        consulta = consulta.where(Partido.id.in_(partido_ids))

    creadas = 0
    for partido, pronostico in db.execute(consulta).all():
        if _utc(pronostico.publicado_en) >= _utc(partido.inicio_utc):
            continue
        existe = db.scalar(select(SeleccionSeguimiento.id).where(
            SeleccionSeguimiento.pronostico_id == pronostico.id,
        ))
        if existe is not None:
            continue
        lado, probabilidad = max(
            (("local", pronostico.prob_local), ("visitante", pronostico.prob_visitante)),
            key=lambda item: item[1],
        )
        cuotas = list(db.scalars(
            select(Cuota)
            .where(
                Cuota.partido_id == partido.id,
                Cuota.pronostico_id == pronostico.id,
            )
            .order_by(Cuota.capturada_en, Cuota.id)
        ))
        cuotas = [c for c in cuotas if _utc(c.capturada_en) < _utc(partido.inicio_utc)]
        if not cuotas:
            continue
        primera_captura = cuotas[0].capturada_en
        candidatas = [c for c in cuotas if c.capturada_en == primera_captura]
        campo = "cuota_local" if lado == "local" else "cuota_visitante"
        cuota = max(candidatas, key=lambda c: getattr(c, campo))
        db.add(SeleccionSeguimiento(
            partido_id=partido.id, pronostico_id=pronostico.id, cuota_id=cuota.id,
            lado=lado, probabilidad=probabilidad, cuota_decimal=getattr(cuota, campo),
            casa=cuota.casa, seleccionada_en=primera_captura,
            version_modelo=pronostico.version_modelo, publicado_en=pronostico.publicado_en,
            monto=UNIDAD, estado_registro="simulada",
        ))
        creadas += 1
    return creadas


def casas_disponibles(db: Session) -> list[str]:
    """Casas presentes en las selecciones ya fijadas."""
    if not inspect(db.get_bind()).has_table("selecciones_seguimiento"):
        return []
    return list(db.scalars(
        select(SeleccionSeguimiento.casa).distinct().order_by(SeleccionSeguimiento.casa)
    ))


def rendimiento_selecciones(
    db: Session,
    liga: str | None = None,
    casa: str | None = None,
    min_probabilidad: float = 0.0,
    min_valor: float = -1.0,
    cuota_min: float | None = None,
    cuota_max: float | None = None,
    limite: int = 50,
    monto: float | None = None,
) -> dict:
    """Devuelve las selecciones fijadas y sus resultados simulados a una unidad de 100."""
    vacio = {"total": 0, "evaluadas": 0, "pendientes": 0, "aciertos": 0,
             "inversion": 0.0, "retorno": 0.0, "ganancia": 0.0, "roi": None,
             "filas": [], "filas_para_curva": [], "unidad": UNIDAD,
             "segmentos": {"liga": [], "casa": [], "probabilidad": []},
             "clv": {"n": 0, "promedio": None, "positivos": 0, "con_multiples_capturas": 0}}
    if not inspect(db.get_bind()).has_table("selecciones_seguimiento"):
        return vacio
    local, visita = aliased(Equipo), aliased(Equipo)
    consulta = (
        select(SeleccionSeguimiento, Partido, local.nombre, visita.nombre)
        .join(Partido, Partido.id == SeleccionSeguimiento.partido_id)
        .join(local, local.id == Partido.local_id)
        .join(visita, visita.id == Partido.visitante_id)
    )
    if liga:
        consulta = consulta.where(Partido.liga == liga)
    if casa:
        consulta = consulta.where(SeleccionSeguimiento.casa == casa)
    filas = db.execute(
        consulta.order_by(SeleccionSeguimiento.seleccionada_en.desc(), SeleccionSeguimiento.id.desc())
    ).all()
    cierres: dict[tuple[int, str], dict] = {}
    ids_partidos = [partido.id for _, partido, _, _ in filas]
    if ids_partidos:
        for cuota, partido in db.execute(
            select(Cuota, Partido)
            .join(Partido, Partido.id == Cuota.partido_id)
            .where(Cuota.partido_id.in_(ids_partidos), Cuota.capturada_en < Partido.inicio_utc)
        ).all():
            clave = (cuota.partido_id, cuota.casa)
            actual = cierres.get(clave)
            if actual is None:
                cierres[clave] = {"cuota": cuota, "capturas": 1}
            else:
                actual["capturas"] += 1
                if (cuota.actualizada_en, cuota.capturada_en, cuota.id) > (
                    actual["cuota"].actualizada_en, actual["cuota"].capturada_en, actual["cuota"].id,
                ):
                    actual["cuota"] = cuota
    salida = []
    evaluadas = aciertos = 0
    retorno = 0.0
    for seleccion, partido, nombre_local, nombre_visita in filas:
        valor_esperado = seleccion.probabilidad * seleccion.cuota_decimal - 1
        if (seleccion.probabilidad < min_probabilidad or valor_esperado < min_valor
                or (cuota_min is not None and seleccion.cuota_decimal < cuota_min)
                or (cuota_max is not None and seleccion.cuota_decimal > cuota_max)
                or seleccion.estado_registro == "descartada"):
            continue
        monto_aplicado = _monto(monto) if monto is not None else seleccion.monto
        terminada = partido.goles_local is not None and partido.goles_visitante is not None
        cierre = cierres.get((partido.id, seleccion.casa))
        cuota_cierre = None
        capturas_cuotas = cierre["capturas"] if cierre else 0
        if cierre and partido.inicio_utc and (terminada or _utc(partido.inicio_utc) <= datetime.now(timezone.utc)):
            campo = "cuota_local" if seleccion.lado == "local" else "cuota_visitante"
            cuota_cierre = getattr(cierre["cuota"], campo)
        clv = (seleccion.cuota_decimal / cuota_cierre - 1) if cuota_cierre else None
        ganada = None
        if terminada:
            resultado = "local" if partido.goles_local > partido.goles_visitante else (
                "visitante" if partido.goles_visitante > partido.goles_local else "empate"
            )
            ganada = seleccion.lado == resultado
            evaluadas += 1
            aciertos += int(ganada)
            retorno += monto_aplicado * seleccion.cuota_decimal if ganada else 0.0
        salida.append({
            "id": seleccion.id, "partido_id": partido.id, "local": nombre_local,
            "visitante": nombre_visita, "liga": nombre_liga(partido.liga),
            "fecha": partido.inicio_utc.date().isoformat() if partido.inicio_utc else None,
            "lado": seleccion.lado, "seleccion": nombre_local if seleccion.lado == "local" else nombre_visita,
            "probabilidad": seleccion.probabilidad, "cuota": seleccion.cuota_decimal,
            "probabilidad_mercado": 1 / seleccion.cuota_decimal,
            "diferencia_modelo_mercado": seleccion.probabilidad - (1 / seleccion.cuota_decimal),
            "cuota_cierre": cuota_cierre, "clv": clv, "capturas_cuotas": capturas_cuotas,
            "casa": seleccion.casa, "seleccionada_en": seleccion.seleccionada_en,
            "version_modelo": seleccion.version_modelo, "publicado_en": seleccion.publicado_en,
            "monto": monto_aplicado, "estado_registro": seleccion.estado_registro,
            "valor_esperado": valor_esperado,
            "terminada": terminada, "ganada": ganada,
            "marcador": f"{partido.goles_local}-{partido.goles_visitante}" if terminada else None,
            "ganancia": (monto_aplicado * (seleccion.cuota_decimal - 1) if ganada else -monto_aplicado) if terminada else None,
        })
    resumen = _resumen_individuales(salida)
    return {
        **resumen, "filas": salida[:limite], "filas_para_curva": salida, "unidad": UNIDAD,
        "segmentos": _segmentos_individuales(salida), "clv": _resumen_clv(salida),
    }


def estrategias(db: Session) -> list[EstrategiaSimulacion]:
    return list(db.scalars(select(EstrategiaSimulacion).order_by(EstrategiaSimulacion.creado_en.desc())))


def crear_estrategia(db: Session, nombre: str, liga: str | None, casa: str | None,
                     min_probabilidad: float, min_valor: float,
                     cuota_min: float | None, cuota_max: float | None, monto: float) -> EstrategiaSimulacion:
    if not nombre.strip():
        raise ValueError("La estrategia necesita un nombre")
    if cuota_min is not None and cuota_max is not None and cuota_min > cuota_max:
        raise ValueError("La cuota mínima no puede ser mayor que la máxima")
    estrategia = EstrategiaSimulacion(nombre=nombre.strip(), liga=liga or None, casa=casa or None,
        min_probabilidad=min_probabilidad, min_valor=min_valor, cuota_min=cuota_min,
        cuota_max=cuota_max, monto=_monto(monto))
    db.add(estrategia)
    return estrategia


def candidatas_parlay(db: Session, dias: int = 30) -> list[dict]:
    """Selecciones futuras que tienen cuotas reales por casa."""
    partidos = proximos_partidos(db, dias=dias)
    return agregar_cuotas(db, selecciones_destacadas(partidos, limite=len(partidos)))


def parlays_modelo_disponibles(db: Session) -> list[dict]:
    """Parlays sugeridos en Análisis, aplanados para poder fijarlos en Simulación."""
    disponibles = []
    for grupo, lista in parlays(candidatas_parlay(db)).items():
        for parlay in lista:
            ids = ",".join(str(s["id"]) for s in parlay["selecciones"])
            disponibles.append({**parlay, "grupo": grupo, "clave": f"{parlay['casa']}|{ids}"})
    return disponibles


def _monto(valor: float | str | None) -> float:
    try:
        monto = float(valor)
    except (TypeError, ValueError):
        monto = UNIDAD
    return min(max(monto, 1.0), 100_000.0)


def crear_parlay_simulado(
    db: Session,
    origen: str,
    casa: str,
    partido_ids: list[int],
    monto: float | str | None = UNIDAD,
) -> ParlaySimulado:
    """Fija un parlay de 2 a 4 partidos con cuotas de una sola casa."""
    if origen not in {"modelo", "personal"}:
        raise ValueError("Origen de parlay inválido")
    ids = list(dict.fromkeys(partido_ids))
    if not 2 <= len(ids) <= 4:
        raise ValueError("El parlay debe tener entre 2 y 4 partidos distintos")
    por_id = {s["id"]: s for s in candidatas_parlay(db)}
    try:
        selecciones = [por_id[identificador] for identificador in ids]
        cuotas = [s["cuotas_por_casa"][casa]["cuota"] for s in selecciones]
    except KeyError:
        raise ValueError("Una selección ya no tiene cuota válida en esa casa") from None
    if any(not math.isfinite(cuota) or cuota <= 1 for cuota in cuotas):
        raise ValueError("Las cuotas del parlay no son válidas")
    parlay = ParlaySimulado(
        origen=origen, casa=casa,
        probabilidad=math.prod(s["probabilidad"] for s in selecciones),
        cuota_decimal=math.prod(cuotas), monto=_monto(monto),
        creado_en=datetime.now(timezone.utc),
    )
    db.add(parlay)
    db.flush()
    for seleccion, cuota in zip(selecciones, cuotas):
        db.add(PiernaParlay(
            parlay_id=parlay.id, partido_id=seleccion["id"],
            pronostico_id=seleccion["pron"].id, lado=seleccion["lado"],
            probabilidad=seleccion["probabilidad"], cuota_decimal=cuota,
            version_modelo=seleccion["pron"].version_modelo,
            publicado_en=seleccion["pron"].publicado_en,
        ))
    return parlay


def rendimiento_parlays(db: Session, limite: int = 30) -> dict:
    """Evalúa parlays: basta una pierna perdida para cerrar la combinación."""
    vacio = {"total": 0, "evaluados": 0, "ganados": 0, "pendientes": 0,
             "inversion": 0.0, "retorno": 0.0, "ganancia": 0.0, "roi": None,
             "filas": [], "por_tipo": _resumen_tipos_parlay([])}
    if not inspect(db.get_bind()).has_table("parlays_simulados"):
        return vacio
    local, visita = aliased(Equipo), aliased(Equipo)
    parlays_guardados = list(db.scalars(
        select(ParlaySimulado).order_by(ParlaySimulado.creado_en.desc(), ParlaySimulado.id.desc())
    ))
    salida, evaluados, ganados, retorno = [], 0, 0, 0.0
    for parlay in parlays_guardados:
        if parlay.estado_registro == "descartada":
            continue
        piernas = db.execute(
            select(PiernaParlay, Partido, local.nombre, visita.nombre)
            .join(Partido, Partido.id == PiernaParlay.partido_id)
            .join(local, local.id == Partido.local_id)
            .join(visita, visita.id == Partido.visitante_id)
            .where(PiernaParlay.parlay_id == parlay.id)
            .order_by(PiernaParlay.id)
        ).all()
        detalle, perdida, todas_terminadas = [], False, True
        for pierna, partido, nombre_local, nombre_visita in piernas:
            terminada = partido.goles_local is not None and partido.goles_visitante is not None
            resultado = None
            if terminada:
                resultado = "local" if partido.goles_local > partido.goles_visitante else (
                    "visitante" if partido.goles_visitante > partido.goles_local else "empate"
                )
                perdida |= resultado != pierna.lado
            else:
                todas_terminadas = False
            detalle.append({
                "partido_id": partido.id, "local": nombre_local, "visitante": nombre_visita,
                "seleccion": nombre_local if pierna.lado == "local" else nombre_visita,
                "terminada": terminada, "ganada": resultado == pierna.lado if terminada else None,
            })
        estado = "Perdido" if perdida else ("Ganado" if todas_terminadas else "Pendiente")
        ganancia = None
        if estado != "Pendiente":
            evaluados += 1
            if estado == "Ganado":
                ganados += 1
                retorno += parlay.monto * parlay.cuota_decimal
                ganancia = parlay.monto * (parlay.cuota_decimal - 1)
            else:
                ganancia = -parlay.monto
        salida.append({
            "id": parlay.id, "origen": parlay.origen, "casa": parlay.casa,
            "probabilidad": parlay.probabilidad, "cuota": parlay.cuota_decimal,
            "monto": parlay.monto, "estado": estado, "estado_registro": parlay.estado_registro,
            "ganancia": ganancia, "piernas": detalle,
        })
    inversion = sum(p["monto"] for p in salida if p["estado"] != "Pendiente")
    return {
        "total": len(salida), "evaluados": evaluados, "ganados": ganados,
        "pendientes": len(salida) - evaluados, "inversion": inversion,
        "retorno": retorno, "ganancia": retorno - inversion,
        "roi": (retorno - inversion) / inversion if inversion else None,
        "filas": salida[:limite], "por_tipo": _resumen_tipos_parlay(salida),
    }


def _resumen_tipos_parlay(parlays: list[dict]) -> list[dict]:
    """Compara dobles, triples y cuádruples sin penalizar parlays pendientes."""
    nombres = {2: "Dobles", 3: "Triples", 4: "Cuádruples"}
    resumenes = []
    for piernas, nombre in nombres.items():
        grupo = [parlay for parlay in parlays if len(parlay["piernas"]) == piernas]
        evaluados = [parlay for parlay in grupo if parlay["estado"] != "Pendiente"]
        inversion = sum(parlay["monto"] for parlay in evaluados)
        retorno = sum(
            parlay["monto"] * parlay["cuota"]
            for parlay in evaluados if parlay["estado"] == "Ganado"
        )
        ganancia = retorno - inversion
        resumenes.append({
            "tipo": nombre, "total": len(grupo), "evaluados": len(evaluados),
            "ganados": sum(parlay["estado"] == "Ganado" for parlay in evaluados),
            "ganancia": ganancia, "roi": ganancia / inversion if inversion else None,
        })
    return resumenes
