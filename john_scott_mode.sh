#!/bin/bash
# Script helper para gestionar el modo de John Scott (dummy o llm)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

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

show_current_mode() {
    if [ -f "$ENV_FILE" ]; then
        local current_mode=$(grep "^JOHN_SCOTT_MODE=" "$ENV_FILE" | cut -d'=' -f2 || echo "dummy")
        if [ -z "$current_mode" ]; then
            current_mode="dummy"
        fi
        log_info "Modo actual: ${GREEN}$current_mode${NC}"
        
        if [ "$current_mode" = "llm" ]; then
            log_info "Configuración LLM:"
            grep -E "^(OPENAI_API_KEY|OPENAI_BASE_URL|LLM_MODEL|LLM_TEMPERATURE)=" "$ENV_FILE" 2>/dev/null || log_warning "Variables LLM no configuradas"
        fi
    else
        log_error "Archivo .env no encontrado"
        exit 1
    fi
}

set_mode() {
    local mode=$1
    
    if [ "$mode" != "dummy" ] && [ "$mode" != "llm" ]; then
        log_error "Modo inválido. Use: dummy o llm"
        exit 1
    fi
    
    if [ ! -f "$ENV_FILE" ]; then
        log_error "Archivo .env no encontrado"
        exit 1
    fi
    
    # Backup del .env
    cp "$ENV_FILE" "$ENV_FILE.backup.$(date +%Y%m%d_%H%M%S)"
    
    # Actualizar o agregar JOHN_SCOTT_MODE
    if grep -q "^JOHN_SCOTT_MODE=" "$ENV_FILE"; then
        sed -i "s/^JOHN_SCOTT_MODE=.*/JOHN_SCOTT_MODE=$mode/" "$ENV_FILE"
        log_success "Modo actualizado a: $mode"
    else
        echo "" >> "$ENV_FILE"
        echo "# John Scott Mode Configuration" >> "$ENV_FILE"
        echo "JOHN_SCOTT_MODE=$mode" >> "$ENV_FILE"
        log_success "Modo configurado a: $mode"
    fi
    
    if [ "$mode" = "llm" ]; then
        # Verificar que las variables LLM existan
        if ! grep -q "^OPENAI_API_KEY=" "$ENV_FILE"; then
            log_warning "Variables LLM no encontradas. Agregando plantilla..."
            cat >> "$ENV_FILE" << 'EOF'

# LLM Configuration for John Scott
OPENAI_API_KEY=YOUR_API_KEY
OPENAI_BASE_URL=https://chat.ai.e-infra.cz/api/v1
LLM_MODEL=qwen3-coder
LLM_TEMPERATURE=0.7
EOF
            log_info "Por favor, verifica las credenciales LLM en .env"
        fi
    fi
    
    log_info "Reconstruye la imagen para aplicar cambios:"
    echo "  docker compose build ghosts_driver"
    echo "  docker compose up -d ghosts_driver"
}

deploy_mode() {
    local mode=$1
    
    log_info "Configurando modo: $mode"
    set_mode "$mode"
    
    log_info "Reconstruyendo imagen..."
    docker compose build ghosts_driver
    
    log_info "Desplegando..."
    docker compose up -d ghosts_driver
    
    log_success "Agente John Scott desplegado en modo: $mode"
    
    log_info "Esperando 5 segundos..."
    sleep 5
    
    log_info "Mostrando logs iniciales:"
    docker logs lab_ghosts_driver --tail 30
}

status() {
    log_info "=== Estado de John Scott GHOSTS Driver ==="
    echo ""
    
    show_current_mode
    echo ""
    
    if docker ps --filter name=lab_ghosts_driver --format "{{.Status}}" | grep -q "Up"; then
        log_success "Contenedor: RUNNING"
        docker ps --filter name=lab_ghosts_driver --format "{{.Names}}\t{{.Status}}"
    else
        log_warning "Contenedor: STOPPED"
    fi
    echo ""
    
    log_info "Últimos logs:"
    docker logs lab_ghosts_driver --tail 20 2>&1 || log_warning "No hay logs disponibles"
}

test_mode() {
    local mode=$(grep "^JOHN_SCOTT_MODE=" "$ENV_FILE" | cut -d'=' -f2 || echo "dummy")
    
    log_info "Ejecutando test para modo: $mode"
    
    if [ "$mode" = "llm" ]; then
        cd "$SCRIPT_DIR/images/ghosts_driver/john_scott_llm"
        ./test_john_scott_llm.sh status
    else
        cd "$SCRIPT_DIR/images/ghosts_driver/john_scott_dummy"
        ./test_john_scott.sh status
    fi
}

help() {
    cat << EOF
${GREEN}John Scott GHOSTS Driver - Mode Manager${NC}

${YELLOW}Uso:${NC}
    ./john_scott_mode.sh [comando] [opciones]

${YELLOW}Comandos:${NC}
    ${BLUE}status${NC}              - Ver modo actual y estado del contenedor
    ${BLUE}show${NC}                - Mostrar modo actual
    ${BLUE}set [dummy|llm]${NC}     - Cambiar modo (requiere rebuild)
    ${BLUE}deploy [dummy|llm]${NC}  - Configurar, rebuild y desplegar
    ${BLUE}test${NC}                - Ejecutar test del modo actual
    ${BLUE}help${NC}                - Mostrar esta ayuda

${YELLOW}Ejemplos:${NC}
    # Ver estado actual
    ./john_scott_mode.sh status
    
    # Cambiar a modo LLM
    ./john_scott_mode.sh set llm
    
    # Desplegar en modo dummy
    ./john_scott_mode.sh deploy dummy
    
    # Probar funcionamiento
    ./john_scott_mode.sh test

${YELLOW}Descripción de Modos:${NC}
    ${BLUE}dummy${NC} - Usa queries SQL predefinidas (estático)
           • Rápido y predecible
           • Ideal para testing
           • No requiere API externa
    
    ${BLUE}llm${NC}   - Genera queries con IA (dinámico)
           • Comportamiento variable
           • Más realista
           • Requiere API de LLM configurada

${YELLOW}Archivos de Configuración:${NC}
    .env                                      - Variables de entorno
    images/ghosts_driver/john_scott_dummy/    - Configuración modo dummy
    images/ghosts_driver/john_scott_llm/      - Configuración modo LLM

${YELLOW}Documentación:${NC}
    images/ghosts_driver/README.md            - Documentación principal
    images/ghosts_driver/john_scott_llm/README.md  - Detalles modo LLM

EOF
}

# Main
case "${1:-help}" in
    status)
        status
        ;;
    show)
        show_current_mode
        ;;
    set)
        if [ -z "$2" ]; then
            log_error "Especifica el modo: dummy o llm"
            exit 1
        fi
        set_mode "$2"
        ;;
    deploy)
        if [ -z "$2" ]; then
            log_error "Especifica el modo: dummy o llm"
            exit 1
        fi
        deploy_mode "$2"
        ;;
    test)
        test_mode
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
