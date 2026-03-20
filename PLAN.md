# Plan de Integración: QuantipyMRX → SPSS InsightGenius API

## Situación Actual

La API reimplementa manualmente en `quantipy_engine.py` y `tabulation_builder.py` funcionalidad
que ya existe en QuantipyMRX: z-tests, t-tests, crosstabs, frecuencias, NPS, T2B/B2B.
Además, MRX tiene capacidades que la API no expone en absoluto: chi-square, ANOVA,
correlaciones, gap analysis, suggest_banners, Google Sheets export, preset nets.

**Dato clave**: `mrx_crosstab` se importa en `quantipy_engine.py:28` pero nunca se usa.

---

## Fases de Implementación

### Fase 1: Refactor del Engine — Delegar a MRX (Alta prioridad)

**Objetivo**: Reemplazar lógica manual de estadística por llamadas a QuantipyMRX.
Esto elimina duplicación y gana funcionalidad gratis (chi-square, row_pct, etc.).

#### 1.1 Refactor `quantipy_engine.py` — Usar `crosstab()` de MRX

**Archivo**: `services/quantipy_engine.py`

**Cambio**: El método `crosstab_with_significance()` (líneas 337-519, ~180 líneas) reimplementa
lo que `quantipymrx.analysis.crosstab.crosstab()` ya hace nativamente, incluyendo:
- Column percentages con sig letters
- Chi-square test con validación de celdas
- Row percentages y total percentages
- Soporte para weighted y multi-choice x variables

**Acción**:
- Cuando `QUANTIPYMRX_AVAILABLE=True`: delegar a `crosstab(dataset, x, y, weight, sig_level)`
  y convertir `CrosstabResult` al dict shape actual de la API (mantener contrato)
- Cuando `QUANTIPYMRX_AVAILABLE=False`: mantener implementación pandas actual como fallback
- **Ganancia nueva**: añadir `chi2` y `chi2_pvalue` al response (campo nuevo, no rompe contrato)
- **Ganancia nueva**: añadir `row_percentages` opcional al response

**Response shape actualizado** (`schemas/responses.py`):
```python
class CrosstabResponse(BaseModel):
    # ... campos existentes sin cambio ...
    chi2: float | None = None           # NUEVO
    chi2_pvalue: float | None = None    # NUEVO
    chi2_warning: str | None = None     # NUEVO
    row_percentages: dict | None = None # NUEVO (opcional, opt-in)
```

**Tests**: Actualizar `tests/test_crosstab.py` — verificar que chi2 se retorna.

#### 1.2 Refactor `quantipy_engine.py` — Usar `frequency()` de MRX

**Archivo**: `services/quantipy_engine.py`

**Cambio**: El método `frequency()` (líneas 240-335) es funcional pero no retorna
mean, std, median, ni maneja delimited sets (MRS frequency).
MRX `frequency()` retorna `FrequencyResult` con todo esto.

**Acción**:
- Cuando MRX disponible: delegar a `frequency(dataset, variable, weight)`
  y convertir `FrequencyResult` al dict shape actual
- Añadir campos nuevos al response

**Response shape actualizado** (`schemas/responses.py`):
```python
class FrequencyResponse(BaseModel):
    # ... campos existentes sin cambio ...
    mean: float | None = None      # NUEVO
    std: float | None = None       # NUEVO
    median: float | None = None    # NUEVO
    is_weighted: bool = False      # NUEVO
```

**Tests**: Actualizar `tests/test_frequency.py`.

#### 1.3 Refactor NPS — Usar `calculate_nps()` de MRX

**Archivo**: `services/quantipy_engine.py`

**Cambio**: El método `nps()` (líneas 521-550) es básico.
MRX `calculate_nps()` soporta escalas configurables (0-10, 1-10, 1-5),
pesos, y categorización (Excellent/Great/Good/Needs Improvement/Critical).

**Acción**:
- Delegar a `calculate_nps()` de `quantipymrx.analysis.mrx`
- Añadir `category` al response (e.g., "Great")
- Añadir `scale` al response (e.g., "0-10")

#### 1.4 Limpiar imports no usados

**Archivo**: `services/quantipy_engine.py`

**Cambio**: `mrx_crosstab` se importa (línea 28) pero nunca se usa. Limpiar.
Reorganizar imports para reflejar los nuevos módulos de MRX usados.

---

### Fase 2: Nuevos Endpoints — Exponer capacidades MRX (Alta prioridad)

**Objetivo**: Crear endpoints para funcionalidad que MRX ya tiene implementada
pero la API no expone. Código de lógica = 0, solo routing + validación.

#### 2.1 `POST /v1/correlation` — Análisis de correlación

**Archivos nuevos/modificados**:
- `routers/correlation.py` (nuevo)
- `schemas/requests.py` — añadir `CorrelationRequest`
- `schemas/responses.py` — añadir `CorrelationResponse`
- `main.py` — registrar router

**Usa**: `quantipymrx.analysis.significance.correlation()` y `correlation_matrix()`

**Request**:
```python
class CorrelationRequest(BaseModel):
    variables: list[str]           # 2+ variables
    method: str = "pearson"        # pearson | spearman | kendall
    weight: str | None = None
```

**Response**: matriz de correlación + p-values + significancia

**Scope de auth**: `analysis` (nuevo scope, o reusar `crosstab`)

#### 2.2 `POST /v1/anova` — ANOVA con post-hoc

**Archivos nuevos/modificados**:
- `routers/anova.py` (nuevo)
- `schemas/requests.py` — añadir `AnovaRequest`
- `schemas/responses.py` — añadir `AnovaResponse`
- `main.py` — registrar router

**Usa**: `quantipymrx.analysis.significance.anova_oneway()` con Tukey HSD

**Request**:
```python
class AnovaRequest(BaseModel):
    dependent: str                  # variable numérica
    factor: str                     # variable categórica (grupos)
    weight: str | None = None
    post_hoc: bool = True           # Tukey HSD
```

**Response**: F-statistic, p-value, eta-squared, comparaciones Tukey por pares

#### 2.3 `POST /v1/gap-analysis` — Importance-Performance

**Archivos nuevos/modificados**:
- `routers/gap_analysis.py` (nuevo)
- `schemas/requests.py` — añadir `GapAnalysisRequest`
- `schemas/responses.py` — añadir `GapAnalysisResponse`
- `main.py` — registrar router

**Usa**: `quantipymrx.analysis.mrx.gap_analysis()`

**Request**:
```python
class GapAnalysisRequest(BaseModel):
    importance_vars: list[str]      # variables de importancia
    performance_vars: list[str]     # variables de desempeño (pareadas)
    weight: str | None = None
```

**Response**: gaps, prioridades (High/Medium/Low), cuadrantes (Concentrate Here, Keep Up, etc.)

#### 2.4 `POST /v1/satisfaction-summary` — Resumen integrado

**Usa**: `quantipymrx.analysis.mrx.satisfaction_summary()`

**Response**: T2B, B2B, mean, distribución en una sola llamada por variable.

---

### Fase 3: Enriquecer Metadata — Auto-configuración (Media prioridad)

**Objetivo**: Que el frontend pueda auto-configurarse mejor usando la detección
avanzada de MRX.

#### 3.1 Enriquecer `POST /v1/metadata` con sugerencias

**Archivo**: `routers/metadata.py`, `services/quantipy_engine.py`

**Cambio**: Además de `auto_detect`, incluir:
- `suggested_banners`: resultado de `suggest_banners(dataset, max_banners=5)`
- `detected_groups`: resultado de `detect_groups(dataset)` — grids, MRS, top-of-mind
- `detected_question_types`: mapeo variable → QuestionType enum

**Usa**:
- `quantipymrx.analysis.auto_detect.suggest_banners()`
- `quantipymrx.analysis.auto_detect.detect_groups()`

**Response shape actualizado**:
```python
class MetadataResponse(BaseModel):
    # ... campos existentes sin cambio ...
    suggested_banners: list[dict] | None = None    # NUEVO
    detected_groups: list[dict] | None = None      # NUEVO
    question_types: dict[str, str] | None = None   # NUEVO: {"Q1": "SCALE", "Q2": "NPS"}
```

**Impacto frontend**: El UI puede pre-seleccionar banners, auto-crear MRS groups,
y sugerir nets basados en el tipo detectado.

#### 3.2 Endpoint de preset nets

**Archivo**: `routers/metadata.py` (o nuevo `routers/presets.py`)

**Acción**: Exponer los preset nets de MRX como endpoint GET o incluirlos en metadata:
- `LIKERT_5_NETS`: {"Top 2 Box": [4, 5], "Bottom 2 Box": [1, 2]}
- `LIKERT_7_NETS`: {"Top 2 Box": [6, 7], "Bottom 2 Box": [1, 2]}
- `SATISFACTION_5_NETS`: {"Satisfied": [4, 5], "Dissatisfied": [1, 2]}

**Cambio en metadata response**: para cada variable de tipo SCALE, sugerir los nets
apropiados basados en su rango de valores.

---

### Fase 4: Tabulation Builder — Usar MRX internamente (Media prioridad)

**Objetivo**: Simplificar `tabulation_builder.py` delegando cálculos a MRX.

#### 4.1 Reemplazar `_mrs_crosstab()` con MRX crosstab multi-x

**Archivo**: `services/tabulation_builder.py`

**Cambio**: La función `_mrs_crosstab()` (líneas 343-425) reimplementa crosstab para
MRS manualmente. MRX `crosstab()` ya maneja `is_multi` variables nativamente via
`_crosstab_multi_x()`.

**Acción**: Delegar a `crosstab(dataset, x=member_group, y=banner)` de MRX.
Convertir `CrosstabResult` al formato interno del builder.

#### 4.2 Reemplazar `_compute_means_by_column()` con MRX t-test

**Archivo**: `services/tabulation_builder.py`

**Cambio**: `_compute_means_by_column()` (líneas 600-650) y
`_add_mean_sig_to_grid_row()` (líneas 537-563) usan `scipy.stats.ttest_ind` directo.

**Acción**: Usar `t_test_means()` de `quantipymrx.analysis.significance` que ya
calcula Cohen's d y confidence intervals.

#### 4.3 Reemplazar `_add_prop_sig_to_grid_row()` con MRX z-test

**Archivo**: `services/tabulation_builder.py`

**Cambio**: `_add_prop_sig_to_grid_row()` (líneas 566-598) reimplementa z-test.

**Acción**: Usar `z_test_proportions()` de `quantipymrx.analysis.significance`.

---

### Fase 5: Google Sheets Export (Baja prioridad)

#### 5.1 `POST /v1/export-gsheets` — Exportar a Google Sheets

**Archivos nuevos/modificados**:
- `routers/export_gsheets.py` (nuevo)
- `config.py` — añadir `GOOGLE_CREDENTIALS_JSON` env var
- `main.py` — registrar router

**Usa**: `quantipymrx.io.gsheets_export.GoogleSheetsExporter`

**Request**:
```python
# Form data
file: UploadFile           # .sav
spec: str                  # JSON con análisis a exportar
share_with: str | None     # emails para compartir
```

**Response**: `{"spreadsheet_url": "https://docs.google.com/...", "spreadsheet_id": "..."}`

**Dependencia nueva**: `gspread`, `google-auth` en requirements.txt
**Env var nueva**: `GOOGLE_CREDENTIALS_JSON` (service account)

---

### Fase 6: Uso avanzado del GroupingEngine (Baja prioridad)

#### 6.1 `POST /v1/auto-analyze` — Análisis automático completo

**Concepto**: Un endpoint que recibe un .sav y devuelve un análisis completo
auto-generado usando toda la pipeline de MRX:
1. `auto_detect(dataset)` → ProcessingSpec
2. `process_all_groups(dataset, spec)` → resultados agrupados
3. `export_processing_results()` → Excel

**Usa**:
- `quantipymrx.analysis.auto_detect.auto_detect()`
- `quantipymrx.analysis.grouping.process_all_groups()`
- `quantipymrx.io.excel_export.export_processing_results()`

**Es el "modo fácil"**: sube un .sav, recibe un Excel analizado sin configurar nada.

---

## Orden de Implementación

```
Fase 1 (Refactor Engine)         ← Primero: elimina deuda técnica
  1.1 crosstab → MRX             ~2h   Impacto: alto, riesgo: medio
  1.2 frequency → MRX            ~1h   Impacto: medio, riesgo: bajo
  1.3 NPS → MRX                  ~30m  Impacto: bajo, riesgo: bajo
  1.4 Limpiar imports             ~15m  Impacto: bajo, riesgo: nulo

Fase 2 (Nuevos Endpoints)        ← Segundo: features nuevos gratis
  2.1 /v1/correlation             ~1h   Impacto: alto, riesgo: bajo
  2.2 /v1/anova                   ~1h   Impacto: alto, riesgo: bajo
  2.3 /v1/gap-analysis            ~1h   Impacto: medio, riesgo: bajo
  2.4 /v1/satisfaction-summary    ~30m  Impacto: medio, riesgo: bajo

Fase 3 (Metadata enriquecido)    ← Tercero: mejor UX
  3.1 suggested_banners + groups  ~1h   Impacto: alto, riesgo: bajo
  3.2 Preset nets por tipo        ~30m  Impacto: medio, riesgo: bajo

Fase 4 (Builder refactor)        ← Cuarto: limpieza interna
  4.1 MRS crosstab → MRX          ~1h   Impacto: bajo, riesgo: medio
  4.2 Means → MRX t-test          ~30m  Impacto: bajo, riesgo: bajo
  4.3 Prop sig → MRX z-test       ~30m  Impacto: bajo, riesgo: bajo

Fase 5 (Google Sheets)           ← Quinto: feature nuevo
  5.1 /v1/export-gsheets          ~2h   Impacto: medio, riesgo: medio

Fase 6 (Auto-analyze)            ← Sexto: modo fácil
  6.1 /v1/auto-analyze            ~2h   Impacto: alto, riesgo: medio
```

## Principios

1. **No romper contratos** — Campos nuevos son aditivos (default None). Response shapes existentes no cambian.
2. **Fallback siempre** — Si MRX no está disponible, la implementación pandas actual sigue funcionando.
3. **Tests primero** — Cada cambio tiene test correspondiente antes de merge.
4. **Un PR por fase** — Cada fase es un PR independiente, deployable por separado.
