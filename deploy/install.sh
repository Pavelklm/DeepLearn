#!/bin/bash
# =============================================================================
# Скрипт автоматического развертывания Crypto Scanner
# Ubuntu 22.04 LTS
# =============================================================================

set -euo pipefail

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Логирование
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Проверка прав root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "Этот скрипт должен запускаться с правами root"
        echo "Используйте: sudo $0"
        exit 1
    fi
}

# Обновление системы
update_system() {
    log "Обновление системы..."
    apt update -y
    apt upgrade -y
    apt install -y curl wget git unzip software-properties-common
}

# Установка Python 3.11
install_python() {
    log "Установка Python 3.11..."
    
    if ! command -v python3.11 &> /dev/null; then
        add-apt-repository ppa:deadsnakes/ppa -y
        apt update -y
        apt install -y python3.11 python3.11-venv python3.11-dev python3-pip
    else
        log "Python 3.11 уже установлен"
    fi
    
    # Создаем символическую ссылку
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
}

# Установка дополнительных пакетов
install_dependencies() {
    log "Установка зависимостей..."
    apt install -y \
        nginx \
        supervisor \
        redis-server \
        htop \
        iotop \
        ncdu \
        fail2ban \
        ufw \
        certbot \
        python3-certbot-nginx
}

# Создание пользователя
create_user() {
    log "Создание пользователя cryptoscanner..."
    
    if ! id "cryptoscanner" &>/dev/null; then
        useradd -m -s /bin/bash cryptoscanner
        usermod -aG sudo cryptoscanner
        
        # Создание SSH ключей для пользователя
        sudo -u cryptoscanner ssh-keygen -t rsa -b 4096 -f /home/cryptoscanner/.ssh/id_rsa -N ""
    else
        log "Пользователь cryptoscanner уже существует"
    fi
}

# Клонирование репозитория
setup_application() {
    log "Настройка приложения..."
    
    APP_DIR="/home/cryptoscanner/Scanner"
    
    # Клонируем или обновляем репозиторий
    if [[ ! -d "$APP_DIR" ]]; then
        log "Клонирование репозитория..."
        sudo -u cryptoscanner git clone https://github.com/yourcompany/cryptoscanner.git "$APP_DIR"
    else
        log "Обновление репозитория..."
        cd "$APP_DIR"
        sudo -u cryptoscanner git pull origin main
    fi
    
    # Права доступа
    chown -R cryptoscanner:cryptoscanner "$APP_DIR"
    chmod 755 "$APP_DIR"
    
    # Создание виртуальной среды
    log "Создание виртуальной среды..."
    sudo -u cryptoscanner python3.11 -m venv "$APP_DIR/venv"
    
    # Установка зависимостей
    log "Установка Python пакетов..."
    sudo -u cryptoscanner "$APP_DIR/venv/bin/pip" install --upgrade pip
    sudo -u cryptoscanner "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"
    
    # Создание необходимых директорий
    sudo -u cryptoscanner mkdir -p "$APP_DIR/data/cache"
    sudo -u cryptoscanner mkdir -p "$APP_DIR/logs"
    sudo -u cryptoscanner mkdir -p "$APP_DIR/data/backups"
}

# Настройка .env файла
setup_env_file() {
    log "Настройка .env файла..."
    
    APP_DIR="/home/cryptoscanner/Scanner"
    ENV_FILE="$APP_DIR/.env"
    
    if [[ ! -f "$ENV_FILE" ]]; then
        sudo -u cryptoscanner cp "$APP_DIR/.env.example" "$ENV_FILE"
        sudo -u cryptoscanner chmod 600 "$ENV_FILE"
        
        warn "ВАЖНО: Отредактируйте файл $ENV_FILE и добавьте ваши API ключи!"
        warn "nano $ENV_FILE"
    else
        log ".env файл уже существует"
    fi
}

# Настройка systemd сервиса
setup_systemd_service() {
    log "Настройка systemd сервиса..."
    
    cp /home/cryptoscanner/Scanner/deploy/cryptoscanner.service /etc/systemd/system/
    
    systemctl daemon-reload
    systemctl enable cryptoscanner.service
    
    log "Сервис cryptoscanner настроен"
}

# Настройка Nginx
setup_nginx() {
    log "Настройка Nginx..."
    
    cat > /etc/nginx/sites-available/cryptoscanner << 'EOF'
server {
    listen 80;
    server_name localhost;  # Замените на ваш домен
    
    # WebSocket proxy
    location /ws/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket timeout
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
    
    # Health check
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }
    
    # Блокируем доступ к чувствительным файлам
    location ~ /\.(env|git) {
        deny all;
        return 404;
    }
}
EOF
    
    # Активируем сайт
    ln -sf /etc/nginx/sites-available/cryptoscanner /etc/nginx/sites-enabled/
    
    # Удаляем дефолтный сайт
    rm -f /etc/nginx/sites-enabled/default
    
    # Тестируем конфигурацию
    nginx -t
    systemctl reload nginx
    
    log "Nginx настроен"
}

# Настройка firewall
setup_firewall() {
    log "Настройка firewall..."
    
    # Разрешаем SSH, HTTP, HTTPS
    ufw allow ssh
    ufw allow 80/tcp
    ufw allow 443/tcp
    
    # Разрешаем WebSocket порт локально
    ufw allow from 127.0.0.1 to any port 8080
    
    # Включаем firewall
    ufw --force enable
    
    log "Firewall настроен"
}

# Настройка автоматических обновлений безопасности
setup_auto_updates() {
    log "Настройка автоматических обновлений..."
    
    apt install -y unattended-upgrades
    
    cat > /etc/apt/apt.conf.d/50unattended-upgrades << 'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}";
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};
Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
EOF
    
    systemctl enable unattended-upgrades
    systemctl start unattended-upgrades
}

# Настройка мониторинга логов
setup_log_rotation() {
    log "Настройка ротации логов..."
    
    cat > /etc/logrotate.d/cryptoscanner << 'EOF'
/home/cryptoscanner/Scanner/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 cryptoscanner cryptoscanner
    postrotate
        systemctl reload cryptoscanner || true
    endscript
}
EOF
    
    log "Ротация логов настроена"
}

# Создание скрипта мониторинга
create_monitoring_script() {
    log "Создание скрипта мониторинга..."
    
    cat > /home/cryptoscanner/monitor.sh << 'EOF'
#!/bin/bash
# Скрипт мониторинга Crypto Scanner

echo "=== Crypto Scanner Status ==="
echo "Date: $(date)"
echo

echo "=== Service Status ==="
systemctl status cryptoscanner --no-pager -l

echo
echo "=== Resource Usage ==="
echo "Memory usage:"
free -h

echo "Disk usage:"
df -h /home/cryptoscanner

echo "CPU load:"
uptime

echo
echo "=== Recent Logs ==="
journalctl -u cryptoscanner --no-pager -n 10

echo
echo "=== Network Connections ==="
ss -tulpn | grep :8080
EOF
    
    chmod +x /home/cryptoscanner/monitor.sh
    chown cryptoscanner:cryptoscanner /home/cryptoscanner/monitor.sh
}

# Проверка установки
verify_installation() {
    log "Проверка установки..."
    
    # Проверяем Python
    python3.11 --version
    
    # Проверяем сервис
    systemctl is-enabled cryptoscanner
    
    # Проверяем Nginx
    systemctl is-active nginx
    
    # Проверяем права файлов
    ls -la /home/cryptoscanner/Scanner/.env
    
    log "Установка завершена успешно!"
}

# Вывод инструкций
show_instructions() {
    echo
    echo -e "${BLUE}=== ИНСТРУКЦИИ ПОСЛЕ УСТАНОВКИ ===${NC}"
    echo
    echo "1. Настройте API ключи:"
    echo "   sudo -u cryptoscanner nano /home/cryptoscanner/Scanner/.env"
    echo
    echo "2. Протестируйте приложение:"
    echo "   sudo -u cryptoscanner /home/cryptoscanner/Scanner/venv/bin/python /home/cryptoscanner/Scanner/main.py --primary-scan-only"
    echo
    echo "3. Запустите сервис:"
    echo "   sudo systemctl start cryptoscanner"
    echo
    echo "4. Проверьте статус:"
    echo "   sudo systemctl status cryptoscanner"
    echo "   /home/cryptoscanner/monitor.sh"
    echo
    echo "5. Просмотр логов:"
    echo "   sudo journalctl -u cryptoscanner -f"
    echo
    echo "6. WebSocket тест:"
    echo "   curl -i -N -H \"Connection: Upgrade\" -H \"Upgrade: websocket\" http://localhost/ws/public"
    echo
    echo -e "${GREEN}Установка завершена!${NC}"
}

# Главная функция
main() {
    log "Начало установки Crypto Scanner..."
    
    check_root
    update_system
    install_python
    install_dependencies
    create_user
    setup_application
    setup_env_file
    setup_systemd_service
    setup_nginx
    setup_firewall
    setup_auto_updates
    setup_log_rotation
    create_monitoring_script
    verify_installation
    show_instructions
}

# Запуск
main "$@"
