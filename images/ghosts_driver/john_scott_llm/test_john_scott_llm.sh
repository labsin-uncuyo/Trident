#!/bin/bash
# Script para testear el agente John Scott con LLM
# Uso: ./test_john_scott_llm.sh [comando]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

cd "$PROJECT_ROOT"

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Funciones de testing
rebuild() {
    log_info "Reconstruyendo imagen ghosts_driver con soporte LLM..."
    docker compose stop ghosts_driver
    docker compose rm -f ghosts_driver
    docker compose build ghosts_driver
    log_success "Imagen reconstruida"
}

start() {
    log_info "Iniciando agente John Scott LLM..."
    docker compose up -d ghosts_driver
    sleep 5
    log_success "Agente iniciado"
}

stop() {
    log_info "Deteniendo agente John Scott LLM..."
    docker compose stop ghosts_driver
    log_success "Agente detenido"
}

restart() {
    stop
    start
}

logs() {
    local lines="${1:-50}"
    log_info "Mostrando últimas $lines líneas de logs..."
    docker logs lab_ghosts_driver 2>&1 | tail -n "$lines"
}

logs_live() {
    log_info "Siguiendo logs en tiempo real (Ctrl+C para salir)..."
    docker logs -f lab_ghosts_driver 2>&1
}

check_llm_generation() {
    log_info "Verificando generación de timeline con LLM..."
    if docker logs lab_ghosts_driver 2>&1 | grep -q "LLM Timeline Generator"; then
        log_success "✓ Generador LLM ejecutado"
        docker logs lab_ghosts_driver 2>&1 | grep "LLM Timeline Generator\|Timeline generated"
        return 0
    else
        log_error "✗ Generador LLM NO encontrado"
        return 1
    fi
}

check_bash_thread() {
    log_info "Verificando inicialización del thread Bash..."
    if docker logs lab_ghosts_driver 2>&1 | grep -q "Attempting new thread for: Bash"; then
        log_success "✓ Thread Bash inicializado correctamente"
        docker logs lab_ghosts_driver 2>&1 | grep "Attempting new thread for: Bash"
        return 0
    else
        log_error "✗ Thread Bash NO encontrado"
        return 1
    fi
}

check_ssh_commands() {
    log_info "Verificando ejecución de comandos SSH..."
    local ssh_count=$(docker logs lab_ghosts_driver 2>&1 | grep -c "Spawning bash with command ssh" || echo "0")
    if [ "$ssh_count" -gt 0 ]; then
        log_success "✓ Se han ejecutado $ssh_count comandos SSH"
        return 0
    else
        log_warning "✗ No se han ejecutado comandos SSH aún"
        return 1
    fi
}

check_llm_queries() {
    log_info "Verificando consultas generadas por LLM..."
    local llm_count=$(docker logs lab_ghosts_driver 2>&1 | grep -c "JOHN_SCOTT_LLM" || echo "0")
    if [ "$llm_count" -gt 0 ]; then
        log_success "✓ Se detectaron $llm_count actividades generadas por LLM"
        return 0
    else
        log_warning "✗ No se detectaron actividades LLM aún"
        return 1
    fi
}

show_john_scott_activity() {
    log_info "Actividad de John Scott LLM:"
    echo ""
    docker logs lab_ghosts_driver 2>&1 | grep -E "\[JOHN_SCOTT_LLM\]|LLM-powered" | tail -n 20
}

show_llm_generated_queries() {
    log_info "Consultas SQL generadas por LLM:"
    echo ""
    docker logs lab_ghosts_driver 2>&1 | grep -E "Generated query|Generating query" | tail -n 10
}

show_db_results() {
    log_info "Resultados de consultas a la base de datos:"
    echo ""
    docker logs lab_ghosts_driver 2>&1 | grep -A 10 "TIMELINE.*psql" | tail -n 50
}

test_llm_connection() {
    log_info "Probando conexión con LLM..."
    docker exec lab_ghosts_driver bash -c "cd /opt/john_scott_llm && python3 -c 'from llm_query_generator import LLMQueryGenerator; g = LLMQueryGenerator(); print(\"LLM Connection:\", \"OK\" if g.openai_api_key else \"MISSING API KEY\")'"
}

regenerate_timeline() {
    log_info "Regenerando timeline con LLM..."
    docker exec lab_ghosts_driver bash -c "cd /opt/john_scott_llm && ./generate_timeline.sh"
    log_success "Timeline regenerado"
}

status() {
    log_info "=== ESTADO DEL AGENTE JOHN SCOTT LLM ==="
    echo ""
    
    # Estado del contenedor
    if docker ps --filter name=lab_ghosts_driver --format "{{.Status}}" | grep -q "Up"; then
        log_success "Contenedor: RUNNING"
        docker ps --filter name=lab_ghosts_driver --format "Status: {{.Status}}"
    else
        log_error "Contenedor: STOPPED"
        return 1
    fi
    
    echo ""
    check_llm_generation
    echo ""
    check_bash_thread
    echo ""
    check_ssh_commands
    echo ""
    check_llm_queries
    echo ""
    show_john_scott_activity
}

full_test() {
    log_info "=== TEST COMPLETO DEL AGENTE JOHN SCOTT LLM ==="
    echo ""
    
    rebuild
    echo ""
    start
    echo ""
    
    log_info "Esperando 20 segundos para que el agente ejecute comandos..."
    sleep 20
    
    echo ""
    status
    echo ""
    
    log_info "=== Últimos 40 logs ==="
    logs 40
}

help() {
    cat << EOF
${GREEN}Script de Testing para Agente John Scott LLM${NC}

${YELLOW}Uso:${NC}
    ./test_john_scott_llm.sh [comando]

${YELLOW}Comandos disponibles:${NC}
    ${BLUE}rebuild${NC}           - Reconstruir imagen Docker
    ${BLUE}start${NC}             - Iniciar agente
    ${BLUE}stop${NC}              - Detener agente  
    ${BLUE}restart${NC}           - Reiniciar agente
    ${BLUE}logs [N]${NC}          - Ver últimas N líneas de logs (default: 50)
    ${BLUE}logs-live${NC}         - Seguir logs en tiempo real
    ${BLUE}status${NC}            - Ver estado completo del agente
    ${BLUE}check-llm${NC}         - Verificar generación con LLM
    ${BLUE}check-bash${NC}        - Verificar thread Bash
    ${BLUE}check-ssh${NC}         - Verificar comandos SSH
    ${BLUE}check-queries${NC}     - Verificar consultas LLM
    ${BLUE}activity${NC}          - Ver actividad de John Scott LLM
    ${BLUE}queries${NC}           - Ver consultas SQL generadas
    ${BLUE}db-results${NC}        - Ver resultados de consultas DB
    ${BLUE}test-llm${NC}          - Probar conexión LLM
    ${BLUE}regenerate${NC}        - Regenerar timeline con LLM
    ${BLUE}full-test${NC}         - Ejecutar test completo
    ${BLUE}help${NC}              - Mostrar esta ayuda

${YELLOW}Ejemplos:${NC}
    ./test_john_scott_llm.sh full-test
    ./test_john_scott_llm.sh restart
    ./test_john_scott_llm.sh logs 100
    ./test_john_scott_llm.sh status
    ./test_john_scott_llm.sh regenerate

EOF
}

# Main
case "${1:-help}" in
    rebuild)
        rebuild
        ;;
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    logs)
        logs "${2:-50}"
        ;;
    logs-live)
        logs_live
        ;;
    status)
        status
        ;;
    check-llm)
        check_llm_generation
        ;;
    check-bash)
        check_bash_thread
        ;;
    check-ssh)
        check_ssh_commands
        ;;
    check-queries)
        check_llm_queries
        ;;
    activity)
        show_john_scott_activity
        ;;
    queries)
        show_llm_generated_queries
        ;;
    db-results)
        show_db_results
        ;;
    test-llm)
        test_llm_connection
        ;;
    regenerate)
        regenerate_timeline
        ;;
    full-test)
        full_test
        ;;
    help|--help|-h)
        help
        ;;
    *)
        log_error "Comando desconocido: $1"
        echo ""
        help
        exit 1
        ;;
esac
