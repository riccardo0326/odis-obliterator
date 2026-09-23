# ==============================================================================
# ODIS Obliterator - Automated Task Runner
# Esegue sequenzialmente ciascun task in una sessione OpenCode pulita e isolata.
# ==============================================================================

$ErrorActionPreference = "Stop"

$tasks = @(
    "TASK-001",
    "TASK-002",
    "TASK-003",
    "TASK-004",
    "TASK-005",
    "TASK-006",
    "TASK-007",
    "TASK-008",
    "TASK-009",
    "TASK-010"
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  ODIS Obliterator - Avvio Esecuzione Sequenziale Task" -ForegroundColor Cyan
Write-Host "  Totale Task da eseguire: $($tasks.Count)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

foreach ($task in $tasks) {
    Write-Host "`n==========================================================" -ForegroundColor Yellow
    Write-Host ">>> AVVIO NUOVA SESSIONE: $task" -ForegroundColor Yellow
    Write-Host "==========================================================" -ForegroundColor Yellow

    $prompt = @"
Leggi con attenzione TASKS.md, CONTEXT.md, DESIGN.md e WORKFLOW.md.
Implementa completamente il task '$task' seguendo l'architettura stabilita.
Esegui la verifica del codice scrivendo ed eseguendo test unitari con pytest.
Una volta completato e verificato con successo il task, aggiorna lo stato di '$task' in TASKS.md impostandolo su 'COMPLETED'.
"@

    & opencode --auto --prompt $prompt

    if ($LASTEXITCODE -ne 0) {
        Write-Host "`n[ERRORE] Il task $task ha restituito un codice di errore ($LASTEXITCODE)." -ForegroundColor Red
        Write-Host "Interruzione del loop per consentire la verifica." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "`n[SUCCESSO] $task completato e verificato!" -ForegroundColor Green
    Start-Sleep -Seconds 2
}

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "  TUTTI I TASK SONO STATI COMPLETATI CON SUCCESSO! 🎉" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
