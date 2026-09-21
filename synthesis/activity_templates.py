TEMPLATE_VERSION = 2

LEGACY_TEMPLATE = "legado"
ACTIVE_TEMPLATE_KEYS = {
    "acao_evento",
    "entrega_marco",
    "atendimento_articulacao",
}

ACTIVITY_TEMPLATE_CHOICES = (
    (LEGACY_TEMPLATE, "Relato legado"),
    ("acao_evento", "Ação ou evento realizado"),
    ("entrega_marco", "Entrega ou marco concluído"),
    ("atendimento_articulacao", "Atendimento ou articulação"),
)

PUBLISHABLE_LIMITS = {
    "title": 80,
    "summary": 240,
    "result": 180,
    "beneficiaries": 80,
    "evidence": 100,
    "nextStep": 140,
    "internalNotes": 2000,
}

EDITORIAL_LIMITS = {
    "editorialTitle": PUBLISHABLE_LIMITS["title"],
    "editorialSummary": PUBLISHABLE_LIMITS["summary"],
    "editorialResult": PUBLISHABLE_LIMITS["result"],
    "editorialEvidence": PUBLISHABLE_LIMITS["evidence"],
    "editorialNextStep": PUBLISHABLE_LIMITS["nextStep"],
    "decisionRequest": 180,
    "nextStepOwner": 120,
}

EXECUTIVE_LIMITS = {
    "executiveSummary": 400,
    "sectionExecutiveSummary": 180,
}
